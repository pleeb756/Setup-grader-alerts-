"""
A+ Setup Grader — alert runner for GitHub Actions.
Grades each coin on six checks (daily trend, 4H setup, 1H trigger) using
closed candles from Kraken, then sends a phone push alert (ntfy) when a coin
crosses into "setup forming" (5/6) or "A+ actionable" (6/6).
Also scans 5m candles for scalp setups (breakout, pullback, momentum burst).
"""
import json, os, time, sys
from pathlib import Path
import requests
import pandas as pd

# ---------- settings ----------
WATCHLIST = {  # display name -> Kraken pair
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ZEC": "ZECUSD", "LINK": "LINKUSD", "UNI": "UNIUSD", "XLM": "XLMUSD",
    "HBAR": "HBARUSD", "NEAR": "NEARUSD",
}
NEAR_MET = 5            # checks met for "setup forming"
MIN_RR = 2.0            # minimum reward:risk
BO_LOOKBACK = 20        # 4H bars for the breakout range
BO_VOL_MULT = 1.5       # breakout bar volume vs 20-bar average
BO_COOLDOWN_HRS = 12
# Viprasol Sniper Confluence settings (matching your chart: 9 21 4 1.5 14, 5m RSI)
SN_FAST, SN_SLOW, SN_MIN, SN_ATR_MULT, SN_ATR_LEN = 9, 21, 4, 1.5, 14
SN_VOL_LEN = 20
COOLDOWN_HRS = 4        # don't repeat the same tier for a coin within this window
STATE_FILE = Path("state.json")
LOG_FILE = Path("alerts_log.csv")

# scalp module (5m entries, 15m trend) — mirrors the Pine settings 36 / 2.5 / 4 / 1.8 / 80
SC_LOOK = int(os.environ.get("SC_LOOK", "36"))            # 5m bars for the breakout range
SC_VOL_MULT = float(os.environ.get("SC_VOL_MULT", "2.5")) # breakout bar volume vs 20-bar average
SC_BURST_ATR = float(os.environ.get("SC_BURST_ATR", "4")) # burst size in ATR over 12 bars
SC_BURST_VOL = float(os.environ.get("SC_BURST_VOL", "1.8"))
SC_MIN_SCORE = int(os.environ.get("SC_MIN_SCORE", "80"))
SC_COOLDOWN_MIN = int(os.environ.get("SC_COOLDOWN_MIN", "45"))
SC_COINS = [c.strip() for c in os.environ.get("SC_COINS", "").split(",") if c.strip()]  # empty = all

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

# ---------- breakout scanner (momentum moves the pullback grader misses) ----------
def breakout(d, h4):
    last = h4.iloc[-1]
    prior = h4.iloc[-BO_LOOKBACK-1:-1]
    vol_ok = last.v > BO_VOL_MULT * prior.v.mean()
    r = rsi(h4.c).iloc[-1]
    e50d = ema(d.c, 50).iloc[-1]
    if last.c > prior.h.max() and vol_ok and last.c > e50d and 55 <= r <= 75:
        return "long", prior.h.max(), r, last.v / prior.v.mean()
    if last.c < prior.l.min() and vol_ok and last.c < e50d and 25 <= r <= 45:
        return "short", prior.l.min(), r, last.v / prior.v.mean()
    return None

# ---------- Viprasol Sniper Confluence port (4H) ----------
def vwap_daily(df):
    day = pd.to_datetime(df.t, unit="s", utc=True).dt.date
    tp = (df.h + df.l + df.c) / 3
    return (tp * df.v).groupby(day).cumsum() / df.v.groupby(day).cumsum()

def adx_di(df, n=14):
    up, dn = df.h.diff(), -df.l.diff()
    plus = ((up > dn) & (up > 0)) * up
    minus = ((dn > up) & (dn > 0)) * dn
    tr = atr(df, n)
    pdi = 100 * plus.ewm(alpha=1/n, adjust=False).mean() / tr
    mdi = 100 * minus.ewm(alpha=1/n, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi)
    return dx.ewm(alpha=1/n, adjust=False).mean(), pdi, mdi

