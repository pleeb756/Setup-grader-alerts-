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
