"""
Swing Setup Grader - Robinhood stocks (v4: replaces the crypto perps grader).

Scans Robinhood's "100 Most Popular" stocks once a day after the close and pushes two kinds
of long swing setups to your phone through ntfy. Signals use the finished daily bar; the
plan is always "buy at tomorrow's open".

PULLBACK (short-term dip in an uptrend)
  - Stock above its 200-day average, and 50-day above 200-day.
  - 2-day RSI at or below PB_RSI2_MAX (a sharp 1-3 day dip).
  - Stop PB_STOP_ATR x ATR(14) below the fill. Exit at the next open after a close above
    the 5-day average, or after PB_MAX_DAYS sessions.

BREAKOUT (leader breaking out of a tight base)
  - Close > 50-day > 150-day > 200-day, the 200-day rising, within 25% of the 52-week high,
    and beating SPY over the last 6 months.
  - The prior BASE_LEN days formed a base no deeper than BASE_MAX_DEPTH.
  - Today closed above the base high for the first time, on BO_VOL_MULT x average volume,
    in the upper half of the day's range.
  - Skip if tomorrow opens more than BO_MAX_GAP above the base high (chasing).
  - Stop at the base low, capped at BO_MAX_LOSS below the fill and at least 1 ATR away.
    Half off at BO_TP1_R, stop to breakeven, runner trails TRAIL_ATR x ATR behind the high.

Both need the market regime on: SPY above its 200-day average. When SPY drops below it, no new
entries are sent (one push when the regime flips). Every signal of both setups is tracked in
swing_outcomes.csv, but only PUSH_SETUPS (default: breakout) go to the phone: the top
MAX_PUSH_PER_SETUP a day, with a share size (set RISK_USD), an options idea (about 0.60-delta
call, debit spread when implied vol is rich vs realized) and an earnings warning. Pushed trades
get follow-ups for the fill, TP1, stop raises, sell signals and closes.

PAPER TRADING (Alpaca): with APCA_API_KEY_ID / APCA_API_SECRET_KEY set, every PAPER_SETUPS signal
also goes to an Alpaca PAPER account (live URLs are refused). The evening of a breakout signal it
queues a day limit buy at the max-gap price (an open above it never fills = the chase rule); for a
pullback it queues a market buy for the open. Both carry an attached stop, sized to lose
PAPER_RISK_PCT (pullbacks: PAPER_PB_RISK_PCT) of equity at the stop and capped by buying power.
Each evening after that it places the GTC stop (and for breakouts the TP1 half-sell) from the
actual fill, raises the stop along the 3-ATR trail, queues a market sell when the plan exits, and
logs closed trades to paper_swing_trades.csv and equity to paper_swing_equity.csv. Breakouts and
pullbacks have separate open-position caps (PAPER_MAX_OPEN / PAPER_PB_MAX_OPEN). One summary push
per evening.

Backtest: `python grader.py --backtest` replays BT_YEARS of daily history for the current list
with both setups, reports each by year and by first half vs second half, compares with and
without the regime filter, and checks returns against each stock's own drift. Results are
committed as swing_backtest.md and swing_bt_trades.csv.
Known limits: today's popular list didn't exist years ago (survivorship bias, so results run
optimistic), and old earnings dates aren't available, so the backtest can't skip earnings.
"""
import json, math, os, sys
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

# ---------------- settings ----------------
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")
FORCE_RUN = os.environ.get("FORCE_RUN") == "1"
RISK_USD = float(os.environ.get("RISK_USD", "0"))        # $ lost at a full stop; >0 shows share size

MIN_PRICE = 10
MIN_DOLLAR_VOL = 50e6          # 20-day average dollar volume
REGIME_SMA = 200               # SPY must close above this average for new entries

# pullback
PB_RSI2_MAX = float(os.environ.get("PB_RSI2_MAX", "10"))
PB_STOP_ATR = float(os.environ.get("PB_STOP_ATR", "2.5"))
PB_MAX_DAYS = int(os.environ.get("PB_MAX_DAYS", "10"))

# breakout
BASE_LEN = int(os.environ.get("BASE_LEN", "20"))
BASE_MAX_DEPTH = float(os.environ.get("BASE_MAX_DEPTH", "0.12"))
BO_VOL_MULT = float(os.environ.get("BO_VOL_MULT", "1.5"))
BO_NEAR_HIGH = 0.75            # close at least 75% of the 52-week high
BO_MAX_GAP = float(os.environ.get("BO_MAX_GAP", "0.05"))
BO_MAX_LOSS = float(os.environ.get("BO_MAX_LOSS", "0.08"))
BO_MIN_STOP_ATR = 1.0
BO_TP1_R = float(os.environ.get("BO_TP1_R", "2.0"))
TRAIL_ATR = float(os.environ.get("TRAIL_ATR", "3.0"))
BO_MAX_DAYS = int(os.environ.get("BO_MAX_DAYS", "60"))

SLIP_BPS = float(os.environ.get("SLIP_BPS", "5"))         # per fill; Robinhood has no stock commission
MAX_PUSH_PER_SETUP = int(os.environ.get("MAX_PUSH_PER_SETUP", "3"))
TRAIL_PUSH_ATR = 1.0           # push a stop raise once the trail moves this many ATR

# options idea
OPT_DTE = {"pullback": (21, 45, 30), "breakout": (30, 75, 45)}   # min, max, target
TARGET_DELTA = 0.60
MIN_OI = 500
MAX_SPREAD = 0.10
IV_RICH = 1.3                  # ATM IV / 20-day realized vol above this -> debit spread
RISK_FREE = 0.04
EARN_WARN_DAYS = {"pullback": 14, "breakout": 30}

# which setups push to the phone (the other is tracked silently), and paper trading
PUSH_SETUPS = tuple(x for x in os.environ.get("PUSH_SETUPS", "breakout").split(",") if x)
PAPER_SETUPS = tuple(x for x in os.environ.get("PAPER_SETUPS", "breakout,pullback").split(",") if x)
ALPACA_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")
ALPACA_URL = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets").rstrip("/")
PAPER = bool(ALPACA_KEY and ALPACA_SECRET) and "paper-api" in ALPACA_URL   # never a live account
PAPER_RISK_PCT = float(os.environ.get("PAPER_RISK_PCT", "0.5"))      # % of equity lost at a full stop
PAPER_MAX_POS_PCT = float(os.environ.get("PAPER_MAX_POS_PCT", "20")) # cap on one position's size
PAPER_MAX_OPEN = int(os.environ.get("PAPER_MAX_OPEN", "15"))           # breakouts
PAPER_PB_RISK_PCT = float(os.environ.get("PAPER_PB_RISK_PCT", str(PAPER_RISK_PCT)))
PAPER_PB_MAX_OPEN = int(os.environ.get("PAPER_PB_MAX_OPEN", "10"))

BT_YEARS = int(os.environ.get("BT_YEARS", "10"))
UNIVERSE_DAYS = 7              # reuse a Robinhood universe this many days
RUN_AFTER_ET = (16, 20)        # daily bar is final by then

SETUPS = ("pullback", "breakout")
ET = ZoneInfo("America/New_York")
STATE_FILE = Path("swing_state.json")
ALERTS_FILE = Path("swing_alerts.csv")
OUT_FILE = Path("swing_outcomes.csv")
SUMMARY_FILE = Path("swing_summary.md")
BT_FILE = Path("swing_backtest.md")
BT_TRADES = Path("swing_bt_trades.csv")
PAPER_FILE = Path("paper_swing_trades.csv")
EQUITY_FILE = Path("paper_swing_equity.csv")
UA = {"User-Agent": "Mozilla/5.0"}