def sniper(h4, m5):
    fe, se = ema(h4.c, SN_FAST), ema(h4.c, SN_SLOW)
    if fe.iloc[-2] <= se.iloc[-2] and fe.iloc[-1] > se.iloc[-1]:
        L = True
    elif fe.iloc[-2] >= se.iloc[-2] and fe.iloc[-1] < se.iloc[-1]:
        L = False
    else:
        return None
    last = h4.iloc[-1]
    macd = ema(h4.c, 12) - ema(h4.c, 26)
    sig = ema(macd, 9)
    adx, pdi, mdi = adx_di(h4)
    vw = vwap_daily(h4).iloc[-1]
    r, r5 = rsi(h4.c).iloc[-1], rsi(m5.c).iloc[-1]
    volsma = h4.v.rolling(SN_VOL_LEN).mean().iloc[-1]
    f = {
        "VWAP": last.c > vw if L else last.c < vw,
        "RSI": r > 50 if L else r < 50,
        "MACD": macd.iloc[-1] > sig.iloc[-1] if L else macd.iloc[-1] < sig.iloc[-1],
        "EMA": fe.iloc[-1] > se.iloc[-1] if L else fe.iloc[-1] < se.iloc[-1],
        "ADX": adx.iloc[-1] > 25 and (pdi.iloc[-1] > mdi.iloc[-1] if L else mdi.iloc[-1] > pdi.iloc[-1]),
        "Volume": last.v > volsma and (last.c > last.o if L else last.c < last.o),
        "5m RSI": r5 > 50 if L else r5 < 50,
    }
    score = sum(f.values())
    risk = SN_ATR_MULT * atr(h4, SN_ATR_LEN).iloc[-1]
    entry = last.c
    stop = entry - risk if L else entry + risk
    tps = [entry + k * risk if L else entry - k * risk for k in (1, 2, 3)]
    return {"side": "long" if L else "short", "score": score, "factors": f,
            "entry": entry, "stop": stop, "tps": tps, "bar": int(last.t)}

# ---------- scalp scanner (5m entries, 15m trend) ----------
def scalp(m5, m15):
    """Breakout / trend pullback / momentum burst on 5m, scored 0-100."""
    if len(m5) < 80 or len(m15) < 60:
        return None
    e20_15 = ema(m15.c, 20)
    e50_15 = ema(m15.c, 50).iloc[-1]
    c15 = m15.c.iloc[-1]
    slope = (e20_15.iloc[-1] / e20_15.iloc[-4] - 1) * 100
    tdir = 1 if c15 > e20_15.iloc[-1] > e50_15 else -1 if c15 < e20_15.iloc[-1] < e50_15 else 0

    last, prev = m5.iloc[-1], m5.iloc[-2]
    a = atr(m5).iloc[-1]
    vavg = m5.v.iloc[-21:-1].mean()
    vr = last.v / vavg if vavg > 0 else 0.0
    r = rsi(m5.c).iloc[-1]
    e9, e21 = ema(m5.c, 9), ema(m5.c, 21)
    rng = (last.h - last.l) or 1e-12
    body = abs(last.c - last.o) / rng
    pos = (last.c - last.l) / rng
    win = m5.iloc[-SC_LOOK-1:-1]
    hi, lo = win.h.max(), win.l.min()
    burst_v = m5.v.iloc[-12:].mean()
    base_v = m5.v.iloc[-72:-12].mean()
    br = burst_v / base_v if base_v > 0 else 0.0
    move = last.c - m5.c.iloc[-13]

    out = []
    def push(name, d, score, stop, note):
        risk = abs(last.c - stop)
        if risk <= 0:
            return
        out.append({"setup": name, "side": "long" if d == 1 else "short",
                    "score": int(round(max(0, min(100, score)))),
                    "entry": last.c, "stop": stop, "target": last.c + 2 * risk * d,
                    "rsi": r, "volx": vr, "note": note, "bar": int(last.t)})

    # 1. range breakout / breakdown
    for d in (1, -1):
        level = hi if d == 1 else lo
        broke = last.c > level if d == 1 else last.c < level
        if broke and vr >= SC_VOL_MULT and body >= 0.5:
            s = 50 + min(20, (vr - SC_VOL_MULT) * 8 + 8)
            s += 15 if tdir == d else (-15 if tdir == -d else 0)
            s += 10 if (pos if d == 1 else 1 - pos) >= 0.75 else 0
            s += -10 if (r > 80 if d == 1 else r < 20) else 5
            stop = max(last.l, level - 0.5 * a) if d == 1 else min(last.h, level + 0.5 * a)
            push("breakout" if d == 1 else "breakdown", d, s, stop,
                 f"{SC_LOOK}-bar level {fmt(level)} on {vr:.1f}x vol")

    # 2. trend pullback to the 5m EMA21
    if tdir != 0:
        d = tdir
        if d == 1:
            ok = (e9.iloc[-1] > e21.iloc[-1]
                  and (last.l <= e21.iloc[-1] * 1.001 or prev.l <= e21.iloc[-2] * 1.001)
                  and last.c > e9.iloc[-1] and last.c > last.o
                  and min(last.l, prev.l) > e21.iloc[-1] - 0.75 * a)
            stop = min(last.l, prev.l) - 0.1 * a
            rsi_ok = 40 <= r <= 65
        else:
            ok = (e9.iloc[-1] < e21.iloc[-1]
                  and (last.h >= e21.iloc[-1] * 0.999 or prev.h >= e21.iloc[-2] * 0.999)
                  and last.c < e9.iloc[-1] and last.c < last.o
                  and max(last.h, prev.h) < e21.iloc[-1] + 0.75 * a)
            stop = max(last.h, prev.h) + 0.1 * a
            rsi_ok = 35 <= r <= 60
        if ok:
            s = 55 + (10 if slope * d >= 0.15 else 0) + (10 if vr >= 1.3 else 0) + (10 if rsi_ok else 0)
            push("pullback", d, s, stop, f"15m trend {'up' if d == 1 else 'down'}, 5m EMA21 reclaimed")

    # 3. momentum burst — the move-already-running catcher
    if abs(move) >= SC_BURST_ATR * a and br >= SC_BURST_VOL:
        d = 1 if move > 0 else -1
        s = 60 + min(25, (br - SC_BURST_VOL) * 10) + (10 if tdir == d else 0)
        push("burst", d, s, last.c - d * 1.5 * a,
             f"{move / m5.c.iloc[-13] * 100:+.1f}% in 1h on {br:.1f}x vol — wait for the first pullback")

    return max(out, key=lambda x: x["score"]) if out else None

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

