"""
A+ Setup Grader - alert runner for GitHub Actions.
Grades each coin with the same rules as the browser grader, using closed
Kraken candles: five scored checks (level, confirmations, R:R, volume, clean
price action), daily trend as context only, and the RSI re-entry gate deciding
Actionable vs Wait. Sends a phone push (ntfy) when a coin grades B+ or better
("setup graded, waiting on RSI") or turns Actionable (grade plus RSI gate).
Also flags 4H breakouts and momentum shifts, where 5m and 15m flip against
the 4H trend with divergence and money-flow confluence pointing to a 4H cross.
"""
import json, math, os, time, sys
from pathlib import Path
import requests
import numpy as np
import pandas as pd

# ---------- settings ----------
WATCHLIST = {  # display name -> Kraken pair
    "BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD",
    "ZEC": "ZECUSD", "LINK": "LINKUSD", "UNI": "UNIUSD", "XLM": "XLMUSD",
    "HBAR": "HBARUSD", "NEAR": "NEARUSD",
}
MIN_RR = 2.0            # minimum reward:risk
BO_LOOKBACK = 20        # 4H bars for the breakout range
BO_VOL_MULT = 1.5       # breakout bar volume vs 20-bar average
BO_COOLDOWN_HRS = 12
# Momentum shift settings — lower timeframes flip first, 4H confirmed as about to follow
MS_MIN = int(os.environ.get("MS_MIN", "5"))              # confluence factors needed (of 7)
MS_MAX_BARS = float(os.environ.get("MS_MAX_BARS", "6"))  # projected 4H bars until the EMA cross
MS_ATR_MULT = float(os.environ.get("MS_ATR_MULT", "1.5"))
MS_COOLDOWN_HRS = int(os.environ.get("MS_COOLDOWN_HRS", "8"))
COOLDOWN_HRS = 4        # don't repeat the same tier for a coin within this window
STATE_V = 2             # bump when grading rules change so old tiers reset
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

# ---------- grading (same rules as the browser grader) ----------
# Five scored checks: level, confirmations, R:R, volume, clean price action.
# Daily trend is context only. 5/5 = A+, 4/5 = B+, 3/5 = C, else D.
# Actionable only when the grade is B+ or better AND the RSI re-entry gate is live.
PROX_PCT = 2.0          # entry must be within this % of the key level
TOL_PCT = 0.8           # pivots within this % are the same level
MIN_TOUCHES = 2
WEAK_TOUCHES = 4        # this many tests or more = level weakening (caution only)
STOP_ATR = 1.0          # ATR buffer beyond the level for the stop
VOL_BREAKOUT = 1.5      # breakout bar volume vs 20-bar average
VOL_BOUNCE = 1.2        # bounce bar volume vs 20-bar average
MIN_CONFIRMS = 3
CHOP_PASS = 50.0        # choppiness under this passes
CHOP_MAX = 61.8         # over this is choppy; in between is neutral (no pass)
RSI4H_TRIGGER = 32
RSI4H_WATCH = 35
RSI_D_LO, RSI_D_HI = 45, 55
NAN = float("nan")
fin = math.isfinite


def _cols(df):
    return {k: df[k].to_numpy(dtype=float) for k in ("t", "o", "h", "l", "c", "v")}


def _ratio(a, b):
    return a / b if b and fin(b) else NAN


def sma_js(a, n):
    return pd.Series(a).rolling(n).mean().to_numpy()


def ema_js(a, n):
    """SMA-seeded EMA, identical to the browser grader."""
    out = np.full(len(a), NAN)
    if len(a) < n:
        return out
    k = 2 / (n + 1)
    prev = float(np.mean(a[:n]))
    out[n - 1] = prev
    for i in range(n, len(a)):
        prev = a[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi_js(c, n=14):
    """Wilder RSI seeded with a simple average, identical to the browser grader."""
    out = np.full(len(c), NAN)
    if len(c) <= n:
        return out
    d = np.diff(c)
    g = d[:n].clip(min=0).sum() / n
    lo = (-d[:n]).clip(min=0).sum() / n
    out[n] = 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)
    for i in range(n + 1, len(c)):
        x = c[i] - c[i - 1]
        g = (g * (n - 1) + max(x, 0)) / n
        lo = (lo * (n - 1) + max(-x, 0)) / n
        out[i] = 100.0 if lo == 0 else 100 - 100 / (1 + g / lo)
    return out


def macd_js(c):
    m = ema_js(c, 12) - ema_js(c, 26)
    signal = np.full(len(c), NAN)
    if len(c) > 25:
        signal[25:] = ema_js(m[25:], 9)
    return m, signal, m - signal


def true_range(X):
    h, l, c = X["h"], X["l"], X["c"]
    tr = h - l
    pc = np.concatenate(([NAN], c[:-1]))
    tr[1:] = np.maximum.reduce([(h - l)[1:], np.abs(h - pc)[1:], np.abs(l - pc)[1:]])
    return tr


def atr_js(X, n=14):
    tr = true_range(X)
    out = np.full(len(tr), NAN)
    if len(tr) < n:
        return out
    prev = tr[:n].mean()
    out[n - 1] = prev
    for i in range(n, len(tr)):
        prev = (prev * (n - 1) + tr[i]) / n
        out[i] = prev
    return out


def chop_js(X, n=14):
    if len(X["c"]) < n + 1:
        return NAN
    tr = true_range(X)[-n:]
    hh, ll = X["h"][-n:].max(), X["l"][-n:].min()
    if hh == ll:
        return 100.0
    return 100 * math.log10(tr.sum() / (hh - ll)) / math.log10(n)


def pivots_js(h, l, L=3,