FALLBACK = """TSLA NVDA AAPL AMZN AMD PLTR MSFT META GOOGL F SOFI NIO RIVN LCID INTC DIS
NFLX BAC T AAL CCL PFE KO SBUX GE GME AMC HOOD COIN MARA RIOT CLSK IREN MSTR SNAP UBER
ABNB PYPL XYZ SHOP BABA DKNG NKE WMT COST JPM V MA XOM CVX BA DAL UAL NCLH RCL PLUG AVGO
SMCI ARM MU TSM QCOM ORCL CRM ADBE IBM CSCO RBLX AFRM UPST SNOW NET CRWD PANW ZM ROKU
PINS SPOT LYFT CHWY WBD CMG MCD PEP VZ TGT HD LOW LLY NVO MRNA JNJ ABBV UNH CVS OXY
SOUN RKLB ASTS IONQ HIMS""".split()


# ---------------- state ----------------
def load_state():
    if STATE_FILE.exists():
        s = json.loads(STATE_FILE.read_text())
    else:
        s = {}
    s.setdefault("universe", {})
    s.setdefault("trades", [])
    return s


def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=1, default=str))


# ---------------- universe (same source as the options grader) ----------------
def robinhood_top100():
    try:
        r = requests.get("https://api.robinhood.com/midlands/tags/tag/100-most-popular/",
                         headers=UA, timeout=15)
        r.raise_for_status()
        urls = r.json().get("instruments", [])
        with requests.Session() as sess:
            def lookup(url):
                try:
                    inst = sess.get(url, headers=UA, timeout=10).json()
                    if inst.get("tradeable") and inst.get("symbol"):
                        return inst["symbol"].replace(".", "-")
                except Exception:
                    pass
                return None
            with ThreadPoolExecutor(max_workers=16) as ex:
                syms = [x for x in ex.map(lookup, urls) if x]
        if len(syms) >= 50:
            return syms, "robinhood"
    except Exception as e:
        print("Robinhood list failed:", e)
    return FALLBACK, "fallback"


def get_universe(state, today):
    u = state.get("universe", {})
    if u.get("symbols") and u.get("date"):
        age = (today - dt.date.fromisoformat(u["date"])).days
        # a fallback list is only reused the same day, so Robinhood is retried tomorrow
        max_age = UNIVERSE_DAYS if u.get("source") == "robinhood" else 1
        if 0 <= age < max_age:
            return u["symbols"], u["source"]
    syms, src = robinhood_top100()
    state["universe"] = {"date": str(today), "source": src, "symbols": syms}
    print(f"Universe: {len(syms)} symbols from {src}")
    return syms, src


# ---------------- data + indicators ----------------
def load_data(symbols, period):
    tickers = sorted(set(symbols) | {"SPY"})
    raw = yf.download(tickers, period=period, interval="1d", group_by="ticker",
                      auto_adjust=True, threads=True, progress=False)
    out = {}
    for s in tickers:
        try:
            df = raw[s].dropna(subset=["Close"]).copy()
        except KeyError:
            continue
        if len(df) < 260:
            continue
        idx = pd.DatetimeIndex(df.index)
        df.index = idx.tz_localize(None) if idx.tz is not None else idx
        out[s] = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
    return out


def wilder(s, n):
    return s.ewm(alpha=1 / n, adjust=False).mean()


def rsi(c, n):
    d = c.diff()
    up, dn = wilder(d.clip(lower=0), n), wilder(-d.clip(upper=0), n)
    return (100 - 100 / (1 + up / dn.replace(0, np.nan))).fillna(100.0)


def atr(df, n=14):
    pc = df.Close.shift()
    tr = pd.concat([df.High - df.Low, (df.High - pc).abs(), (df.Low - pc).abs()], axis=1).max(axis=1)
    return wilder(tr, n)


def hv20(close):
    return float(np.log(close / close.shift()).tail(20).std() * math.sqrt(252))


def add_ind(df, spy):
    """Indicators and both signal columns. Every column uses only that day and earlier."""
    c = df.Close
    df["sma5"] = c.rolling(5).mean()
    df["sma50"] = c.rolling(50).mean()
    df["sma150"] = c.rolling(150).mean()
    df["sma200"] = c.rolling(200).mean()
    df["sma200_up"] = df.sma200 > df.sma200.shift(20)
    df["atr"] = atr(df)
    df["rsi2"] = rsi(c, 2)
    df["hi252"] = df.High.rolling(252, min_periods=200).max()
    df["vol50"] = df.Volume.rolling(50).mean().shift(1)
    df["dv20"] = (c * df.Volume).rolling(20).mean()
    df["base_hi"] = df.High.rolling(BASE_LEN).max().shift(1)
    df["base_low"] = df.Low.rolling(BASE_LEN).min().shift(1)
    rng = df.High - df.Low
    df["pos"] = ((c - df.Low) / rng).where(rng > 0, 0.5)
    spy_c = spy.Close.reindex(df.index).ffill()
    spy_ma = spy.Close.rolling(REGIME_SMA).mean().reindex(df.index).ffill()
    df["regime"] = spy_c > spy_ma
    df["rs"] = c / c.shift(126) - spy_c / spy_c.shift(126)

    liquid = (c >= MIN_PRICE) & (df.dv20 >= MIN_DOLLAR_VOL)
    df["sig_pullback"] = liquid & (c > df.sma200) & (df.sma50 > df.sma200) & (df.rsi2 <= PB_RSI2_MAX)

    depth = (df.base_hi - df.base_low) / df.base_hi
    df["depth"] = depth
    trend = (c > df.sma50) & (df.sma50 > df.sma150) & (df.sma150 > df.sma200) & df.sma200_up
    first = c.shift(1) <= df.base_hi.shift(1)
    df["vx"] = df.Volume / df.vol50
    df["sig_breakout"] = (liquid & trend & (c >= BO_NEAR_HIGH * df.hi252) & (df.rs > 0)
                          & (depth <= BASE_MAX_DEPTH) & (c > df.base_hi) & first
                          & (df.vx >= BO_VOL_MULT) & (df.pos >= 0.5))
    for k in ("sig_pullback", "sig_breakout", "regime", "sma200_up"):
        df[k] = df[k].fillna(False).astype(bool)
    return df


# ---------------- trade rules ----------------
def initial_stop(setup, entry, atr_, base_low):
    if setup == "pullback":
        return entry - PB_STOP_ATR * atr_
    stop = max(base_low, entry * (1 - BO_MAX_LOSS))
    if entry - stop < BO_MIN_STOP_ATR * atr_:
        stop = entry - BO_MIN_STOP_ATR * atr_
    return stop