def stamp(now):
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))

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
            if sn:
                if sn["score"] < SN_MIN:
                    when = time.strftime('%b %d %H:%M', time.gmtime(sub.t.iloc[-1]))
                    print(f"{coin} {when} UTC  {sn['side'].upper():5} {sn['score']}/7  (below {SN_MIN}, no alert)")
                    continue
                found += 1
                when = time.strftime('%b %d %H:%M', time.gmtime(sub.t.iloc[-1]))
                note = "" if len(m) > 30 else " (5m RSI est.)"
                print(f"{coin} {when} UTC  {sn['side'].upper():5} {sn['score']}/7  "
                      f"entry {fmt(sn['entry'])}  TP1 {fmt(sn['tps'][0])}{note}")
        if not found:
            print(f"{coin}: no signals")

def scalp_backtest(bars=300):
    """List scalp signals over the last `bars` closed 5m candles (no alerts sent)."""
    coins = SC_COINS or list(WATCHLIST)
    for coin in coins:
        pair = WATCHLIST.get(coin)
        if not pair:
            continue
        try:
            m5, m15 = candles(pair, 5), candles(pair, 15)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}"); continue
        found = 0
        for i in range(max(80, len(m5) - bars), len(m5)):
            sub = m5.iloc[:i + 1].reset_index(drop=True)
            close_t = sub.t.iloc[-1] + 300
            ctx = m15[m15.t + 900 <= close_t].reset_index(drop=True)
            if len(ctx) < 60:
                continue
            sc = scalp(sub, ctx)
            if sc and sc["score"] >= SC_MIN_SCORE:
                found += 1
                when = time.strftime('%b %d %H:%M', time.gmtime(sub.t.iloc[-1]))
                print(f"{coin} {when} UTC  {sc['side'].upper():5} {sc['setup']:9} "
                      f"{sc['score']}/100  entry {fmt(sc['entry'])}  stop {fmt(sc['stop'])}")
        if not found:
            print(f"{coin}: no scalp signals")

