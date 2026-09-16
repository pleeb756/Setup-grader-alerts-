"""
A+ Setup Grader — alert runner for GitHub Actions.
Grades each coin on six checks (daily trend, 4H setup, 1H trigger) using
closed candles from Kraken, then sends a phone push alert (ntfy) when a coin
crosses into "setup forming" (5/6) or "A+ actionable" (6/6).
"""
import json, os, time, sys
from pathlib import Path
import requests
import pandas as pd

# ---------- settings ----------
WATCHLIST = {  # display name -> Kraken pair
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ZEC": "ZECUSD", "LINK": "LINKUSD", "UNI": "UNIUSD", "XLM": "XLMUSD",
    "HBAR": "HBARUSD",
}
NEAR_MET = 5            # checks met for "setup forming"
MIN_RR = 2.0            # minimum reward:risk
COOLDOWN_HRS = 4        # don't repeat the same tier for a coin within this window
STATE_FILE = Path("state.json")
LOG_FILE = Path("alerts_log.csv")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")

# ---------- data ----------
def candles(pair, minutes):
    r = requests.get("https://api.kraken.com/0/public/OHLC",
                     params={"pair": pair, "interval": minutes}, timeout=20)
    j = r.json()
    if j.get("error"):
        raise RuntimeError(f"{pair}: {j['error']}")
    key = next(k for k in j["result"] if k != "last")
    df = pd.DataFrame(j["result"][key],
                      columns=["t", "o", "h", "l", "c", "vwap", "v", "n"])
    df = df.astype({"o": float, "h": float, "l": float, "c": float, "v": float})
    return df.iloc[:-1].reset_index(drop=True)   # drop the still-forming bar

# ---------- indicators ----------
def ema(s, n): return s.ewm(span=n, adjust=False).mean()

def rsi(s, n=14):
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)

def atr(df, n=14):
    pc = df.c.shift()
    tr = pd.concat([df.h - df.l, (df.h - pc).abs(), (df.l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/n, adjust=False).mean()

def pivots(df, k=3):
    lows, highs = [], []
    for i in range(k, len(df) - k):
        w = df.iloc[i-k:i+k+1]
        if df.l[i] == w.l.min(): lows.append(df.l[i])
        if df.h[i] == w.h.max(): highs.append(df.h[i])
    return lows, highs

# ---------- grading ----------
def grade(d, h4, h1, side):
    L = side == "long"
    dc, e20d, e50d = d.c.iloc[-1], ema(d.c, 20).iloc[-1], ema(d.c, 50).iloc[-1]
    lows, highs = pivots(d)
    a4 = atr(h4).iloc[-1]
    e21_4h = ema(h4.c, 21).iloc[-1]
    r4, rd = rsi(h4.c), rsi(d.c).iloc[-1]
    entry = h1.c.iloc[-1]
    checks = {}

    # 1. Daily trend
    checks["trend"] = (dc > e50d and e20d > e50d) if L else (dc < e50d and e20d < e50d)
    # 2. Daily structure (higher low / lower high intact)
    if L:
        checks["structure"] = len(lows) >= 2 and lows[-1] > lows[-2] and dc > lows[-1]
        level = lows[-1] if lows else None
    else:
        checks["structure"] = len(highs) >= 2 and highs[-1] < highs[-2] and dc < highs[-1]
        level = highs[-1] if highs else None
    # 3. 4H pullback into the 21 EMA (below 50 EMA allowed if daily level holds)
    if L:
        checks["pullback"] = h4.l.tail(6).min() <= e21_4h and level is not None and h4.c.iloc[-1] > level
    else:
        checks["pullback"] = h4.h.tail(6).max() >= e21_4h and level is not None and h4.c.iloc[-1] < level
    # 4. RSI re-entry: 4H near 30 (70 for shorts) recently, daily near 50
    checks["rsi"] = ((r4.tail(6).min() <= 35) if L else (r4.tail(6).max() >= 65)) and 42 <= rd <= 58
    # 5. Reward:risk — stop beyond the daily level, target at next daily level
    rr, stop, target = None, None, None
    if level is not None:
        stop = level - 0.25 * a4 if L else level + 0.25 * a4
        tgts = [x for x in highs if x > entry] if L else [x for x in lows if x < entry]
        if tgts:
            target = min(tgts) if L else max(tgts)
            risk = abs(entry - stop)
            if risk > 0 and ((L and stop < entry) or (not L and stop > entry)):
                rr = abs(target - entry) / risk
    if rr is None:
        stop, target = None, None
    checks["rr"] = rr is not None and rr >= MIN_RR
    # 6. 1H trigger: 9/21 EMA cross in the last 3 closed bars, price on the right side
    e9, e21 = ema(h1.c, 9), ema(h1.c, 21)
    diff = (e9 - e21) if L else (e21 - e9)
    crossed = any(diff.iloc[i] > 0 >= diff.iloc[i-1] for i in range(-3, 0))
    checks["trigger"] = crossed and ((entry > e9.iloc[-1]) if L else (entry < e9.iloc[-1]))

    return {"side": side, "met": sum(checks.values()), "checks": checks,
            "entry": entry, "stop": stop, "target": target, "rr": rr,
            "rsi4h": r4.iloc[-1], "rsid": rd}

# ---------- alerts ----------
def send(msg, urgent=False):
    if not NTFY_TOPIC:
        print("[no NTFY_TOPIC set]\n" + msg); return
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Setup Grader",
                           "Priority": "high" if urgent else "default"},
                  timeout=20)