def simulate(setup, entry_open, stop, atr_, bars, slip_bps=SLIP_BPS, x=None):
    """Walk daily bars starting with the entry day (filled at its open).
    Stops are checked before targets in each bar; a gap below the stop fills at the open.
    Exit signals found at a close fill at the next open. Returns a result dict; done=False
    while the trade is still open (with the current stop and any exit due tomorrow).
    x: optional exit-rule overrides used only by the backtest's exit-variant table
    (tp1_r: 0 = no half-sell; trail: ATR multiple; lock_at/lock_to: once the high reaches
    lock_at R, the stop rises to entry + lock_to R from the next bar; pb_mode: "sma5" or
    "trail"; max_days). Live trading always uses the defaults."""
    x = x or {}
    tp1_r = x.get("tp1_r", BO_TP1_R)
    trail = x.get("trail", TRAIL_ATR)
    lock_at, lock_to = x.get("lock_at"), x.get("lock_to", 0.0)
    pb_mode = x.get("pb_mode", "sma5")
    max_days = x.get("max_days", BO_MAX_DAYS if setup == "breakout" else PB_MAX_DAYS)
    slip = slip_bps / 1e4
    entry = entry_open * (1 + slip)
    risk = entry - stop
    O, H, L, C = (bars[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    S5 = bars["sma5"].to_numpy(float) if "sma5" in bars else np.full(len(O), np.nan)
    dates = bars.index
    base = {"entry": entry, "risk": risk, "stop0": stop}
    if risk <= 0:
        return {**base, "done": True, "r": 0.0, "reason": "invalid", "days": 0, "exit_px": entry,
                "exit_date": dates[0] if len(dates) else None, "mfe": 0.0, "mae": 0.0,
                "half": False, "ret_pct": 0.0}
    tp1 = entry + tp1_r * risk if tp1_r else float("inf")
    q, real, half, best, mfe, mae, pend = 1.0, 0.0, False, entry, 0.0, 0.0, None

    def done(k, px, reason):
        r = real + q * (px - entry) / risk
        return {**base, "done": True, "r": r, "reason": reason, "days": k + 1, "exit_px": px,
                "exit_date": dates[k], "mfe": mfe, "mae": mae, "half": half,
                "ret_pct": r * risk / entry * 100}

    for k in range(len(O)):
        o, h, l, c = O[k], H[k], L[k], C[k]
        if pend:
            return done(k, o * (1 - slip), pend)
        mfe = max(mfe, (h - entry) / risk)
        mae = max(mae, (entry - l) / risk)
        if k > 0 and o <= stop:
            return done(k, o * (1 - slip), "gapped below stop")
        if l <= stop:
            return done(k, stop * (1 - slip), "trailing stop" if stop > base["stop0"] + 1e-9 else "stop")
        if setup == "breakout":
            if not half and h >= tp1:
                px = max(tp1, o) if k > 0 else tp1
                real += 0.5 * (px - entry) / risk
                q, half = 0.5, True
                stop = max(stop, entry)
                if l <= entry and k > 0:
                    return done(k, entry * (1 - slip), "TP1 then back to entry")
            best = max(best, h)
            stop = max(stop, best - trail * atr_)
            if lock_at is not None and mfe >= lock_at:
                stop = max(stop, entry + lock_to * risk)
            if k + 1 >= max_days:
                pend = "max hold"
        else:
            if pb_mode == "trail":
                best = max(best, h)
                stop = max(stop, best - trail * atr_)
                if lock_at is not None and mfe >= lock_at:
                    stop = max(stop, entry + lock_to * risk)
                if k + 1 >= max_days:
                    pend = "time stop"
            elif np.isfinite(S5[k]) and c > S5[k]:
                pend = "closed above 5-day average"
            elif k + 1 >= max_days:
                pend = "time stop"
    return {**base, "done": False, "r": real, "half": half, "stop": stop, "pending_exit": pend,
            "mfe": mfe, "mae": mae, "days": len(O), "tp1": tp1}


# ---------------- backtest ----------------
def stats(r, days=None):
    r = pd.Series(r, dtype=float)
    if r.empty:
        return None
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    return {"n": len(r), "win": 100 * (r > 0).mean(), "avg": r.mean(), "tot": r.sum(),
            "pf": wins / losses if losses > 0 else float("inf"), "dd": float((eq.cummax() - eq).max()),
            "days": float(pd.Series(days).mean()) if days is not None and len(days) else float("nan")}


def cell(st):
    if not st:
        return "-"
    pf = "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return f"{st['n']} / {st['win']:.0f}% / {st['avg']:+.2f} / {st['tot']:+.1f} / PF {pf}"


def max_concurrent(t):
    ev = [(d, 1) for d in t.entry_date] + [(d, -1) for d in t.exit_date]
    cur = best = 0
    for _, x in sorted(ev, key=lambda e: (e[0], e[1])):
        cur += x
        best = max(best, cur)
    return best


def backtest():
    syms, src = robinhood_top100()
    print(f"Backtest universe: {len(syms)} symbols from {src}, {BT_YEARS} years")
    data = load_data(syms, f"{BT_YEARS}y")
    spy = data.get("SPY")
    if spy is None:
        raise SystemExit("SPY data missing")
    rows, gaps, open_end, prepped = [], 0, 0, {}
    for sym in syms:
        df = data.get(sym)
        if df is None:
            continue
        df = add_ind(df.copy(), spy)
        drift = float(df.Close.pct_change().mean())
        prepped[sym] = (df, drift)
        O = df.Open.to_numpy(float)
        A = df.atr.to_numpy(float)
        BL = df.base_low.to_numpy(float)
        PV = df.base_hi.to_numpy(float)
        REG = df.regime.to_numpy(bool)
        for setup in SETUPS:
            sig = df[f"sig_{setup}"].to_numpy(bool)
            for variant in ("filtered", "unfiltered"):
                busy = -1
                for i in np.flatnonzero(sig):
                    if i <= busy or i + 1 >= len(df):
                        continue
                    if variant == "filtered" and not REG[i]:
                        continue
                    o = O[i + 1]
                    if setup == "breakout" and o > PV[i] * (1 + BO_MAX_GAP):
                        gaps += variant == "filtered"
                        continue
                    stop = initial_stop(setup, o * (1 + SLIP_BPS / 1e4), A[i], BL[i])
                    res = simulate(setup, o, stop, A[i], df.iloc[i + 1:])
                    if not res["done"]:
                        open_end += variant == "filtered"
                        break
                    rows.append({"sym": sym, "setup": setup, "variant": variant,
                                 "regime": bool(REG[i]), "signal_date": df.index[i].date(),
                                 "entry_date": df.index[i + 1].date(), "exit_date": res["exit_date"].date(),
                                 "year": df.index[i + 1].year, "entry": round(res["entry"], 4),
                                 "stop": round(stop, 4), "exit": round(res["exit_px"], 4),
                                 "r": round(res["r"], 3), "ret_pct": round(res["ret_pct"], 3),
                                 "days": res["days"], "reason": res["reason"],
                                 "mfe_r": round(res["mfe"], 2), "mae_r": round(res["mae"], 2),
                                 "excess_pct": round(res["ret_pct"] - drift * res["days"] * 100, 3)})
                    busy = i + res["days"]
        print(f"{sym}: done")
    t = pd.DataFrame(rows)
    t.to_csv(BT_TRADES, index=False)
    text = bt_report(t, len(data) - 1, src, gaps, open_end)
    text += exit_variants_report(prepped)
    BT_FILE.write_text(text)
    print(text)
    step_summary(text)


# Exit rules compared side by side (regime filter on, same entries and initial stops).
# The first row of each setup is the live rule.
EXIT_VARIANTS = {
    "breakout": [
        ("LIVE: half at 2R, trail 3 ATR", {}),
        ("half at 3R, trail 3 ATR", {"tp1_r": 3.0}),
        ("half at 4R, trail 3 ATR", {"tp1_r": 4.0}),
        ("no half-sell, trail 3 ATR", {"tp1_r": 0}),
        ("no half-sell, trail 4 ATR", {"tp1_r": 0, "trail": 4.0}),
        ("half at 2R, trail 2 ATR", {"trail": 2.0}),
        ("half at 2R, trail 4 ATR", {"trail": 4.0}),
        ("half at 2R, trail 3, lock +0.5R at +1R", {"lock_at": 1.0, "lock_to": 0.5}),
        ("half at 3R, trail 3, lock +0.5R at +1R", {"tp1_r": 3.0, "lock_at": 1.0, "lock_to": 0.5}),
        ("no half-sell, trail 3, lock +0.5R at +1R", {"tp1_r": 0, "lock_at": 1.0, "lock_to": 0.5}),
        ("no half-sell, trail 3, breakeven at +1R", {"tp1_r": 0, "lock_at": 1.0, "lock_to": 0.0}),
        ("no half-sell, trail 4, lock +1R at +2R", {"tp1_r": 0, "trail": 4.0, "lock_at": 2.0, "lock_to": 1.0}),
    ],
    "pullback": [
        ("LIVE: sell after close above 5-day avg", {}),
        ("let it run: trail 2.5 ATR, max 20 days", {"pb_mode": "trail", "trail": 2.5, "max_days": 20}),
        ("let it run: trail 2.5, lock +0.25R at +0.5R, max 20 days",
         {"pb_mode": "trail", "trail": 2.5, "lock_at": 0.5, "lock_to": 0.25, "max_days": 20}),
    ],
}


def exit_variants_report(prepped):
    out = ["\n## Exit variants (regime filter on)\n",
           "Same signals, entries and starting stops; only the exit changes. Stop raises (trail, lock) "
           "take effect the next day, like the evening stop updates in paper trading. Look for a row that "
           "beats LIVE on total R **and** holds up in both halves, not just the biggest number.\n",
           "| setup | exit rule | result | avg % / trade | vs drift % | avg days | max DD (R) | 1st half | 2nd half |",
           "|---|---|---|---|---|---|---|---|---|"]
    for setup, variants in EXIT_VARIANTS.items():
        for label, x in variants:
            rows = []
            for sym, (df, drift) in prepped.items():
                O = df.Open.to_numpy(float)
                A = df.atr.to_numpy(float)
                BL = df.base_low.to_numpy(float)
                PV = df.base_hi.to_numpy(float)
                REG = df.regime.to_numpy(bool)
                sig = df[f"sig_{setup}"].to_numpy(bool)
                busy = -1
                for i in np.flatnonzero(sig):
                    if i <= busy or i + 1 >= len(df) or not REG[i]:
                        continue
                    o = O[i + 1]
                    if setup == "breakout" and o > PV[i] * (1 + BO_MAX_GAP):
                        continue
                    stop = initial_stop(setup, o * (1 + SLIP_BPS / 1e4), A[i], BL[i])
                    res = simulate(setup, o, stop, A[i], df.iloc[i + 1:], x=x)
                    if not res["done"]:
                        break
                    rows.append({"entry_date": df.index[i + 1].date(), "exit_date": res["exit_date"].date(),
                                 "r": res["r"], "ret_pct": res["ret_pct"], "days": res["days"],
                                 "excess": res["ret_pct"] - drift * res["days"] * 100})
                    busy = i + res["days"]
            v = pd.DataFrame(rows)
            if v.empty:
                out.append(f"| {setup} | {label} | - | | | | | | |"); continue
            v = v.sort_values("exit_date")
            st = stats(v.r, v.days)
            mid = v.entry_date.min() + (v.entry_date.max() - v.entry_date.min()) / 2
            out.append(f"| {setup} | {label} | {cell(st)} | {v.ret_pct.mean():+.2f} | {v.excess.mean():+.2f} | "
                       f"{st['days']:.1f} | {st['dd']:.1f} | {cell(stats(v[v.entry_date <= mid].r))} | "
                       f"{cell(stats(v[v.entry_date > mid].r))} |")
            print(f"exit variant done: {setup} / {label}")
    return "\n".join(out) + "\n"


def bt_report(t, n_syms, src, gaps, open_end):
    out = [f"# Swing backtest: {BT_YEARS} years, {n_syms} stocks ({src} list)\n",
           f"Run {dt.date.today()}. Entries at the next open, {SLIP_BPS:g} bps slippage per fill, "
           f"no commissions. R = profit / initial risk. One position per stock per setup. "
           f"{gaps} breakouts skipped for gapping more than {BO_MAX_GAP:.0%}; "
           f"{open_end} trades still open at the end left out.\n",
           "**Caution:** this list is today's most popular stocks, chosen partly because they went up "
           "(survivorship bias), so treat results as optimistic. The 'vs drift' column subtracts each "
           "stock's own average daily move over the hold, which is the fairer test: positive means the "
           "signal beat just owning that stock.\n",
           "Cells: n / win% / avg R / total R / profit factor.\n"]
    if t.empty:
        return "\n".join(out + ["No trades.\n"])
    f = t[t.variant == "filtered"].sort_values("exit_date")
    u = t[t.variant == "unfiltered"].sort_values("exit_date")
    out += ["## Strategy (regime filter on)\n",
            "| setup | result | avg % / trade | vs drift % | avg days | max DD (R) | max open at once |",
            "|---|---|---|---|---|---|---|"]
    for s in SETUPS:
        x = f[f.setup == s]
        st = stats(x.r, x.days)
        if not st:
            out.append(f"| {s} | - | | | | | |"); continue
        out.append(f"| {s} | {cell(st)} | {x.ret_pct.mean():+.2f} | {x.excess_pct.mean():+.2f} | "
                   f"{st['days']:.1f} | {st['dd']:.1f} | {max_concurrent(x)} |")

    mid = f.entry_date.min() + (f.entry_date.max() - f.entry_date.min()) / 2 if len(f) else None
    out += [f"\n## First half vs second half (split {mid})\n",
            "If a setup only works in one half, it's fragile. Tune rules on the first half only.\n",
            "| setup | first half | second half |", "|---|---|---|"]
    for s in SETUPS:
        x = f[f.setup == s]
        out.append(f"| {s} | {cell(stats(x[x.entry_date <= mid].r))} | {cell(stats(x[x.entry_date > mid].r))} |")

    out += ["\n## Does the regime filter help?\n",
            "| setup | SPY above 200-day | SPY below 200-day (filter skips these) | all signals |",
            "|---|---|---|---|"]
    for s in SETUPS:
        x = u[u.setup == s]
        out.append(f"| {s} | {cell(stats(x[x.regime].r))} | {cell(stats(x[~x.regime].r))} | {cell(stats(x.r))} |")

    out += ["\n## By year (regime filter on)\n", "| year | pullback | breakout |", "|---|---|---|"]
    for y in sorted(f.year.unique()):
        x = f[f.year == y]
        out.append(f"| {y} | {cell(stats(x[x.setup == 'pullback'].r))} | {cell(stats(x[x.setup == 'breakout'].r))} |")

    out += ["\n## Exit reasons (regime filter on)\n", "| setup | reason | n | avg R |", "|---|---|---|---|"]
    for (s, rs), x in f.groupby(["setup", "reason"]):
        out.append(f"| {s} | {rs} | {len(x)} | {x.r.mean():+.2f} |")

    for s in SETUPS:
        x = f[f.setup == s]
        if len(x):
            g = x.groupby("sym").r.sum()
            out.append(f"\n{s}: {int((g > 0).sum())} of {len(g)} stocks net positive. "
                       f"Avg best excursion {x.mfe_r.mean():.2f}R; {100 * (x.mfe_r >= 1).mean():.0f}% reached +1R.")
    out.append("\nPer-trade detail: swing_bt_trades.csv\n")
    return "\n".join(out) + "\n"


# ---------------- options idea + earnings (live pushes only) ----------------
def bs_delta(S, K, T, sigma, r=RISK_FREE):
    if T <= 0 or sigma <= 0:
        return None
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return 0.5 * (1 + math.erf(d1 / math.sqrt(2)))


def option_idea(sym, px, setup, hv, target_px):
    lo, hi, tgt = OPT_DTE[setup]
    try:
        t = yf.Ticker(sym)
        today = dt.datetime.now(ET).date()
        exps = []
        for e in t.options:
            dte = (dt.date.fromisoformat(e) - today).days
            if lo <= dte <= hi:
                exps.append((abs(dte - tgt), e, dte))
        if not exps:
            return f"Options: no expiry {lo}-{hi} days out"
        _, exp, dte = min(exps)
        calls = t.option_chain(exp).calls
        rows = []
        for _, row in calls.iterrows():
            bid, ask = float(row.bid or 0), float(row.ask or 0)
            if bid <= 0 or ask <= 0:
                continue
            iv = float(row.impliedVolatility) if row.impliedVolatility and row.impliedVolatility > 0.05 else hv
            dl = bs_delta(px, float(row.strike), dte / 365, iv)
            if dl is None:
                continue
            mid = (bid + ask) / 2
            rows.append({"k": float(row.strike), "d": dl, "mid": mid, "sp": (ask - bid) / mid,
                         "oi": 0 if pd.isna(row.openInterest) else int(row.openInterest), "iv": iv})
        if not rows:
            return "Options: no usable quotes"
        k = min(rows, key=lambda x: abs(x["d"] - TARGET_DELTA))
        atm = min(rows, key=lambda x: abs(x["k"] - px))
        ratio = atm["iv"] / hv if hv > 0 else 1.0
        expd = dt.date.fromisoformat(exp).strftime("%b %d")
        if ratio <= IV_RICH:
            line = f"Options: {expd} {k['k']:g}C (Δ{k['d']:.2f}, {dte} DTE) mid ${k['mid']:.2f} | IV/HV {ratio:.2f} → long call"
        else:
            above = [x for x in rows if x["k"] > k["k"]]
            short = min(above, key=lambda x: abs(x["k"] - target_px)) if above else None
            leg = f"/{short['k']:g}C" if short else ""
            line = (f"Options: {expd} {k['k']:g}{leg}C debit spread ({dte} DTE) | IV/HV {ratio:.2f} rich, "
                    f"spread cuts the IV cost")
        if k["oi"] < MIN_OI or k["sp"] > MAX_SPREAD:
            line += f"\n⚠ thin contract: OI {k['oi']}, spread {k['sp']:.0%}"
        return line
    except Exception as e:
        return f"Options: lookup failed ({type(e).__name__})"


def earnings_days(sym):
    try:
        cal = yf.Ticker(sym).calendar
        dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
        if dates:
            d = dates[0] if isinstance(dates, list) else dates
            d = d.date() if hasattr(d, "date") else d
            return (d - dt.datetime.now(ET).date()).days
    except Exception:
        pass
    return None


# ---------------- alerts ----------------
def send(title, body, priority="default", tags=""):
    if not NTFY_TOPIC:
        print(f"[no NTFY_TOPIC] {title}\n{body}\n"); return
    try:
        requests.post(f"{NTFY_SERVER}/{NTFY_TOPIC}", data=body.encode("utf-8"),
                      headers={"Title": title.encode("ascii", "ignore").decode() or "Swing grader",
                               "Priority": priority, "Tags": tags}, timeout=15)
    except Exception as e:
        print("ntfy failed:", e)


def money(p):
    return f"${p:,.2f}"


def size_line(entry, stop):
    risk = entry - stop
    if risk <= 0:
        return ""
    if RISK_USD > 0:
        sh = RISK_USD / risk
        return f"Shares: ${RISK_USD:g} risk ÷ {money(risk)} = {sh:.2f} sh (≈{money(sh * entry)})"
    return f"Shares: your $ risk ÷ {money(risk)} per share"


def entry_msg(sym, setup, row):
    c, a = float(row.Close), float(row.atr)
    if setup == "pullback":
        stop = c - PB_STOP_ATR * a
        title = f"PULLBACK BUY {sym}"
        lines = [f"🟢 PULLBACK BUY: {sym} (2-day RSI {row.rsi2:.0f})",
                 f"Closed {money(c)} | uptrend: above 200-day, 50-day above 200-day",
                 "Plan: buy at tomorrow's open",
                 f"Stop ≈ {money(stop)} ({PB_STOP_ATR:g} ATR; exact level pushed after the fill)",
                 f"Exit: sell at the next open after a close above the 5-day avg (now {money(row.sma5)}), "
                 f"or after {PB_MAX_DAYS} sessions",
                 size_line(c, stop)]
        target = c + 1.5 * a
    else:
        stop = initial_stop("breakout", c, a, float(row.base_low))
        risk = c - stop
        title = f"BREAKOUT BUY {sym}"
        lines = [f"🚀 BREAKOUT BUY: {sym}",
                 f"Closed {money(c)} above its {BASE_LEN}-day base {money(row.base_hi)} "
                 f"(base depth {row.depth:.0%}) on {row.vx:.1f}x volume",
                 f"Plan: buy at tomorrow's open if ≤ {money(row.base_hi * (1 + BO_MAX_GAP))}; skip if it gaps higher",
                 f"Stop ≈ {money(stop)} (base low, max {BO_MAX_LOSS:.0%} loss; exact after the fill)",
                 f"TP1 ≈ {money(c + BO_TP1_R * risk)} ({BO_TP1_R:g}R): sell half, stop to entry. "
                 f"Runner trails {TRAIL_ATR:g} ATR ({money(TRAIL_ATR * a)}) below the high",
                 size_line(c, stop)]
        target = c + BO_TP1_R * risk
    return title, lines, target


def log_alert(rows):
    if not rows:
        return
    new = not ALERTS_FILE.exists()
    with ALERTS_FILE.open("a") as f:
        if new:
            f.write("date,sym,setup,event,price\n")
        f.write("\n".join(rows) + "\n")


OUT_COLS = ["signal_date", "entry_date", "exit_date", "sym", "setup", "pushed", "entry", "stop",
            "exit", "r", "ret_pct", "days", "reason", "mfe_r", "mae_r"]


def write_outcomes(rows):
    if not rows:
        return
    new = not OUT_FILE.exists()
    with OUT_FILE.open("a") as f:
        if new:
            f.write(",".join(OUT_COLS) + "\n")
        f.write("\n".join(",".join(str(r[c]) for c in OUT_COLS) for r in rows) + "\n")


def summarize(n_open=0):
    if not OUT_FILE.exists():
        d = pd.DataFrame(columns=OUT_COLS)
    else:
        d = pd.read_csv(OUT_FILE)
    out = [f"# Swing outcomes\n\n{len(d)} closed, {n_open} open or pending. Updated {dt.date.today()}.\n",
           "Wait for 30+ per row before judging. Compare with swing_backtest.md.\n",
           "| setup | pushed | result |", "|---|---|---|"]
    for (s, p), x in d.groupby(["setup", "pushed"]):
        out.append(f"| {s} | {p} | {cell(stats(x.r))} |")
    if PAPER_FILE.exists():
        pp = pd.read_csv(PAPER_FILE)
        pr = pd.to_numeric(pp.r, errors="coerce").dropna()
        pnl = pd.to_numeric(pp.pnl, errors="coerce").sum()
        out += ["\n## Alpaca paper account\n",
                f"{len(pp)} closed: {cell(stats(pr))} | net ${pnl:+,.0f}. "
                "Equity history: paper_swing_equity.csv\n"]
        if "setup" in pp:
            out += ["| setup | result | net $ |", "|---|---|---|"]
            for s, x in pp.groupby("setup"):
                out.append(f"| {s} | {cell(stats(pd.to_numeric(x.r, errors='coerce').dropna()))} | "
                           f"{pd.to_numeric(x.pnl, errors='coerce').sum():+,.0f} |")
    return "\n".join(out) + "\n"


def step_summary(text):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        with open(p, "a") as f:
            f.write(text)


# ---------------- Alpaca paper trading ----------------
def ap(method, path, **kw):
    """Alpaca REST call. Returns parsed JSON, None on 404, raises on other errors."""
    r = requests.request(method, ALPACA_URL + path, timeout=20,
                         headers={"APCA-API-KEY-ID": ALPACA_KEY, "APCA-API-SECRET-KEY": ALPACA_SECRET}, **kw)
    if r.status_code == 404:
        return None
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:200]}")
    return r.json() if r.text.strip() else {}