# ---------- one pass ----------
def run_once(scalp_only=False):
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now, changed, log = time.time(), False, []
    sc_coins = SC_COINS or list(WATCHLIST)

    for coin, pair in WATCHLIST.items():
        if scalp_only and coin not in sc_coins:
            continue

        if not scalp_only:
            try:
                d, h4, h1 = candles(pair, 1440), candles(pair, 240), candles(pair, 60)
                m5 = candles(pair, 5)
                time.sleep(1)   # stay under Kraken's public rate limit
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
                log.append(f"{stamp(now)},{coin},{best['side']},{best['met']},{best['entry']}")
                sent[str(tier)] = now
            if tier != prev["tier"] or sent != prev.get("sent", {}):
                state[coin] = {"tier": tier, "sent": sent}; changed = True

            bo = breakout(d, h4)
            if bo:
                side, lvl, r, vx = bo
                key = f"{coin}_bo"
                last_bo = state.get(key, 0)
                if now - last_bo > BO_COOLDOWN_HRS * 3600:
                    send(f"⚡ BREAKOUT: {coin} {side.upper()}\n"
                         f"4H closed {fmt(h4.c.iloc[-1])} through {fmt(lvl)} ({BO_LOOKBACK}-bar range)\n"
                         f"Volume {vx:.1f}x avg | RSI 4H {r:.0f}", urgent=True)
                    log.append(f"{stamp(now)},{coin},breakout-{side},-,{h4.c.iloc[-1]}")
                    state[key] = now; changed = True
                print(f"{coin}: breakout {side}")

            sn = sniper(h4, m5)
            if sn:
                miss = [k for k, v in sn["factors"].items() if not v]
                print(f"{coin}: sniper {sn['side']} cross, score {sn['score']}/7"
                      + (f" (missing: {', '.join(miss)})" if miss else ""))
                key = f"{coin}_sn"
                side_key = f"{coin}_side"
                # Dedupe by bar only. The old side lock blocked every new long cross until a
                # qualifying SHORT alert fired (and vice versa), which in a trend never happens.
                if sn["score"] >= SN_MIN and state.get(key) != sn["bar"]:
                    missing = [k for k, v in sn["factors"].items() if not v]
                    tp = " / ".join(fmt(x) for x in sn["tps"])
                    send(f"🎯 SNIPER {sn['side'].upper()}: {coin} {sn['score']}/7 (4H)\n"
                         f"Entry {fmt(sn['entry'])} | SL {fmt(sn['stop'])}\n"
                         f"TP1-3 {tp}"
                         + (f"\nMissing: {', '.join(missing)}" if missing else ""), urgent=True)
                    log.append(f"{stamp(now)},{coin},sniper-{sn['side']},{sn['score']},{sn['entry']}")
                    state[key] = sn["bar"]; state[side_key] = sn["side"]; changed = True

        # ----- scalp scan -----
        if coin in sc_coins:
            try:
                m5s, m15 = candles(pair, 5), candles(pair, 15)
                time.sleep(1)
                sc = scalp(m5s, m15)
            except Exception as e:
                print(f"{coin}: scalp skip: {e}"); sc = None
            if sc:
                print(f"{coin}: scalp {sc['setup']} {sc['side']} {sc['score']}/100")
                key = f"{coin}_sc"
                prev_sc = state.get(key, {})
                if not isinstance(prev_sc, dict):
                    prev_sc = {}
                if (sc["score"] >= SC_MIN_SCORE and prev_sc.get("bar") != sc["bar"]
                        and now - prev_sc.get("sent", 0) > SC_COOLDOWN_MIN * 60):
                    send(f"⚡ SCALP {sc['side'].upper()}: {coin} {sc['setup']} {sc['score']}/100 (5m)\n"
                         f"Entry {fmt(sc['entry'])} | Stop {fmt(sc['stop'])} | 2R {fmt(sc['target'])}\n"
                         f"RSI {sc['rsi']:.0f} | Vol {sc['volx']:.1f}x\n{sc['note']}",
                         urgent=(sc["score"] >= 90))
                    log.append(f"{stamp(now)},{coin},scalp-{sc['setup']}-{sc['side']},{sc['score']},{sc['entry']}")
                    state[key] = {"bar": sc["bar"], "sent": now}; changed = True

    if changed:
        STATE_FILE.write_text(json.dumps(state, indent=1))
    if log:
        new = not LOG_FILE.exists()
        with LOG_FILE.open("a") as f:
            if new: f.write("utc,coin,side,met,price\n")
            f.write("\n".join(log) + "\n")

def main():
    if "--test" in sys.argv:
        send("✅ Grader alerts are connected."); return
    if "--backtest" in sys.argv:
        backtest(); return
    if "--scalp-backtest" in sys.argv:
        scalp_backtest(); return

    loop_min = int(os.environ.get("LOOP_MINUTES", "0"))
    if loop_min <= 0:
        run_once(scalp_only="--scalp-only" in sys.argv)
        return

    # loop mode: full pass first, then scalp-only passes every minute
    end = time.time() + loop_min * 60
    run_once()
    while time.time() + 75 < end:
        time.sleep(60)
        try:
            run_once(scalp_only=True)
        except Exception as e:
            print(f"pass failed: {e}")

if __name__ == "__main__":
    main()