def fmt(p):
    if p is None: return "–"
    return f"{p:,.2f}" if p >= 1 else f"{p:.5f}"

def backtest(bars=180):
    """List every Sniper signal in the last `bars` closed 4H candles (no alerts sent)."""
    for coin, pair in WATCHLIST.items():
        try:
            h4, m5 = candles(pair, 240), candles(pair, 5)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}"); continue
        found = 0
        for i in range(len(h4) - bars, len(h4)):
            sub = h4.iloc[:i + 1].reset_index(drop=True)
            close_t = sub.t.iloc[-1] + 4 * 3600
            m = m5[m5.t + 300 <= close_t]
            sn = sniper(sub, m if len(m) > 30 else sub)
            if sn and sn["score"] >= SN_MIN:
                found += 1
                when = time.strftime('%b %d %H:%M', time.gmtime(sub.t.iloc[-1]))
                note = "" if len(m) > 30 else " (5m RSI est.)"
                print(f"{coin} {when} UTC  {sn['side'].upper():5} {sn['score']}/7  "
                      f"entry {fmt(sn['entry'])}  TP1 {fmt(sn['tps'][0])}{note}")
        if not found:
            print(f"{coin}: no signals")

def main():
    if "--test" in sys.argv:
        send("✅ Grader alerts are connected."); return
    if "--backtest" in sys.argv:
        backtest(); return
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now, changed, log = time.time(), False, []

    for coin, pair in WATCHLIST.items():
        try:
            d, h4, h1 = candles(pair, 1440), candles(pair, 240), candles(pair, 60)
        except Exception as e:
            print(f"skip {coin}: {e}"); continue
        best = max((grade(d, h4, h1, s) for s in ("long", "short")), key=lambda g: g["met"])
        tier = 2 if best["met"] == 6 else 1 if best["met"] >= NEAR_MET else 0
        prev = state.get(coin, {"tier": 0, "sent": {}})
        sent = prev.get("sent", {})
        print(f"{coin}: {best['side']} {best['met']}/6 tier {tier}")

        # alert on a move up into a tier, unless that tier already alerted within the cooldown
        if tier > prev["tier"] and now - sent.get(str(tier), 0) > COOLDOWN_HRS * 3600:
            label = "🚨 A+ SETUP" if tier == 2 else "👀 Setup forming"
            missing = [k for k, v in best["checks"].items() if not v]
            rr = f" ({best['rr']:.1f}R)" if best["rr"] else ""
            msg = (f"{label}: {coin} {best['side'].upper()} {best['met']}/6\n"
                   f"Price {fmt(best['entry'])} | Stop {fmt(best['stop'])} | Target {fmt(best['target'])}{rr}\n"
                   f"RSI 4H {best['rsi4h']:.0f} / D {best['rsid']:.0f}"
                   + (f"\nMissing: {', '.join(missing)}" if missing else ""))
            send(msg, urgent=(tier == 2))
            log.append(f"{time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))},{coin},{best['side']},{best['met']},{best['entry']}")
            sent[str(tier)] = now
        if tier != prev["tier"] or sent != prev.get("sent", {}):
            state[coin] = {"tier": tier, "sent": sent}; changed = True

    if changed:
        STATE_FILE.write_text(json.dumps(state, indent=1))
    if log:
        new = not LOG_FILE.exists()
        with LOG_FILE.open("a") as f:
            if new: f.write("utc,coin,side,met,price\n")
            f.write("\n".join(log) + "\n")

if __name__ == "__main__":
    main()