def ap_sym(sym):
    return sym.replace("-", ".")          # Yahoo BRK-B -> Alpaca BRK.B


def ap_order(sym, qty, side, otype, tif, **extra):
    body = {"symbol": ap_sym(sym), "qty": str(int(qty)), "side": side, "type": otype, "time_in_force": tif}
    body.update({k: (f"{v:.2f}" if isinstance(v, float) else v) for k, v in extra.items()})
    return ap("POST", "/v2/orders", json=body)


def ap_cancel(order_id):
    if not order_id:
        return
    try:
        o = ap("GET", f"/v2/orders/{order_id}")
        if o and o.get("status") in OPEN_STATUSES:
            ap("DELETE", f"/v2/orders/{order_id}")
    except Exception as e:
        print("cancel failed:", e)


OPEN_STATUSES = ("new", "accepted", "pending_new", "accepted_for_bidding", "held", "partially_filled",
                 "pending_replace", "calculated")


def paper_enter(tr, equity, buying_power):
    """Queue tomorrow's entry with an attached stop. Breakout: limit buy at the max-gap price (an
    open above it never fills, which is the chase rule), sized so a fill at the limit risks
    PAPER_RISK_PCT. Pullback: market buy at the open, sized off today's close to risk
    PAPER_PB_RISK_PCT. Both are capped at PAPER_MAX_POS_PCT of equity and the buying power left."""
    if tr["setup"] == "breakout":
        limit = round(tr["pivot"] * (1 + BO_MAX_GAP), 2)
        px, risk_pct = limit, PAPER_RISK_PCT
    else:
        limit, px, risk_pct = None, tr["close"] * 1.02, PAPER_PB_RISK_PCT   # room for a gap up
    stop = round(initial_stop(tr["setup"], tr["close"], tr["atr"], tr["base_low"]), 2)
    risk_ps = px - stop
    if risk_ps <= 0:
        return None
    qty = int(min(equity * risk_pct / 100 / risk_ps, equity * PAPER_MAX_POS_PCT / 100 / px,
                  buying_power / px))
    if qty < 1:
        return None
    kind = {"limit_price": limit} if limit else {}
    o = ap_order(tr["sym"], qty, "buy", "limit" if limit else "market", "day", **kind, order_class="oto",
                 stop_loss={"stop_price": f"{stop:.2f}"},
                 client_order_id=f"sg-{tr['setup'][:2]}-{tr['sym']}-{tr['signal_date']}")
    return {"status": "submitted", "entry_id": o["id"], "qty": qty, "limit": limit, "stop_px": stop,
            "cost": qty * px}


def paper_fills(ids):
    """Sum filled quantity and value over exit orders."""
    q = v = 0.0
    for oid in ids:
        if not oid:
            continue
        o = ap("GET", f"/v2/orders/{oid}")
        if o and float(o.get("filled_qty") or 0) > 0:
            fq = float(o["filled_qty"])
            q += fq
            v += fq * float(o["filled_avg_price"])
    return q, v


def paper_sync(tr, after, notes, paper_rows):
    """Advance one paper trade: confirm the fill, keep the GTC stop and TP1 order in line with the
    plan (replayed from the actual fill), and record the result once the position is flat."""
    p, sym = tr["paper"], tr["sym"]
    if p["status"] == "submitted":
        o = ap("GET", f"/v2/orders/{p['entry_id']}", params={"nested": "true"})
        if o is None:
            p["status"] = "error"; notes.append(f"{sym}: entry order not found"); return
        filled = float(o.get("filled_qty") or 0)
        if o["status"] == "filled" or (filled > 0 and o["status"] in ("canceled", "expired")):
            for leg in o.get("legs") or []:
                ap_cancel(leg.get("id"))
            fill, qty = float(o["filled_avg_price"]), int(filled)
            stop = round(initial_stop(tr["setup"], fill, tr["atr"], tr["base_low"]), 2)
            so = ap_order(sym, qty, "sell", "stop", "gtc", stop_price=stop)
            tp1 = round(fill + BO_TP1_R * (fill - stop), 2)
            half = qty // 2 if tr["setup"] == "breakout" else 0     # pullbacks exit all at once
            lo = ap_order(sym, half, "sell", "limit", "gtc", limit_price=tp1) if half >= 1 else None
            p.update(status="open", fill=fill, qty=qty, stop0=stop, stop_px=stop, stop_id=so["id"],
                     tp1_px=tp1, tp1_id=lo["id"] if lo else None, half_qty=half,
                     fill_date=str(after.index[0].date()))
            notes.append(f"✅ {sym}: filled {qty} sh @ {money(fill)}, stop {money(stop)}"
                         + (f", TP1 {half} sh @ {money(tp1)}" if half else ""))
        elif o["status"] in ("canceled", "expired", "rejected"):
            p["status"] = "skipped"
            why = f", likely opened above {money(p['limit'])}" if p.get("limit") else ""
            notes.append(f"⏭ {sym}: entry not filled ({o['status']}{why})")
        return

    if p["status"] != "open":
        return
    pos = ap("GET", f"/v2/positions/{ap_sym(sym)}")
    if pos is None:                                         # flat: stop, TP1 + stop, or our exit
        ap_cancel(p.get("tp1_id")); ap_cancel(p.get("stop_id"))
        q, v = paper_fills([p.get("tp1_id"), p.get("stop_id"), p.get("exit_id")])
        pnl = v - q * p["fill"] if q else None
        risk_d = p["qty"] * (p["fill"] - p["stop0"])
        r = pnl / risk_d if pnl is not None and risk_d > 0 else None
        p.update(status="closed", pnl=pnl, r=r)
        paper_rows.append({"sym": sym, "setup": tr["setup"], "signal_date": tr["signal_date"], "fill_date": p["fill_date"],
                           "close_date": str(after.index[-1].date()), "qty": p["qty"], "fill": p["fill"],
                           "stop0": p["stop0"], "exit_avg": round(v / q, 4) if q else "",
                           "pnl": round(pnl, 2) if pnl is not None else "", "r": round(r, 3) if r is not None else ""})
        notes.append(f"🏁 {sym}: closed " + (f"{r:+.2f}R (${pnl:+,.0f})" if r is not None else "(P/L unknown)"))
        return

    cur_qty = int(float(pos["qty"]))
    bars = after[after.index >= pd.Timestamp(p["fill_date"])]
    res = simulate(tr["setup"], p["fill"], p["stop0"], tr["atr"], bars, slip_bps=0)
    want = res["stop"] if not res["done"] else p["stop_px"]
    if p.get("tp1_id") and not p.get("tp1_done"):
        o = ap("GET", f"/v2/orders/{p['tp1_id']}")
        if o and o["status"] == "filled":
            p["tp1_done"] = True
            want = max(want, p["fill"])
            notes.append(f"🎯 {sym}: TP1 filled, {o['filled_qty']} sh @ {money(float(o['filled_avg_price']))}")
    want = round(want, 2)
    exit_now = res["done"] or res.get("pending_exit")
    if exit_now and not p.get("exit_id"):
        ap_cancel(p.get("tp1_id")); ap_cancel(p.get("stop_id"))
        eo = ap_order(sym, cur_qty, "sell", "market", "day")
        p["exit_id"] = eo["id"]
        notes.append(f"🔔 {sym}: market sell {cur_qty} sh queued for the open ({res.get('reason') or res.get('pending_exit')})")
        return
    so = ap("GET", f"/v2/orders/{p['stop_id']}") if p.get("stop_id") else None
    so_qty = int(float(so["qty"])) if so else 0
    if so and so["status"] in OPEN_STATUSES and (want > p["stop_px"] + 0.009 or so_qty != cur_qty):
        new = ap("PATCH", f"/v2/orders/{p['stop_id']}",
                 json={"qty": str(cur_qty), "stop_price": f"{max(want, p['stop_px']):.2f}"})
        if new:
            if want > p["stop_px"] + 0.009:
                notes.append(f"⬆️ {sym}: stop raised {money(p['stop_px'])} → {money(want)}")
            p["stop_id"], p["stop_px"] = new["id"], max(want, p["stop_px"])


PAPER_COLS = ["sym", "setup", "signal_date", "fill_date", "close_date", "qty", "fill", "stop0", "exit_avg", "pnl", "r"]


def write_paper(rows, equity):
    if rows:
        new = not PAPER_FILE.exists()
        with PAPER_FILE.open("a") as f:
            if new:
                f.write(",".join(PAPER_COLS) + "\n")
            f.write("\n".join(",".join(str(r[c]) for c in PAPER_COLS) for r in rows) + "\n")
    if equity is not None:
        new = not EQUITY_FILE.exists()
        with EQUITY_FILE.open("a") as f:
            if new:
                f.write("date,equity\n")
            f.write(f"{dt.date.today()},{equity:.2f}\n")


# ---------------- live run ----------------
def run(force=False):
    now = dt.datetime.now(ET)
    today = now.date()
    state = load_state()
    if not force:
        if now.weekday() >= 5 or (now.hour, now.minute) < RUN_AFTER_ET:
            print("Outside the after-close window; nothing to do."); return
        if state.get("last_run") == str(today):
            print("Already ran today."); return

    syms, _ = get_universe(state, today)
    held = {t["sym"] for t in state["trades"]}
    data = load_data(set(syms) | held, "2y")
    spy = data.get("SPY")
    if spy is None:
        print("SPY data missing; skipping."); return
    last_bar = spy.index[-1].date()
    if not force and last_bar != today:
        print(f"Latest bar is {last_bar}, not today (holiday?)."); save_state(state); return

    equity, buying_power, notes, paper_rows = None, 0.0, [], []
    if PAPER:
        try:
            acct = ap("GET", "/v2/account")
            equity, buying_power = float(acct["equity"]), float(acct["buying_power"])
        except Exception as e:
            print("Alpaca account check failed:", e)
            notes.append(f"⚠ Alpaca unreachable ({type(e).__name__}); paper orders skipped today")

    spy_ma = spy.Close.rolling(REGIME_SMA).mean()
    regime = bool(spy.Close.iloc[-1] > spy_ma.iloc[-1])
    if state.get("regime") is not None and state["regime"] != regime:
        send("Market regime " + ("ON" if regime else "OFF"),
             (f"SPY closed {money(spy.Close.iloc[-1])}, "
              f"{'above' if regime else 'below'} its 200-day ({money(spy_ma.iloc[-1])}).\n")
             + ("New swing entries are back on." if regime else
                "No new swing entries until SPY closes back above. Open trades keep their stops."),
             "high", "chart_with_upwards_trend" if regime else "warning")
    state["regime"] = regime

    ind = {}
    def get_ind(sym):
        if sym not in ind and sym in data:
            ind[sym] = add_ind(data[sym].copy(), spy)
        return ind.get(sym)

    stamp = str(last_bar)
    alerts, outcomes, keep = [], [], []

    def paper_live(tr):
        return bool(tr.get("paper")) and tr["paper"]["status"] in ("submitted", "open")

    # 1) manage tracked trades (model record + paper account)
    for tr in state["trades"]:
        df = get_ind(tr["sym"])
        if df is None:
            keep.append(tr); continue
        after = df[df.index > pd.Timestamp(tr["signal_date"])]
        if after.empty:
            keep.append(tr); continue
        loud = tr.get("pushed", False)

        if not tr.get("model_done"):
            o = float(after.Open.iloc[0])
            if tr["status"] == "pending":
                if tr["setup"] == "breakout" and o > tr["pivot"] * (1 + BO_MAX_GAP):
                    alerts.append(f"{stamp},{tr['sym']},{tr['setup']},skipped-gap,{o}")
                    tr["model_done"] = True
                    if loud:
                        send(f"SKIP {tr['sym']}", f"⏭ {tr['sym']} opened {money(o)}, more than {BO_MAX_GAP:.0%} "
                             f"above the base high {money(tr['pivot'])}. Breakout skipped (chasing).")
                else:
                    stop = initial_stop(tr["setup"], o * (1 + SLIP_BPS / 1e4), tr["atr"], tr["base_low"])
                    tr.update(status="open", entry_open=o, stop0=stop, entry_date=str(after.index[0].date()))
                    if loud:
                        fill = o * (1 + SLIP_BPS / 1e4)
                        send(f"FILLED {tr['sym']}", f"✅ {tr['sym']} {tr['setup']}: opened {money(o)}.\n"
                             f"Set a GTC stop at {money(stop)}.\n"
                             f"TP1 {money(fill + BO_TP1_R * (fill - stop))}: sell half, stop to entry\n"
                             f"{size_line(fill, stop)}", "default", "white_check_mark")
            if tr["status"] == "open" and not tr.get("model_done"):
                res = simulate(tr["setup"], tr["entry_open"], tr["stop0"], tr["atr"], after)
                if res["done"]:
                    tr["model_done"] = True
                    outcomes.append({"signal_date": tr["signal_date"], "entry_date": tr["entry_date"],
                                     "exit_date": res["exit_date"].date(), "sym": tr["sym"], "setup": tr["setup"],
                                     "pushed": loud, "entry": round(res["entry"], 4), "stop": round(tr["stop0"], 4),
                                     "exit": round(res["exit_px"], 4), "r": round(res["r"], 3),
                                     "ret_pct": round(res["ret_pct"], 3), "days": res["days"], "reason": res["reason"],
                                     "mfe_r": round(res["mfe"], 2), "mae_r": round(res["mae"], 2)})
                    alerts.append(f"{stamp},{tr['sym']},{tr['setup']},closed {res['r']:+.2f}R,{res['exit_px']:.4f}")
                    if loud:
                        send(f"CLOSED {tr['sym']}", f"🏁 {tr['sym']} {tr['setup']}: {res['r']:+.2f}R "
                             f"({res['ret_pct']:+.1f}%) via {res['reason']} after {res['days']} sessions.")
                elif loud:
                    a = tr["atr"]
                    if res.get("pending_exit") and not tr.get("exit_sent"):
                        q = 0.5 if res["half"] else 1.0
                        open_r = res["r"] + q * (float(after.Close.iloc[-1]) - res["entry"]) / res["risk"]
                        send(f"SELL {tr['sym']}", f"🔔 SELL {tr['sym']} at tomorrow's open ({res['pending_exit']}).\n"
                             f"Open P/L at today's close about {open_r:+.2f}R.", "high", "bell")
                        tr["exit_sent"] = True
                    if res["half"] and not tr.get("tp1_sent"):
                        send(f"TP1 {tr['sym']}", f"🎯 {tr['sym']} hit TP1 {money(res['tp1'])}: sell half, "
                             f"move the stop to {money(res['stop'])}.", "high", "dart")
                        tr["tp1_sent"] = True
                        tr["stop_sent"] = res["stop"]
                    last = tr.get("stop_sent", tr["stop0"])
                    if res["stop"] - last >= TRAIL_PUSH_ATR * a:
                        send(f"RAISE STOP {tr['sym']}", f"⬆️ {tr['sym']}: raise the stop to {money(res['stop'])} "
                             f"(was {money(last)}), locks {(res['stop'] - res['entry']) / res['risk']:+.1f}R on the runner.")
                        tr["stop_sent"] = res["stop"]

        if PAPER and equity is not None and paper_live(tr):
            try:
                paper_sync(tr, after, notes, paper_rows)
            except Exception as e:
                notes.append(f"⚠ {tr['sym']} paper sync failed: {str(e)[:120]}")
        if not tr.get("model_done") or paper_live(tr):
            keep.append(tr)
    state["trades"] = keep

    # 2) new signals (regime on only)
    taken = {(t["sym"], t["setup"]) for t in keep}
    cands = {s: [] for s in SETUPS}
    if regime:
        for sym in syms:
            df = get_ind(sym)
            if df is None or df.index[-1].date() != last_bar:
                continue
            row = df.iloc[-1]
            for s in SETUPS:
                if row[f"sig_{s}"] and (sym, s) not in taken:
                    cands[s].append((sym, row))
    cands["pullback"].sort(key=lambda x: x[1].rsi2)
    cands["breakout"].sort(key=lambda x: -x[1].vx)

    paper_open = {s: sum(1 for t in keep if t["setup"] == s and paper_live(t)) for s in SETUPS}
    paper_cap = {"breakout": PAPER_MAX_OPEN, "pullback": PAPER_PB_MAX_OPEN}
    for s in SETUPS:
        muted = []
        for n, (sym, row) in enumerate(cands[s]):
            push = s in PUSH_SETUPS and n < MAX_PUSH_PER_SETUP
            tr = {"sym": sym, "setup": s, "signal_date": stamp, "status": "pending", "pushed": push,
                  "atr": float(row.atr), "base_low": float(row.base_low), "pivot": float(row.base_hi),
                  "close": float(row.Close)}
            keep.append(tr)
            alerts.append(f"{stamp},{sym},{s},signal{'' if push else '-muted'},{row.Close}")
            paper_txt = ""
            if PAPER and equity is not None and s in PAPER_SETUPS:
                if paper_open[s] >= paper_cap[s]:
                    notes.append(f"{sym}: no paper order, {paper_cap[s]} {s} positions already open")
                else:
                    try:
                        p = paper_enter(tr, equity, buying_power)
                        if p:
                            tr["paper"] = p
                            paper_open[s] += 1
                            buying_power -= p["cost"]
                            how = f"limit {money(p['limit'])}" if p["limit"] else "at the open"
                            paper_txt = (f"📄 Paper order queued: buy {p['qty']} sh {how}, "
                                         f"stop {money(p['stop_px'])}")
                            notes.append(f"📝 {sym} {s}: {p['qty']} sh {how} queued")
                        else:
                            notes.append(f"{sym}: no paper order, not enough risk budget or buying power for 1 share")
                    except Exception as e:
                        notes.append(f"⚠ {sym} paper order failed: {str(e)[:120]}")
            if not push:
                if s in PUSH_SETUPS:
                    muted.append(sym)
                continue
            title, lines, target = entry_msg(sym, s, row)
            lines.append(option_idea(sym, float(row.Close), s, hv20(data[sym].Close), target))
            ed = earnings_days(sym)
            if ed is not None and 0 <= ed <= EARN_WARN_DAYS[s]:
                lines.append(f"⚠ earnings in {ed} days, inside the usual hold. Consider skipping or sizing down.")
            lines.append("Market: SPY above its 200-day ✓")
            if paper_txt:
                lines.append(paper_txt)
            send(title, "\n".join(x for x in lines if x), "high", "rocket" if s == "breakout" else "green_circle")
        if muted:
            send(f"More {s} signals", f"Also signaled today ({s}, tracked but not pushed): {', '.join(muted)}",
                 "low", "memo")

    if PAPER and equity is not None:
        try:
            equity = float(ap("GET", "/v2/account")["equity"])
        except Exception:
            pass
    if notes:
        head = f"Paper account ${equity:,.0f}\n" if equity is not None else ""
        send("Paper trading", head + "\n".join(notes), "low", "page_facing_up")

    state["trades"] = keep
    state["last_run"] = str(today)
    save_state(state)
    log_alert(alerts)
    write_outcomes(outcomes)
    write_paper(paper_rows, equity if PAPER else None)
    if outcomes or paper_rows or not SUMMARY_FILE.exists():
        SUMMARY_FILE.write_text(summarize(len(keep)))
    print(f"Regime {'ON' if regime else 'OFF'} | pullback {len(cands['pullback'])} | "
          f"breakout {len(cands['breakout'])} | tracked {len(keep)} | closed {len(outcomes)} | "
          f"paper {'on' if PAPER else 'off'}" + (f" ${equity:,.0f}" if equity is not None else ""))


def report():
    s = load_state()
    text = summarize(len(s.get("trades", [])))
    print(text)
    step_summary(text)


def main():
    if "--test" in sys.argv:
        send("Swing grader", "✅ Swing grader alerts are connected."); return
    if "--backtest" in sys.argv:
        backtest(); return
    if "--report" in sys.argv:
        report(); return
    run(force=FORCE_RUN)


if __name__ == "__main__":
    main()
