"""
A+ Setup Grader - alert runner for GitHub Actions (v3: trend-pullback engine).

v3 replaces the breakout / impulse / momentum-shift / pullback-grade alerts. Their tracked
outcomes (80 trades, 9% wins, -56.7R) showed entries after the move was spent and stops
inside normal noise. The one live setup is now a trend pullback:

  1. Daily trend: close above the daily 50 EMA, 20 EMA above the 50, and the 50 rising
     (mirror for shorts). No daily trend, no trade.
  2. 4H stack: 4H 20 EMA on the trend side of the 4H 50 EMA.
  3. Not choppy: 4H choppiness index <= CHOP_GATE and 4H ADX >= ADX_MIN.
  4. Pullback: within the last PB_BARS 4H bars price came back to the 4H 20 EMA, or retested
     a 20-bar range level it broke in the last RETEST_WITHIN bars. A close more than
     PB_FLOOR_ATR beyond the 4H 50 EMA means the trend broke and cancels the setup.
  5. Trigger: a closed 4H reclaim candle (closes in trend direction, beyond the prior bar's
     extreme and the 20 EMA, in the outer half of its range). In the zone without a trigger
     sends a WATCH push instead.
  6. Vetoes: entry more than MAX_EXT_ATR from the pullback zone (chasing), stop wider than
     MAX_STOP_ATR, 4H RSI overheated, heavy money flow already in the trade direction
     (the old outcomes' worst bucket), or perp funding crowded on the trade side.

Stops sit beyond the pullback's swing extreme plus STOP_BUF_ATR, never closer than
MIN_STOP_ATR x 4H ATR. Size each trade to a fixed dollar risk (set RISK_USD to see the
quantity in the push). Exits: half off at TP1_R, stop to entry, and the runner trails a
chandelier stop TRAIL_ATR x 4H ATR behind the best price since entry. The runner sends
pushes for TP1, each stop move of TRAIL_PUSH_ATR or more, and the close.

Funding comes from Kraken Futures public historical funding (relative rate, annualized).
Metals and any coin without a Kraken perp simply skip that check.

At most MAX_PUSH_PER_SIDE entries per direction push per run (strongest ADX first); in a
broad move the rest are the same market bet. Muted entries are still tracked.

Outcomes: trend trades are replayed on closed 1H bars with the same TP1 + trail rules and
written to outcomes.csv (kind "trend", grade = pullback zone, target = TP1). Older rows and
any still-open legacy trades are kept and resolved with their original fixed targets.

Backtest: `python grader.py --backtest` replays the last BT_DAYS of 4H bars with fees and
slippage and compares three exit plans on the same entries: plan (TP1 + trail), fixed2R
(whole position to 2R), and trail_only (no partial). Report goes to the Actions summary.

The legacy signal functions (grade, breakout, impulse, momentum_shift, order blocks,
value area, money flow) stay in this file because papertrade.py imports them; they no
longer send alerts or track outcomes here.
"""
import json, math, os, time, sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
import numpy as np
import pandas as pd

# ---------- settings ----------
WATCHLIST = {  # display name -> data source (Kalshi perps only)
    # crypto: Kraken spot pairs
    "BTC": "XBTUSD", "ETH": "ETHUSD", "HYPE": "HYPEUSD", "XRP": "XRPUSD",
    "SOL": "SOLUSD", "ZEC": "ZECUSD", "NEAR": "NEARUSD", "SUI": "SUIUSD",
    "DOGE": "XDGUSD", "LTC": "LTCUSD", "LINK": "LINKUSD", "kSHIB": "SHIBUSD",
    "VVV": "VVVUSD", "ADA": "ADAUSD", "WLD": "WLDUSD", "BNB": "BNBUSD",
    "AAVE": "AAVEUSD",
    # metals: COMEX/NYMEX front-month futures via Yahoo Finance ("yf:" prefix)
    "Gold": "yf:GC=F", "Silver": "yf:SI=F", "Platinum": "yf:PL=F", "Palladium": "yf:PA=F",
}
# Kalshi quotes kSHIB per 1,000 SHIB; scale Kraken prices so alerts match the app.
PRICE_MULT = {"SHIBUSD": 1000}

# ----- trend-pullback engine (live alerts) -----
D_SLOPE_BARS = 5                                              # daily 50 EMA must rise over this many days
ADX_MIN = float(os.environ.get("ADX_MIN", "20"))              # 4H ADX floor
CHOP_GATE = float(os.environ.get("CHOP_GATE", "61.8"))        # 4H choppiness ceiling
PB_BARS = int(os.environ.get("PB_BARS", "6"))                 # 4H bars to look back for the pullback
PB_TOUCH_ATR = 0.25          # a low within this many ATR of the 20 EMA (or retest level) counts as a touch
PB_FLOOR_ATR = 0.5           # a close this many ATR beyond the 50 EMA = trend broken
RETEST_RANGE = 20            # 4H bars that define a broken range level
RETEST_WITHIN = 12           # the break must be this recent (4H bars)
MAX_EXT_ATR = float(os.environ.get("MAX_EXT_ATR", "1.0"))     # entry this far past the 20 EMA = chasing
STOP_BUF_ATR = 0.25          # stop buffer beyond the pullback swing
MIN_STOP_ATR = float(os.environ.get("MIN_STOP_ATR", "1.5"))   # stop never closer than this
MAX_STOP_ATR = float(os.environ.get("MAX_STOP_ATR", "3.0"))   # skip if the structure stop is wider
TP1_R = float(os.environ.get("TP1_R", "1.5"))                 # half off here, stop to entry
TRAIL_ATR = float(os.environ.get("TRAIL_ATR", "3.0"))         # chandelier distance for the runner
TRAIL_PUSH_ATR = 1.0         # push a stop move once the trail has moved this many ATR
RSI_HOT = float(os.environ.get("RSI_HOT", "75"))              # 4H RSI veto (shorts: 100 - this)
FUND_MAX_APR = float(os.environ.get("FUND_MAX_APR", "30"))    # funding %/yr on your side = crowded
RISK_USD = float(os.environ.get("RISK_USD", "0"))             # >0 shows position size in pushes
TREND_PUSH = os.environ.get("TREND_PUSH", "1") == "1"
WATCH_PUSH = os.environ.get("WATCH_PUSH", "1") == "1"
MAX_PUSH_PER_SIDE = int(os.environ.get("MAX_PUSH_PER_SIDE", "2"))
WATCH_COOLDOWN_HRS = int(os.environ.get("WATCH_COOLDOWN_HRS", "12"))

# ----- backtest -----
BT_DAYS = int(os.environ.get("BT_DAYS", "90"))
BT_FEE_BPS = float(os.environ.get("BT_FEE_BPS", "12"))        # per side
BT_SLIP_BPS = float(os.environ.get("BT_SLIP_BPS", "5"))       # entry and stop fills
BT_MODES = ("plan", "fixed2R", "trail_only")

# ----- legacy signal settings (used by papertrade.py's baseline) -----
MIN_RR = 2.0
BO_LOOKBACK = 20
BO_VOL_MULT = 1.5
BO_RSI_MAX = float(os.environ.get("BO_RSI_MAX", "85"))
BO_STOP_ATR = 0.5
BO_TARGET_R = 2.0
IMP_LOOKBACK = int(os.environ.get("IMP_LOOKBACK", "48"))
IMP_ATR_MULT = float(os.environ.get("IMP_ATR_MULT", "2.0"))
IMP_VOL_MULT = float(os.environ.get("IMP_VOL_MULT", "3.0"))
IMP_CLOSE_POS = 0.6
IMP_TARGET_R = float(os.environ.get("IMP_TARGET_R", "2.0"))
IMP_STOP_ATR = 0.25
MS_MIN = int(os.environ.get("MS_MIN", "5"))
MS_MAX_BARS = float(os.environ.get("MS_MAX_BARS", "6"))
MS_ATR_MULT = float(os.environ.get("MS_ATR_MULT", "1.5"))

STATE_V = 3             # v3 = trend-pullback engine
STATE_FILE = Path("state.json")
LOG_FILE = Path("alerts_log.csv")
OUT_FILE = Path("outcomes.csv")
SUMMARY_FILE = Path("outcomes_summary.md")
METALS_FILE = Path("metals.json")   # metal candles for the browser grader (browsers can't read Yahoo)

# Value area (auction market theory) settings - info only
VA_BARS = int(os.environ.get("VA_BARS", "42"))
VA_ACCEPT = int(os.environ.get("VA_ACCEPT", "3"))
VA_PCT = 0.70
VA_BINS = 60
VA_GATE = os.environ.get("VA_GATE", "0") == "1"

# Money flow: direction from CMF/OBV, intensity from 4H volume vs its average
FLOW_VOL_MULT = float(os.environ.get("FLOW_VOL_MULT", "1.5"))
FLOW_CMF_MIN = 0.05
FLOW_SLOPE_BARS = 3

# Order blocks (info only)
OB_LOOKBACK = int(os.environ.get("OB_LOOKBACK", "120"))
OB_DISP_ATR = float(os.environ.get("OB_DISP_ATR", "1.5"))
OB_SEARCH = 5
OB_NEAR_ATR = 1.0
OB_TOL_ATR = 0.1
OB_MAX_TESTS = int(os.environ.get("OB_MAX_TESTS", "3"))

# Outcome tracking
MAX_HOLD_HRS = int(os.environ.get("MAX_HOLD_HRS", "336"))  # 14 days, then close at market

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
LOCAL_TZ = ZoneInfo(os.environ.get("ALERT_TZ", "America/Los_Angeles"))  # times shown in alerts

# ---------- data ----------
# ---------- metals (Yahoo Finance futures) ----------
# Yahoo has no 4H bars, so 4H is built from closed 1H bars. Futures pause daily and on
# weekends, so metals simply get no new bars while the market is closed.
YF_SPEC = {1440: ("1d", "2y"), 240: ("60m", "60d"), 60: ("60m", "60d"),
           15: ("15m", "5d"), 5: ("5m", "2d")}
YF_HEADERS = {"User-Agent": "Mozilla/5.0 (setup-grader)"}
_yf_cache = {}


def _yf_fetch(sym, interval, rng):
    key = (sym, interval)
    if key in _yf_cache:
        return _yf_cache[key]
    last_err = None
    for attempt in range(4):
        host = "query1" if attempt % 2 == 0 else "query2"
        try:
            r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"interval": interval, "range": rng},
                             headers=YF_HEADERS, timeout=20)
            if r.status_code == 429:
                last_err = "rate limited"; time.sleep(3 * (attempt + 1)); continue
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            df = pd.DataFrame({"t": res["timestamp"], "o": q["open"], "h": q["high"],
                               "l": q["low"], "c": q["close"], "v": q["volume"]})
            df = df.dropna(subset=["o", "h", "l", "c"]).astype(
                {"t": int, "o": float, "h": float, "l": float, "c": float})
            df["v"] = df["v"].fillna(0).astype(float)
            df = df.drop_duplicates("t", keep="last").sort_values("t").reset_index(drop=True)
            _yf_cache[key] = df
            return df
        except Exception as e:
            last_err = e; time.sleep(2)
    raise RuntimeError(f"{sym} {interval}: {last_err}")


def yf_candles(sym, minutes):
    interval, rng = YF_SPEC[minutes]
    now = time.time()
    df = _yf_fetch(sym, interval, rng)
    if minutes == 240:
        h1 = df[df.t + 3600 <= now].copy()
        h1["b"] = h1.t // 14400 * 14400
        df = (h1.groupby("b").agg(o=("o", "first"), h=("h", "max"), l=("l", "min"),
                                   c=("c", "last"), v=("v", "sum"))
                .reset_index().rename(columns={"b": "t"}))
        step = 14400
    else:
        step = 86400 if minutes == 1440 else minutes * 60
    df = df[df.t + step <= now].reset_index(drop=True)     # closed bars only
    if len(df) < 30:
        raise RuntimeError(f"{sym}: only {len(df)} closed {minutes}m bars")
    return df


def candles(pair, minutes):
    """Closed candles: Yahoo futures for "yf:" symbols, Kraken spot for everything else."""
    if pair.startswith("yf:"):
        return yf_candles(pair[3:], minutes)
    return kraken_candles(pair, minutes)


def kraken_candles(pair, minutes):
    """Closed Kraken candles. Retries with backoff if Kraken rate-limits the run."""
    for attempt in range(4):
        r = requests.get("https://api.kraken.com/0/public/OHLC",
                         params={"pair": pair, "interval": minutes}, timeout=20)
        j = r.json()
        err = j.get("error") or []
        if any("Too many requests" in e or "Rate limit" in e for e in err):
            time.sleep(3 * (attempt + 1)); continue
        if err:
            raise RuntimeError(f"{pair}: {err}")
        key = next(k for k in j["result"] if k != "last")
        df = pd.DataFrame(j["result"][key],
                          columns=["t", "o", "h", "l", "c", "vwap", "v", "n"])
        df = df.astype({"o": float, "h": float, "l": float, "c": float, "v": float})
        m = PRICE_MULT.get(pair, 1)
        if m != 1:
            df[["o", "h", "l", "c"]] *= m
        return df.iloc[:-1].reset_index(drop=True)   # drop the still-forming bar
    raise RuntimeError(f"{pair}: still rate-limited after retries")

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


def pivots_js(h, l, L=3, R=3):
    highs, lows = [], []
    for i in range(L, len(h) - R):
        is_h = is_l = True
        for j in range(i - L, i + R + 1):
            if j == i:
                continue
            if h[j] >= h[i]: is_h = False
            if l[j] <= l[i]: is_l = False
        if is_h: highs.append((i, h[i]))
        if is_l: lows.append((i, l[i]))
    return {"highs": highs, "lows": lows}


def structure_js(h, l):
    p = pivots_js(h, l)
    if len(p["highs"]) < 2 or len(p["lows"]) < 2:
        return {"state": "unknown", "l2": NAN, "h2": NAN}
    h1, h2 = p["highs"][-2][1], p["highs"][-1][1]
    l1, l2 = p["lows"][-2][1], p["lows"][-1][1]
    state = "up" if h2 > h1 and l2 > l1 else "down" if h2 < h1 and l2 < l1 else "range"
    return {"state": state, "l2": l2, "h2": h2}


def cluster_levels(prices, tol):
    out, s, cnt = [], 0.0, 0
    for p in sorted(prices):
        if cnt and abs(p - s / cnt) / (s / cnt) * 100 <= tol:
            s += p; cnt += 1
        else:
            if cnt: out.append({"price": s / cnt, "touches": cnt})
            s, cnt = p, 1
    if cnt: out.append({"price": s / cnt, "touches": cnt})
    return out


def candle_info(X, i):
    if i < 1:
        return {}
    o, h, l, c = X["o"][i], X["h"][i], X["l"][i], X["c"][i]
    po, pc = X["o"][i - 1], X["c"][i - 1]
    rng, body = h - l, abs(c - o)
    lw, uw = min(o, c) - l, h - max(o, c)
    return {
        "body": body / rng if rng > 0 else 0,
        "bull_engulf": c > o and pc < po and c >= po and o <= pc,
        "bear_engulf": c < o and pc > po and c <= po and o >= pc,
        "hammer": rng > 0 and lw >= 2 * body and uw <= max(body, rng * 0.15) and lw / rng >= 0.55,
        "shooter": rng > 0 and uw >= 2 * body and lw <= max(body, rng * 0.15) and uw / rng >= 0.55,
    }


def divergence_js(X, r, L, lookback=40):
    p = pivots_js(X["h"], X["l"])
    min_i = len(X["c"]) - lookback
    pts = [x for x in (p["lows"] if L else p["highs"]) if x[0] >= min_i]
    if len(pts) < 2:
        return False
    (ia, pa), (ib, pb) = pts[-2], pts[-1]
    return (pb < pa and r[ib] > r[ia]) if L else (pb > pa and r[ib] < r[ia])


def crossed_within(a, b, bars, up):
    n = len(a)
    for k in range(bars):
        i = n - 1 - k
        if i < 1 or not all(fin(x) for x in (a[i], b[i], a[i - 1], b[i - 1])):
            continue
        if up and a[i - 1] <= b[i - 1] and a[i] > b[i]: return True
        if not up and a[i - 1] >= b[i - 1] and a[i] < b[i]: return True
    return False


# ---------- value area (volume profile on 4H) ----------
def volume_profile(h, l, v, bins=VA_BINS):
    """Spread each bar's volume evenly across its high-low range. Returns POC, VAL, VAH."""
    lo, hi = float(l.min()), float(h.max())
    if not (hi > lo):
        return None
    edges = np.linspace(lo, hi, bins + 1)
    width = h - l
    overlap = np.clip(np.minimum(h[:, None], edges[1:]) - np.maximum(l[:, None], edges[:-1]), 0, None)
    share = np.where(width[:, None] > 0, overlap / np.where(width > 0, width, 1)[:, None], 0.0)
    flat = width <= 0                                  # zero-range bars go to their own bin
    if flat.any():
        idx = np.clip(np.searchsorted(edges, h[flat], side="right") - 1, 0, bins - 1)
        share[np.where(flat)[0], idx] = 1.0
    vol = (share * v[:, None]).sum(axis=0)
    total = vol.sum()
    if total <= 0:
        return None
    poc = int(np.argmax(vol))
    a = b = poc
    acc = vol[poc]
    while acc < VA_PCT * total and (a > 0 or b < bins - 1):
        up = vol[b + 1] if b < bins - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn: b += 1; acc += up
        else:        a -= 1; acc += dn
    return {"poc": (edges[poc] + edges[poc + 1]) / 2, "val": edges[a], "vah": edges[b + 1]}


def value_state(F, price, L):
    """Balance vs imbalance against the prior value area, and whether the setup side fits it.

    The profile covers the VA_BARS 4H bars before the last VA_ACCEPT bars, so recent closes
    are judged against value built earlier. Acceptance = all of the last VA_ACCEPT closes
    outside value. Outside value without acceptance is a probe (possible failed auction).
    """
    n = len(F["c"])
    if n < VA_BARS + VA_ACCEPT:
        return {"state": "unknown", "fit": False, "note": "not enough 4H history for a profile"}
    sl = slice(n - VA_BARS - VA_ACCEPT, n - VA_ACCEPT)
    vp = volume_profile(F["h"][sl], F["l"][sl], F["v"][sl])
    if not vp:
        return {"state": "unknown", "fit": False, "note": "flat profile"}
    closes = F["c"][-VA_ACCEPT:]
    if (closes > vp["vah"]).all():   state = "imbalance_up"
    elif (closes < vp["val"]).all(): state = "imbalance_down"
    elif price > vp["vah"]:          state = "probe_up"
    elif price < vp["val"]:          state = "probe_down"
    else:                            state = "balance"

    if L:
        if state == "imbalance_up":
            fit, why = True, "accepted above value, continuation long"
        elif state == "balance" and price <= vp["poc"]:
            fit, why = True, "lower half of balance, rotation toward POC/VAH"
        elif state == "balance":
            fit, why = False, "buying the upper half of balance"
        elif state == "imbalance_down":
            fit, why = False, "long against accepted selling"
        else:
            fit, why = False, f"{state.replace('_', ' ')} not accepted yet"
    else:
        if state == "imbalance_down":
            fit, why = True, "accepted below value, continuation short"
        elif state == "balance" and price >= vp["poc"]:
            fit, why = True, "upper half of balance, rotation toward POC/VAL"
        elif state == "balance":
            fit, why = False, "selling the lower half of balance"
        elif state == "imbalance_up":
            fit, why = False, "short against accepted buying"
        else:
            fit, why = False, f"{state.replace('_', ' ')} not accepted yet"
    return {"state": state, "fit": fit, "note": why, **vp}


def grade(d, h4, h1):
    """Grade a coin with the browser grader's rules. Direction comes from the daily chart."""
    D, F, H = _cols(d), _cols(h4), _cols(h1)
    if len(H["c"]) < 60 or len(F["c"]) < 80 or len(D["c"]) < 60:
        raise RuntimeError("not enough price history")
    price = H["c"][-1]

    # daily: trend (context only) and direction
    dc = D["c"]
    dE50, dE200, dRsi = ema_js(dc, 50), ema_js(dc, 200), rsi_js(dc)
    dS200 = sma_js(dc, 200)
    ds = structure_js(D["h"], D["l"])
    di = len(dc) - 1
    e200 = fin(dE200[di])
    d_above = dc[di] > dE50[di] and (not e200 or dc[di] > dE200[di])
    d_below = dc[di] < dE50[di] and (not e200 or dc[di] < dE200[di])
    d_stack = ("bull" if dE50[di] > dE200[di] else "bear") if e200 else "n/a"
    if ds["state"] == "up" or (d_above and d_stack == "bull"):
        side = "long"
    elif ds["state"] == "down" or (d_below and d_stack == "bear"):
        side = "short"
    else:
        side = "long"
    L = side == "long"

    # 4H setup, 1H trigger
    hc, hv = F["c"], F["v"]
    hE50, hRsi = ema_js(hc, 50), rsi_js(hc)
    macd, signal, hist = macd_js(hc)
    hVolAvg, a4 = sma_js(hv, 20), atr_js(F)
    i = len(hc) - 1
    atr4 = a4[i]
    v1Avg = sma_js(H["v"], 20)
    j = len(H["c"]) - 1
    t1 = candle_info(H, j)

    trend_ok = (ds["state"] == ("up" if L else "down") and (d_above if L else d_below)
                and d_stack == ("bull" if L else "bear")
                and (hc[i] > ds["l2"] if L else hc[i] < ds["h2"]))

    # levels from 4H + daily pivots
    p4 = pivots_js(F["h"][-200:], F["l"][-200:])
    pdl = pivots_js(D["h"][-150:], D["l"][-150:])
    allp = [p for _, p in p4["highs"] + p4["lows"] + pdl["highs"] + pdl["lows"]]
    levels = [x for x in cluster_levels(allp, TOL_PCT) if x["touches"] >= MIN_TOUCHES]
    below = sorted([x for x in levels if x["price"] <= price * 1.002], key=lambda x: -x["price"])
    above = sorted([x for x in levels if x["price"] > price * 0.998], key=lambda x: x["price"])
    key = (below[0] if below else None) if L else (above[0] if above else None)
    dist = ((price - key["price"]) if L else (key["price"] - price)) / price * 100 if key else NAN

    fHi, fLo = F["h"][-120:].max(), F["l"][-120:].min()

    # 2. level: near, tested, and holding on a 4H close
    holds = bool(key) and (hc[i] >= key["price"] if L else hc[i] <= key["price"])
    weak = bool(key) and key["touches"] >= WEAK_TOUCHES
    near = bool(key) and abs(dist) <= PROX_PCT
    c_level = bool(key) and key["touches"] >= MIN_TOUCHES and near and holds
    word = "support" if L else "resistance"
    if not key:
        level_note = f"no {word} with {MIN_TOUCHES}+ tests nearby"
    elif not holds:
        level_note = f"{word} lost: 4H closed {fmt(hc[i])}, {'below' if L else 'above'} {fmt(key['price'])}"
    else:
        level_note = f"{word} {fmt(key['price'])} tested {key['touches']}x, {dist:.2f}% away"
    if weak:
        level_note += f"; caution, {key['touches']} tests, level weakening"

    # 3. confirmations
    c4 = candle_info(F, i)
    confirms, conflicts = 0, 0
    if L:
        if c4.get("bull_engulf") or c4.get("hammer") or t1.get("bull_engulf") or t1.get("hammer"): confirms += 1
    else:
        if c4.get("bear_engulf") or c4.get("shooter") or t1.get("bear_engulf") or t1.get("shooter"): confirms += 1
    rwin = hRsi[-6:]
    rsi_ok = (hRsi[i] > hRsi[i - 1] and np.min(rwin) < 45) if L else (hRsi[i] < hRsi[i - 1] and np.max(rwin) > 55)
    if rsi_ok or divergence_js(F, hRsi, L): confirms += 1
    hist_ok = (hist[i] > hist[i - 1] > hist[i - 2]) if L else (hist[i] < hist[i - 1] < hist[i - 2])
    if hist_ok or crossed_within(macd, signal, 3, L): confirms += 1
    vr4, vr1 = _ratio(hv[i], hVolAvg[i]), _ratio(H["v"][j], v1Avg[j])
    if vr4 >= VOL_BREAKOUT or vr1 >= VOL_BREAKOUT: confirms += 1
    lows3, highs3 = F["l"][-3:], F["h"][-3:]
    ema_bounce = (lows3.min() <= hE50[i] * 1.005 and hc[i] > hE50[i]) if L else (highs3.max() >= hE50[i] * 0.995 and hc[i] < hE50[i])
    if ema_bounce or crossed_within(hc, hE50, 3, L): confirms += 1
    if (c4.get("bear_engulf") or c4.get("shooter")) if L else (c4.get("bull_engulf") or c4.get("hammer")): conflicts += 1
    if crossed_within(macd, signal, 2, not L): conflicts += 1
    c_confirm = confirms >= MIN_CONFIRMS and conflicts == 0

    # 4. plan and R:R: stop beyond the level by 1 ATR, target at the next level
    pall = pivots_js(F["h"], F["l"])
    ks = (1.272, 1.618, 2.0)
    if L:
        ref = key["price"] if key else (pall["lows"][-1][1] if pall["lows"] else fLo)
        stop = min(ref, price) - STOP_ATR * atr4
        tg = [x for x in above if x["price"] > price * 1.005]
        target = tg[0]["price"] if tg else next((fLo + (fHi - fLo) * k for k in ks if fLo + (fHi - fLo) * k > price * 1.005), NAN)
        target_src = "level" if tg else "fib"
        risk, reward = price - stop, target - price
    else:
        ref = key["price"] if key else (pall["highs"][-1][1] if pall["highs"] else fHi)
        stop = max(ref, price) + STOP_ATR * atr4
        tg = [x for x in below if x["price"] < price * 0.995]
        target = tg[0]["price"] if tg else next((fHi - (fHi - fLo) * k for k in ks if fHi - (fHi - fLo) * k < price * 0.995), NAN)
        target_src = "level" if tg else "fib"
        risk, reward = stop - price, price - target
    valid = risk > 0 and reward > 0
    rr = reward / risk if valid else None
    c_rr = valid and rr >= MIN_RR

    # 5. volume on the bar that matches the setup
    bo_i, bo_lv = -1, None
    for k in range(3):
        if i - k - 1 < 0: continue
        a_c, b_c = hc[i - k - 1], hc[i - k]
        hit = next((lv for lv in levels if (a_c <= lv["price"] < b_c if L else a_c >= lv["price"] > b_c)), None)
        if hit:
            bo_i, bo_lv = i - k, hit
            break
    holding_break = bo_i >= 0 and (hc[i] > bo_lv["price"] if L else hc[i] < bo_lv["price"]) and (not key or holds)
    if holding_break:
        vr = _ratio(hv[bo_i], hVolAvg[bo_i])
        c_vol = fin(vr) and vr >= VOL_BREAKOUT
        vol_note = f"breakout bar {vr:.2f}x avg"
    elif key and near:
        tol = key["price"] * TOL_PCT / 100
        b_i = -1
        for k in range(3):
            b = i - k
            touched = F["l"][b] <= key["price"] + tol if L else F["h"][b] >= key["price"] - tol
            reacted = (hc[b] > F["o"][b] and hc[b] >= key["price"]) if L else (hc[b] < F["o"][b] and hc[b] <= key["price"])
            if touched and reacted:
                b_i = b
                break
        if b_i >= 0:
            vr = _ratio(hv[b_i], hVolAvg[b_i])
            c_vol = fin(vr) and vr >= VOL_BOUNCE
            vol_note = f"bounce bar {vr:.2f}x avg"
        else:
            c_vol, vol_note = False, "no bounce bar yet"
    else:
        c_vol = vr4 >= 1.0 and hv[i] > hv[i - 1]
        vol_note = f"pullback volume {vr4:.2f}x avg"

    # 6. clean price action
    ch = chop_js(F)
    chop_state = "clean" if ch < CHOP_PASS else "neutral" if ch <= CHOP_MAX else "choppy"
    rng = F["h"][-10:] - F["l"][-10:]
    bodies = np.where(rng > 0, np.abs(hc[-10:] - F["o"][-10:]) / np.where(rng > 0, rng, 1), 0)
    clean_last = c4.get("body", 0) >= 0.5 or c4.get("hammer" if L else "shooter", False)
    c_clean = chop_state == "clean" and bodies.mean() >= 0.4 and clean_last

    checks = {"level": c_level, "confirmations": c_confirm, "rr": c_rr, "volume": c_vol, "clean": c_clean}
    passed = sum(bool(v) for v in checks.values())
    g = "A+" if passed == 5 else "B+" if passed == 4 else "C" if passed == 3 else "D"

    # RSI re-entry gate: 4H near 30 and daily near 50, off in a bear regime
    r4, rd = hRsi[i], dRsi[di]
    recent = [x for x in dRsi[-14:] if fin(x)]
    bear_env = sum(x < 40 for x in recent) >= 10
    gate = (not bear_env) and r4 <= RSI4H_TRIGGER and RSI_D_LO <= rd <= RSI_D_HI
    va = value_state(F, price, L)
    setup_ok = g in ("A+", "B+")
    va_ok = va["fit"] or not VA_GATE
    action = "actionable" if setup_ok and gate and va_ok else "wait"
    if bear_env:
        gate_note = "RSI gate off (daily under 40 most of 2 weeks)"
    elif gate:
        gate_note = "RSI gate live"
    else:
        gate_note = f"RSI gate closed: 4H needs {RSI4H_TRIGGER} or lower, daily {RSI_D_LO}-{RSI_D_HI}"
    if VA_GATE and setup_ok and gate and not va["fit"]:
        gate_note += "; value-area gate closed"

    return {"side": side, "grade": g, "passed": passed, "scored": 5, "checks": checks,
            "action": action, "gate_note": gate_note, "trend_ok": trend_ok,
            "level_note": level_note, "vol_note": vol_note, "chop": ch, "chop_state": chop_state,
            "entry": price, "stop": stop if valid else None, "target": target if valid else None, "rr": rr,
            "rsi4h": r4, "rsid": rd, "va": va, "target_src": target_src if valid else None,
            "from_t": int(H["t"][-1]) + 3600}


# ---------- breakout scanner (momentum moves the pullback grader misses) ----------
def breakout(d, h4):
    """Closed 4H bar through the BO_LOOKBACK range on volume, with the daily EMA50 behind it.
    RSI is capped at BO_RSI_MAX (was 75): real breakouts often print RSI 75-85 on the bar itself."""
    last = h4.iloc[-1]
    prior = h4.iloc[-BO_LOOKBACK-1:-1]
    vol_ok = last.v > BO_VOL_MULT * prior.v.mean()
    r = rsi(h4.c).iloc[-1]
    e50d = ema(d.c, 50).iloc[-1]
    if last.c > prior.h.max() and vol_ok and last.c > e50d and 55 <= r <= BO_RSI_MAX:
        return "long", prior.h.max(), r, last.v / prior.v.mean()
    if last.c < prior.l.min() and vol_ok and last.c < e50d and 100 - BO_RSI_MAX <= r <= 45:
        return "short", prior.l.min(), r, last.v / prior.v.mean()
    return None


def breakout_plan(side, lvl, h4):
    """Entry at the 4H close, stop BO_STOP_ATR x 4H ATR back inside the broken level, TP at BO_TARGET_R."""
    d = 1 if side == "long" else -1
    entry = float(h4.c.iloc[-1])
    a = float(atr(h4).iloc[-1])
    stop = lvl - d * BO_STOP_ATR * a
    if (entry - stop) * d <= 0:
        return None
    return {"entry": entry, "stop": stop, "target": entry + d * BO_TARGET_R * abs(entry - stop),
            "from_t": int(h4.t.iloc[-1]) + 4 * 3600}


def impulse(h1, h4):
    """One outsized closed 1H bar that breaks the IMP_LOOKBACK-bar range on heavy volume.
    Catches vertical moves the 4H breakout scanner only sees after the 4H bar closes and the
    momentum-shift scanner never sees (it only fires against the 4H trend)."""
    if len(h1) < IMP_LOOKBACK + 20:
        return None
    last = h1.iloc[-1]
    prior = h1.iloc[-IMP_LOOKBACK-1:-1]
    a1 = float(atr(h1).iloc[-2])              # ATR before the bar, so the bar can't inflate its own yardstick
    rng = last.h - last.l
    avg_v = prior.v.tail(20).mean()
    if rng <= 0 or a1 <= 0 or avg_v <= 0:
        return None
    size_x, vol_x = rng / a1, last.v / avg_v
    pos = (last.c - last.l) / rng             # 0 = closed at the low, 1 = at the high
    if size_x < IMP_ATR_MULT or vol_x < IMP_VOL_MULT:
        return None
    if last.c > last.o and pos >= IMP_CLOSE_POS and last.c > prior.h.max():
        side, d, lvl = "long", 1, prior.h.max()
    elif last.c < last.o and pos <= 1 - IMP_CLOSE_POS and last.c < prior.l.min():
        side, d, lvl = "short", -1, prior.l.min()
    else:
        return None
    entry = float(last.c)
    a4 = float(atr(h4).iloc[-1])
    # stop for the FULL scaled position sits beyond the broken level, so a normal retest
    # can't take out the starter before the add is due
    stop = lvl - d * IMP_STOP_ATR * a4
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    ext = abs(entry - lvl) / a4 if a4 > 0 else 0.0
    return {"side": side, "level": float(lvl), "entry": entry, "stop": float(stop),
            "target": entry + d * IMP_TARGET_R * risk, "size_x": size_x, "vol_x": vol_x,
            "ext": ext, "rsi4h": float(rsi(h4.c).iloc[-1]), "bar": int(last.t),
            "from_t": int(last.t) + 3600}

# ---------- order blocks (info only) ----------
def order_blocks(h4):
    """Live 4H order blocks. Bullish: last red candle before a green displacement candle that
    closed above it (demand). Bearish: mirror (supply). A zone dies on a 4H close through its
    far side, or once price has come back to it more than OB_MAX_TESTS separate times. A test
    is one visit: consecutive bars sitting in the zone count once."""
    n = len(h4)
    if n < 40:
        return []
    o, h, l, c, t = (h4[k].to_numpy(float) for k in ("o", "h", "l", "c", "t"))
    a = atr(h4).to_numpy(float)
    out, used = [], set()
    for i in range(max(OB_SEARCH + 1, n - OB_LOOKBACK), n):
        body = c[i] - o[i]
        if not fin(a[i - 1]) or abs(body) < OB_DISP_ATR * a[i - 1]:
            continue
        bull = body > 0
        j = next((k for k in range(i - 1, max(i - 1 - OB_SEARCH, -1), -1)
                  if (c[k] < o[k] if bull else c[k] > o[k])), None)
        if j is None or j in used:
            continue
        lo, hi = l[j], h[j]
        if (bull and c[i] <= hi) or (not bull and c[i] >= lo):
            continue                              # displacement never cleared the candle
        used.add(j)
        broken, tests, was_in = False, 0, False
        for k in range(i + 1, n):
            if (bull and c[k] < lo) or (not bull and c[k] > hi):
                broken = True; break
            now_in = (bull and l[k] <= hi) or (not bull and h[k] >= lo)
            if now_in and not was_in:
                tests += 1                        # a new visit, not another bar of the same one
            was_in = now_in
        if broken or tests > OB_MAX_TESTS:
            continue
        out.append({"side": "bull" if bull else "bear", "lo": float(lo), "hi": float(hi),
                    "t": int(t[j]), "touches": tests,
                    "status": "fresh" if tests == 0 else f"tested {tests}x"})
    return out


def ob_info(obs, side, entry, target, a4):
    """Order-block context for a trade: (tag for outcomes, text for the push)."""
    if not obs or not fin(a4) or a4 <= 0:
        return "none", "OB: none live nearby"
    L = side == "long"
    with_side = "bull" if L else "bear"
    tol = OB_TOL_ATR * a4
    inside = [z for z in obs if z["lo"] - tol <= entry <= z["hi"] + tol]
    inside_with = [z for z in inside if z["side"] == with_side]
    inside_against = [z for z in inside if z["side"] != with_side]
    blocking = []
    if target is not None and fin(target):
        lo_p, hi_p = (entry, target) if L else (target, entry)
        blocking = [z for z in obs if z["side"] != with_side and z not in inside
                    and z["lo"] < hi_p and z["hi"] > lo_p]
        blocking.sort(key=lambda z: abs((z["lo"] if L else z["hi"]) - entry))
    behind = [z for z in obs if z["side"] == with_side and z not in inside
              and ((0 <= entry - z["hi"] <= OB_NEAR_ATR * a4) if L
                   else (0 <= z["lo"] - entry <= OB_NEAR_ATR * a4))]

    def zt(z):
        word = "bullish" if z["side"] == "bull" else "bearish"
        return f"{word} OB {fmt(z['lo'])}-{fmt(z['hi'])} ({z['status']})"

    parts = []
    if inside_against:
        tag = "in-against"; parts.append("🟥 entry inside " + zt(inside_against[0]))
    elif inside_with:
        tag = "in-with"; parts.append("🟩 entry inside " + zt(inside_with[0]))
    elif blocking:
        tag = "blocked"
    elif behind:
        tag = "near-with"
    else:
        tag = "none"
    if blocking:
        parts.append("🟥 " + zt(blocking[0]) + " before target")
    if behind and not inside_with:
        parts.append("🟩 " + zt(behind[0]) + " behind entry")
    return tag, "OB: " + (" | ".join(parts) if parts else "none live nearby")

# ---------- money flow + divergence helpers ----------
def mfi(df, n=14):
    """Money Flow Index — volume-weighted RSI."""
    tp = (df.h + df.l + df.c) / 3
    raw = tp * df.v
    pos = raw.where(tp > tp.shift(), 0.0)
    neg = raw.where(tp < tp.shift(), 0.0)
    return 100 - 100 / (1 + pos.rolling(n).sum() / neg.rolling(n).sum().replace(0, 1e-9))

def cmf(df, n=20):
    """Chaikin Money Flow — accumulation above zero, distribution below."""
    rng = (df.h - df.l).replace(0, 1e-9)
    mfm = ((df.c - df.l) - (df.h - df.c)) / rng
    return (mfm * df.v).rolling(n).sum() / df.v.rolling(n).sum()

def obv(df):
    step = (df.c.diff() > 0).astype(int) - (df.c.diff() < 0).astype(int)
    return (step * df.v).cumsum()

def flow_state(h4):
    """Money flow on the last closed bar: direction (CMF, OBV) and intensity (volume vs avg).
    Called with 4H bars for most alerts, and with 1H bars for impulse alerts so the Flow line
    reflects the breakout bar instead of the 4H bar that closed before it."""
    unknown = {"label": "unknown", "dir": 0, "heavy": False, "text": "not enough bar data"}
    if len(h4) < 40 or h4.v.iloc[-21:].sum() <= 0:
        return unknown                        # e.g. a futures feed with no volume
    cf = cmf(h4)
    now_c, then_c = cf.iloc[-1], cf.iloc[-1 - FLOW_SLOPE_BARS]
    if not fin(now_c):
        return unknown
    ob = obv(h4)
    obv_up = ob.iloc[-1] > ema(ob, 21).iloc[-1]
    last = h4.iloc[-1]
    avg = h4.v.iloc[-21:-1].mean()
    vx = last.v / avg if avg > 0 else NAN
    rng = last.h - last.l
    bar_mf = ((last.c - last.l) - (last.h - last.c)) / rng if rng > 0 else 0.0  # +1 closed at high

    d = 1 if now_c >= FLOW_CMF_MIN else -1 if now_c <= -FLOW_CMF_MIN else 0
    heavy = (d != 0 and fin(vx) and vx >= FLOW_VOL_MULT
             and (bar_mf > 0 if d == 1 else bar_mf < 0))
    word = "inflow" if d == 1 else "outflow" if d == -1 else "neutral"
    label = f"heavy {word}" if heavy else word
    trend = ("rising" if now_c > then_c else "falling" if now_c < then_c else "flat") \
        if fin(then_c) else "-"
    dot = "\U0001F7E2" if d == 1 else "\U0001F534" if d == -1 else "\u26AA"
    vtxt = f"{vx:.1f}x" if fin(vx) else "-"
    text = (f"{dot} {label.upper()} | CMF {now_c:+.2f} ({trend}) | "
            f"OBV {'above' if obv_up else 'below'} EMA | vol {vtxt} avg")
    return {"label": label, "dir": d, "heavy": heavy, "cmf": now_c, "trend": trend,
            "obv_up": obv_up, "vx": vx, "text": text}

def flow_line(fl, side=None, tf=None):
    """Flow text for a push, plus whether the money agrees with the trade side."""
    txt = fl["text"]
    if side and fl["dir"] != 0:
        txt += " | with you" if (fl["dir"] == 1) == (side == "long") else " | AGAINST you"
    return (f"Flow ({tf}): " if tf else "Flow: ") + txt

def swing_idx(series, k=2):
    """Indices of pivot lows and highs in a series."""
    v = series.values
    lows, highs = [], []
    for i in range(k, len(v) - k):
        w = v[i-k:i+k+1]
        if v[i] == w.min(): lows.append(i)
        if v[i] == w.max(): highs.append(i)
    return lows, highs

def divergence(df, look=60, k=2):
    """Regular RSI divergence across the last two swings. Returns (bullish, bearish)."""
    sub = df.iloc[-look:].reset_index(drop=True)
    if len(sub) < 20:
        return False, False
    r = rsi(sub.c)
    lows = swing_idx(sub.l, k)[0]
    highs = swing_idx(sub.h, k)[1]
    bull = bear = False
    if len(lows) >= 2:
        a, b = lows[-2], lows[-1]
        bull = sub.l[b] < sub.l[a] and r[b] > r[a]      # lower low in price, higher low in RSI
    if len(highs) >= 2:
        a, b = highs[-2], highs[-1]
        bear = sub.h[b] > sub.h[a] and r[b] < r[a]      # higher high in price, lower high in RSI
    return bull, bear

# ---------- momentum shift (lower timeframes lead, 4H about to follow) ----------
def ltf_dir(df):
    """Momentum direction on a lower timeframe: EMA9/21 plus RSI either side of 50."""
    e9, e21 = ema(df.c, 9), ema(df.c, 21)
    r = rsi(df.c).iloc[-1]
    if e9.iloc[-1] > e21.iloc[-1] and r > 50: return 1
    if e9.iloc[-1] < e21.iloc[-1] and r < 50: return -1
    return 0

def bars_to_cross(h4):
    """Extrapolate how many 4H bars until the 9/21 EMA spread crosses zero."""
    spread = ema(h4.c, 9) - ema(h4.c, 21)
    now, step = spread.iloc[-1], spread.iloc[-1] - spread.iloc[-2]
    if step == 0:
        return None
    if (now > 0) == (step > 0):
        return None                 # spread is widening, no cross coming
    return abs(now / step)

def momentum_shift(h4, m15, m5):
    """Fires when 5m and 15m have flipped against the 4H trend and the 4H is about to follow."""
    d15, d5 = ltf_dir(m15), ltf_dir(m5)
    if d15 == 0 or d15 != d5:
        return None                 # both lower timeframes must agree
    d = d15
    e9, e21 = ema(h4.c, 9), ema(h4.c, 21)
    if (1 if e9.iloc[-1] > e21.iloc[-1] else -1) == d:
        return None                 # 4H already points this way, so there is no shift to catch

    eta = bars_to_cross(h4)
    macd = ema(h4.c, 12) - ema(h4.c, 26)
    hist = macd - ema(macd, 9)
    bull_div, bear_div = divergence(h4)
    mf = mfi(h4)
    cf = cmf(h4).iloc[-1]
    ob, ob_ema = obv(h4), ema(obv(h4), 21)
    r4 = rsi(h4.c).iloc[-1]
    a = atr(h4).iloc[-1]
    last = h4.iloc[-1]

    f = {
        "5m+15m flip": True,
        "4H cross due": eta is not None and eta <= MS_MAX_BARS,
        "Histogram turning": (hist.iloc[-1] > hist.iloc[-2] > hist.iloc[-3]) if d == 1
                             else (hist.iloc[-1] < hist.iloc[-2] < hist.iloc[-3]),
        "Divergence": bull_div if d == 1 else bear_div,
        "MFI": (mf.iloc[-1] > mf.iloc[-4] and mf.iloc[-1] > 40) if d == 1
               else (mf.iloc[-1] < mf.iloc[-4] and mf.iloc[-1] < 60),
        "CMF": cf > 0 if d == 1 else cf < 0,
        "OBV": ob.iloc[-1] > ob_ema.iloc[-1] if d == 1 else ob.iloc[-1] < ob_ema.iloc[-1],
    }
    entry = last.c
    stop = entry - MS_ATR_MULT * a * d
    return {"side": "long" if d == 1 else "short", "score": sum(f.values()), "factors": f,
            "entry": entry, "stop": stop,
            "tps": [entry + k * MS_ATR_MULT * a * d for k in (1, 2, 3)],
            "eta": eta, "rsi4h": r4, "mfi": mf.iloc[-1], "cmf": cf,
            "div": bull_div if d == 1 else bear_div, "bar": int(last.t),
            "from_t": int(last.t) + 4 * 3600}


# ---------- perp funding (Kraken Futures, public) ----------
FUND_URL = "https://futures.kraken.com/derivatives/api/v3/historical-funding-rates"
FUND_ALIASES = {"XBT": ["XBT", "BTC"], "XDG": ["XDG", "DOGE"], "SHIB": ["SHIB", "1000SHIB"]}
_fund_cache = {}


def funding_history(coin, pair):
    """Hourly relative funding rates for the coin's Kraken perp, or None (metals, no perp,
    or the request failed). Columns: t (unix), rel (fraction per funding period)."""
    if pair.startswith("yf:"):
        return None
    if pair in _fund_cache:
        return _fund_cache[pair]
    base = pair[:-3] if pair.endswith("USD") else pair
    names = FUND_ALIASES.get(base, [base])
    out = None
    for b in names:
        try:
            r = requests.get(FUND_URL, params={"symbol": f"PF_{b}USD"}, timeout=20)
            rates = (r.json() or {}).get("rates") or []
            if not rates:
                continue
            df = pd.DataFrame(rates)
            if "relativeFundingRate" not in df or "timestamp" not in df:
                continue
            df["t"] = pd.to_datetime(df["timestamp"], utc=True).map(lambda x: int(x.timestamp()))
            df["rel"] = pd.to_numeric(df["relativeFundingRate"], errors="coerce")
            out = df[["t", "rel"]].dropna().sort_values("t").reset_index(drop=True)
            if len(out) >= 2:
                break
            out = None
        except Exception:
            continue
    _fund_cache[pair] = out
    return out


def funding_apr(df, T):
    """Annualized funding in % at time T (positive = longs pay shorts). None if unknown."""
    if df is None:
        return None
    sub = df[df.t <= T]
    if len(sub) < 2:
        return None
    period = sub.t.iloc[-1] - sub.t.iloc[-2]
    if period <= 0:
        return None
    apr = float(sub.rel.iloc[-1]) * (365 * 86400 / period) * 100
    if not fin(apr) or abs(apr) > 2000:          # sanity guard against a units surprise
        return None
    return apr


# ---------- trend-pullback engine ----------
def adx(df, n=14):
    """Wilder ADX on the last bar (same formula as papertrade.py)."""
    h, l, c = (df[k].to_numpy(float) for k in ("h", "l", "c"))
    if len(c) < 2 * n + 2:
        return NAN
    up = np.diff(h, prepend=np.nan)
    dn = -np.diff(l, prepend=np.nan)
    plus = np.where((up > dn) & (up > 0), up, 0.0)
    minus = np.where((dn > up) & (dn > 0), dn, 0.0)
    pc = np.concatenate(([np.nan], c[:-1]))
    tr = np.nanmax(np.vstack([h - l, np.abs(h - pc), np.abs(l - pc)]), axis=0)
    a = 1 / n
    atr_ = pd.Series(tr).ewm(alpha=a, adjust=False).mean()
    pdi = 100 * pd.Series(plus).ewm(alpha=a, adjust=False).mean() / atr_
    mdi = 100 * pd.Series(minus).ewm(alpha=a, adjust=False).mean() / atr_
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return float(dx.ewm(alpha=a, adjust=False).mean().iloc[-1])


def daily_trend(d):
    """+1 uptrend, -1 downtrend, 0 none. Close beyond the 50 EMA, 20 EMA beyond the 50,
    and the 50 sloping the same way over D_SLOPE_BARS days."""
    if len(d) < 60:
        return 0
    c = d.c
    e20, e50 = ema(c, 20), ema(c, 50)
    cn, f, s, s_old = c.iloc[-1], e20.iloc[-1], e50.iloc[-1], e50.iloc[-1 - D_SLOPE_BARS]
    if cn > s and f > s and s > s_old:
        return 1
    if cn < s and f < s and s < s_old:
        return -1
    return 0


def _retest(h, l, c, a, i, L):
    """Most recent 20-bar range break in the trend direction within RETEST_WITHIN bars,
    held on closes since and revisited. Returns (level, swing extreme since the break) or None."""
    for j in range(i - 1, max(i - RETEST_WITHIN, RETEST_RANGE) - 1, -1):
        lvl = h[j - RETEST_RANGE:j].max() if L else l[j - RETEST_RANGE:j].min()
        broke = c[j] > lvl if L else c[j] < lvl
        if not broke:
            continue
        after = slice(j + 1, i + 1)
        held = (c[after] >= lvl - 0.5 * a[i]).all() if L else (c[after] <= lvl + 0.5 * a[i]).all()
        touched = (l[after].min() <= lvl + PB_TOUCH_ATR * a[i]) if L \
            else (h[after].max() >= lvl - PB_TOUCH_ATR * a[i])
        if held and touched:
            return lvl, (l[after].min() if L else h[after].max())
        return None
    return None


def trend_setup(d, h4, fund=None):
    """Evaluate the trend-pullback setup on the last closed 4H bar.

    Returns None when there is no trend/stack/clean market, else a dict with status:
      "veto"  - in a pullback with a trigger, but a veto rule failed (reason in "why")
      "watch" - in the pullback zone, no trigger yet
      "entry" - all rules pass; entry/stop/tp1 filled in
    """
    if len(h4) < 80 or len(d) < 60:
        return None
    s = daily_trend(d)
    if s == 0:
        return None
    L = s == 1
    side = "long" if L else "short"
    o, h, l, c = (h4[k].to_numpy(float) for k in ("o", "h", "l", "c"))
    e20 = ema(h4.c, 20).to_numpy()
    e50 = ema(h4.c, 50).to_numpy()
    a = atr(h4).to_numpy()
    i = len(c) - 1
    A = a[i]
    if not fin(A) or A <= 0 or (e20[i] - e50[i]) * s <= 0:
        return None                                       # 4H not stacked with the daily
    ch = chop_js(_cols(h4))
    ax = adx(h4)
    if not (fin(ch) and fin(ax)) or ch > CHOP_GATE or ax < ADX_MIN:
        return None                                       # choppy or no 4H trend strength

    win = range(i - PB_BARS, i + 1)
    if any((c[k] < e50[k] - PB_FLOOR_ATR * a[k]) if L else (c[k] > e50[k] + PB_FLOOR_ATR * a[k])
           for k in win):
        return None                                       # pullback broke the trend
    touch_ema = any((l[k] <= e20[k] + PB_TOUCH_ATR * a[k]) if L else (h[k] >= e20[k] - PB_TOUCH_ATR * a[k])
                    for k in win)
    rt = None if touch_ema else _retest(h, l, c, a, i, L)
    if not touch_ema and not rt:
        return None
    if touch_ema:
        zone, zone_txt, ref = "20ema", "4H 20 EMA", float(e20[i])
        swing = l[win.start:i + 1].min() if L else h[win.start:i + 1].max()
    else:
        zone, zone_txt, ref = "retest", f"retest of broken level {fmt(rt[0])}", float(rt[0])
        swing = rt[1]

    base = {"side": side, "zone": zone, "zone_txt": zone_txt, "adx": ax, "chop": ch,
            "atr": float(A), "bar": int(h4.t.iloc[-1]), "from_t": int(h4.t.iloc[-1]) + 4 * 3600,
            "ref": ref, "swing": float(swing), "fund": fund}

    rng = h[i] - l[i]
    pos = (c[i] - l[i]) / rng if rng > 0 else 0.5
    trig = (c[i] > o[i] and pos >= 0.5 and c[i] > h[i - 1] and c[i] > e20[i]) if L \
        else (c[i] < o[i] and pos <= 0.5 and c[i] < l[i - 1] and c[i] < e20[i])
    stop_est = swing - s * STOP_BUF_ATR * A
    if not trig:
        trig_px = max(h[i], e20[i]) if L else min(l[i], e20[i])
        return {**base, "status": "watch", "trigger": float(trig_px), "stop_est": float(stop_est)}

    entry = float(c[i])
    ext = (entry - ref) * s / A                           # distance from the zone it bounced off
    rsi4 = float(rsi(h4.c).iloc[-1])
    stop = stop_est
    if (entry - stop) * s < MIN_STOP_ATR * A:
        stop = entry - s * MIN_STOP_ATR * A
    risk = (entry - stop) * s
    base.update({"entry": entry, "stop": float(stop), "risk": float(risk), "ext": ext, "rsi4h": rsi4,
                 "tp1": entry + s * TP1_R * risk})

    why = None
    if ext > MAX_EXT_ATR:
        why = f"extended {ext:.1f} ATR past the {'20 EMA' if zone == '20ema' else 'retest level'}"
    elif risk > MAX_STOP_ATR * A:
        why = f"structure stop {risk / A:.1f} ATR away (max {MAX_STOP_ATR:g})"
    elif (rsi4 > RSI_HOT) if L else (rsi4 < 100 - RSI_HOT):
        why = f"4H RSI {rsi4:.0f} overheated"
    else:
        fl = flow_state(h4)
        base["flow"] = fl
        if fl["heavy"] and fl["dir"] == s:
            why = "heavy money flow already with the trade (late entry)"
        elif fund is not None and fund * s >= FUND_MAX_APR:
            why = f"funding {fund:+.0f}%/yr, {side}s crowded"
    if why:
        return {**base, "status": "veto", "why": why}
    return {**base, "status": "entry"}


def manage(tr, bars, step, now=None, mode="plan", fee_bps=0.0, slip_bps=0.0):
    """Replay closed bars after entry with the trade plan. Stop is checked first in every bar
    (a stop and target in the same bar counts as the stop); the trail is raised after the bar
    closes, so it applies from the next bar.

    mode: plan (half at TP1_R, stop to entry, trail rest), fixed2R (all at 2R, no trail),
          trail_only (no partial, trail everything).
    Returns {done, outcome, r, mfe_r, mae_r, end_t, half, stop}. done=False while open."""
    L = tr["side"] == "long"
    s = 1 if L else -1
    slip, fee = slip_bps / 1e4, fee_bps / 1e4
    entry = tr["entry"] * (1 + s * slip)
    stop = tr["stop"]
    risk = (entry - stop) * s
    A = tr["atr"]
    if risk <= 0:
        return {"done": True, "outcome": "invalid", "r": 0.0, "mfe_r": 0.0, "mae_r": 0.0,
                "end_t": tr["from_t"], "half": False, "stop": stop}
    tp1 = entry + s * TP1_R * risk
    tgt2 = entry + s * 2.0 * risk
    q, realized, half, best, mfe, mae = 1.0, 0.0, False, entry, 0.0, 0.0
    outcome, end_t = None, None
    for b in bars[bars.t >= tr["from_t"]].itertuples():
        mfe = max(mfe, ((b.h - entry) if L else (entry - b.l)) / risk)
        mae = max(mae, ((entry - b.l) if L else (b.h - entry)) / risk)
        if (b.l <= stop) if L else (b.h >= stop):
            px = stop * (1 - s * slip)
            realized += q * (px - entry) * s / risk
            q, end_t = 0.0, b.t + step
            outcome = "stop"
            break
        if mode == "fixed2R":
            if (b.h >= tgt2) if L else (b.l <= tgt2):
                realized += q * 2.0
                q, end_t, outcome = 0.0, b.t + step, "target"
                break
        else:
            if mode == "plan" and not half and ((b.h >= tp1) if L else (b.l <= tp1)):
                realized += 0.5 * TP1_R
                q, half = 0.5, True
                stop = max(stop, entry) if L else min(stop, entry)
                if (b.l <= entry) if L else (b.h >= entry):      # same bar came back to entry
                    realized += q * (entry * (1 - s * slip) - entry) * s / risk
                    q, end_t, outcome = 0.0, b.t + step, "stop"
                    break
            best = max(best, b.h) if L else min(best, b.l)
            trail = best - s * TRAIL_ATR * A
            stop = max(stop, trail) if L else min(stop, trail)
        if b.t + step - tr["from_t"] >= MAX_HOLD_HRS * 3600:
            realized += q * (b.c * (1 - s * slip) - entry) * s / risk
            q, end_t, outcome = 0.0, b.t + step, "time"
            break
    if outcome is None:
        return {"done": False, "outcome": None, "r": realized, "mfe_r": mfe, "mae_r": mae,
                "end_t": None, "half": half, "stop": stop}
    realized -= 2 * fee * entry / risk                        # entry + exit fees, in R
    label = "win" if realized > 0.05 else "loss" if realized < -0.05 else "breakeven"
    return {"done": True, "outcome": label, "exit": outcome, "r": realized, "mfe_r": mfe,
            "mae_r": mae, "end_t": int(end_t), "half": half, "stop": stop}


# ---------- outcome tracking ----------
OUT_COLS = ["alert_utc", "resolved_utc", "coin", "kind", "side", "grade", "va_state", "va_fit",
            "target_src", "entry", "stop", "target", "outcome", "r", "mfe_r", "mae_r", "hours",
            "flow", "ob"]


def open_trade(state, coin, kind, side, grade_, entry, stop, target, from_t, now,
               va_state="", va_fit="", target_src="", flow="", ob="", **extra):
    """Start tracking an alert. One open trade per coin and kind; skip if no stop/target."""
    if stop is None or target is None or not all(fin(x) for x in (entry, stop, target)):
        return
    if abs(entry - stop) <= 0:
        return
    trades = state.setdefault("open", [])
    if any(t["coin"] == coin and t["kind"] == kind for t in trades):
        return
    trades.append({"coin": coin, "kind": kind, "side": side, "grade": grade_,
                   "entry": float(entry), "stop": float(stop), "target": float(target),
                   "t": now, "from_t": int(from_t), "va_state": va_state,
                   "va_fit": va_fit, "target_src": target_src or "", "flow": flow or "",
                   "ob": ob or "", **extra})


def walk_trade(tr, h1, now):
    """Legacy trades: replay closed 1H bars to a fixed stop or target."""
    L = tr["side"] == "long"
    entry, stop, target = tr["entry"], tr["stop"], tr["target"]
    risk = abs(entry - stop)
    bars = h1[h1.t >= tr["from_t"]]
    mfe = mae = 0.0
    outcome, r, end_t = None, None, None
    for b in bars.itertuples():
        mfe = max(mfe, ((b.h - entry) if L else (entry - b.l)) / risk)
        mae = max(mae, ((entry - b.l) if L else (b.h - entry)) / risk)
        hit_stop = b.l <= stop if L else b.h >= stop
        hit_tgt = b.h >= target if L else b.l <= target
        if hit_stop:
            outcome, r, end_t = ("both" if hit_tgt else "loss"), -1.0, b.t + 3600
            break
        if hit_tgt:
            outcome, r, end_t = "win", abs(target - entry) / risk, b.t + 3600
            break
    if outcome is None:
        if now - tr["t"] < MAX_HOLD_HRS * 3600:
            return None
        last = bars.c.iloc[-1] if len(bars) else entry
        outcome, end_t = "expired", now
        r = ((last - entry) if L else (entry - last)) / risk
    return [stamp(tr["t"]), stamp(end_t), tr["coin"], tr["kind"], tr["side"], tr["grade"],
            tr.get("va_state", ""), tr.get("va_fit", ""), tr.get("target_src", ""),
            tr["entry"], tr["stop"], tr["target"], outcome, round(r, 3),
            round(mfe, 3), round(mae, 3), round((end_t - tr["t"]) / 3600, 1), tr.get("flow", ""),
            tr.get("ob", "")]


def trend_row(tr, res):
    return [stamp(tr["t"]), stamp(res["end_t"]), tr["coin"], tr["kind"], tr["side"], tr["grade"],
            tr.get("va_state", ""), tr.get("va_fit", ""), tr.get("target_src", ""),
            tr["entry"], tr["stop"], tr["target"], res["outcome"], round(res["r"], 3),
            round(res["mfe_r"], 3), round(res["mae_r"], 3),
            round((res["end_t"] - tr["t"]) / 3600, 1), tr.get("flow", ""), tr.get("ob", "")]


def resolve_trades(state, coin, h1, now):
    """Resolve this coin's open trades. Trend trades also produce management pushes
    (TP1 hit, trailing-stop moves, close). Returns (rows, messages, changed)."""
    rows, msgs, keep, changed = [], [], [], False
    for tr in state.get("open", []):
        if tr["coin"] != coin:
            keep.append(tr); continue
        if tr["kind"] != "trend":
            row = walk_trade(tr, h1, now)
            if row:
                rows.append(row); changed = True
            else:
                keep.append(tr)
            continue
        res = manage(tr, h1, 3600, now)
        L = tr["side"] == "long"
        s = 1 if L else -1
        side, A, risk = tr["side"].upper(), tr["atr"], abs(tr["entry"] - tr["stop"])
        loud = tr.get("pushed", False)
        if res["done"]:
            rows.append(trend_row(tr, res)); changed = True
            how = {"stop": "stop/trail", "time": "max hold", "target": "target"}.get(res.get("exit"), "")
            if loud:
                msgs.append(f"🏁 TREND CLOSED: {coin} {side}\n"
                            f"{res['outcome']} {res['r']:+.2f}R via {how} "
                            f"(best {res['mfe_r']:.1f}R)")
            continue
        if res["half"] and not tr.get("tp1_sent"):
            tr["tp1_sent"], tr["trail_sent"], changed = True, res["stop"], True
            if loud:
                msgs.append(f"🎯 TP1 HIT: {coin} {side}\n"
                            f"Close half at {fmt(tr['target'])}; move SL to entry {fmt(tr['entry'])}\n"
                            f"Runner trails {TRAIL_ATR:g}×ATR; SL now {fmt(res['stop'])}")
        last = tr.get("trail_sent", tr["stop"])
        if (res["stop"] - last) * s >= TRAIL_PUSH_ATR * A:
            lock = (res["stop"] - tr["entry"]) * s / risk
            tr["trail_sent"], changed = res["stop"], True
            if loud:
                msgs.append(f"{'⬆️' if L else '⬇️'} MOVE SL: {coin} {side} runner\n"
                            f"New SL {fmt(res['stop'])} (was {fmt(last)}) | locks {lock:+.1f}R")
        keep.append(tr)
    if changed:
        state["open"] = keep
    return rows, msgs, changed


def expire_orphans(state, now):
    """Close trades for coins no longer on the watchlist once they pass the hold limit."""
    rows, keep = [], []
    for tr in state.get("open", []):
        if tr["coin"] not in WATCHLIST and now - tr["t"] > MAX_HOLD_HRS * 3600:
            rows.append([stamp(tr["t"]), stamp(now), tr["coin"], tr["kind"], tr["side"], tr["grade"],
                         tr.get("va_state", ""), tr.get("va_fit", ""), tr.get("target_src", ""),
                         tr["entry"], tr["stop"], tr["target"], "dropped", 0.0, 0.0, 0.0,
                         round((now - tr["t"]) / 3600, 1), tr.get("flow", ""),
                         tr.get("ob", "")])
        else:
            keep.append(tr)
    if rows:
        state["open"] = keep
    return rows


def summarize(n_open=0):
    """Win rate and expectancy by alert kind and tags. Trend rows are the v3 engine."""
    if not OUT_FILE.exists():
        return "No resolved alerts yet."
    df = pd.read_csv(OUT_FILE)
    df = df[df.outcome != "dropped"].copy()
    for col in ("flow", "ob"):
        if col not in df:
            df[col] = ""
    for col in ("grade", "va_state", "va_fit", "target_src", "flow", "ob"):
        df[col] = df[col].fillna("-").astype(str)
    if df.empty:
        return "No resolved alerts yet."
    df["engine"] = np.where(df.kind == "trend", "v3 trend", "legacy")

    def flow_vs(r):
        f = r.flow
        if f in ("-", "", "nan", "unknown"): return "-"
        if "neutral" in f: return "neutral"
        w = "with" if ("inflow" in f) == (r.side == "long") else "against"
        return ("heavy " if f.startswith("heavy") else "") + w
    df["flow_vs"] = df.apply(flow_vs, axis=1)

    def table(by, sub=None):
        x0 = df if sub is None else sub
        if x0.empty:
            return "_none yet_"
        g = x0.groupby(by, dropna=False)
        rows = [f"| {' / '.join(by)} | n | win % | avg R | total R | avg MFE R |",
                "|---|---|---|---|---|---|"]
        for k, x in g:
            k = " / ".join(str(v) for v in (k if isinstance(k, tuple) else (k,)))
            rows.append(f"| {k} | {len(x)} | {100 * (x.outcome == 'win').mean():.0f} | "
                        f"{x.r.mean():+.2f} | {x.r.sum():+.1f} | {x.mfe_r.mean():.2f} |")
        return "\n".join(rows)

    tr = df[df.kind == "trend"]
    parts = [f"# Alert outcomes\n\n{len(df)} resolved, {n_open} still open. "
             f"Updated {stamp(time.time())} UTC.\n",
             "Small samples mean little; wait for 30+ per row before changing rules. "
             "R is gross (no fees).\n",
             "## By engine\n\n" + table(["engine"]),
             "## v3 trend: by side and zone\n\n" + table(["side", "grade"], tr),
             "## v3 trend: by order block\n\n" + table(["ob"], tr),
             "## v3 trend: by value-area state\n\n" + table(["va_state"], tr),
             "## v3 trend: by money flow vs trade side\n\n" + table(["flow_vs"], tr),
             "## Legacy alerts (frozen)\n\n" + table(["kind", "grade"], df[df.kind != "trend"])]
    return "\n\n".join(parts) + "\n"


def report():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    text = summarize(len(state.get("open", [])))
    print(text)
    write_step_summary(text)


def write_step_summary(text):
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(text)

# ---------- alerts ----------
def send(msg, urgent=False):
    if not NTFY_TOPIC:
        print("[no NTFY_TOPIC set]\n" + msg); return
    requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=msg.encode("utf-8"),
                  headers={"Title": "Setup Grader",
                           "Priority": "high" if urgent else "default"},
                  timeout=20)

def notify(msg, urgent=False, push=True):
    """Push to the phone, or just print when this alert is muted."""
    if push:
        send(msg, urgent=urgent)
    else:
        print("[muted] " + msg.splitlines()[0])


def fmt(p):
    if p is None: return "–"
    return f"{p:,.2f}" if p >= 1 else f"{p:.5f}"

def stamp(now):
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))

def local_time(ts, day=True):
    """Unix time as a short local clock time for alerts, e.g. 'Sun 9:00 AM PDT'."""
    dt = datetime.fromtimestamp(ts, timezone.utc).astimezone(LOCAL_TZ)
    return dt.strftime("%a %-I:%M %p %Z" if day else "%-I:%M %p")


def fund_txt(apr):
    if apr is None:
        return "Funding: n/a"
    if abs(apr) < 1:
        return f"Funding: {apr:+.1f}%/yr (neutral)"
    return f"Funding: {apr:+.0f}%/yr ({'longs' if apr > 0 else 'shorts'} pay)"


def trend_msg(coin, s, fl, ob_txt, va, muted_note=""):
    L = s["side"] == "long"
    A, risk = s["atr"], s["risk"]
    lines = [f"{'🟢📈' if L else '🔴📉'} TREND {s['side'].upper()}: {coin}{muted_note}",
             f"Pullback to {s['zone_txt']}, 4H reclaim closed {fmt(s['entry'])}",
             f"Order: Entry {fmt(s['entry'])} | SL {fmt(s['stop'])} "
             f"({risk / A:.1f} ATR, {risk / s['entry'] * 100:.1f}%) | no TP on the order",
             f"TP1 {fmt(s['tp1'])} ({TP1_R:g}R): close half, SL to entry (set a price alert)",
             f"Runner: SL trails {TRAIL_ATR:g}×ATR ({fmt(TRAIL_ATR * A)}) behind the best price; "
             f"moves get pushed"]
    if RISK_USD > 0:
        lines.append(f"Size: ${RISK_USD:g} risk → {RISK_USD / risk:.4g} units")
    else:
        lines.append(f"Size: your $ risk ÷ {fmt(risk)} = units")
    lines += [f"Daily trend {'up' if L else 'down'} | 4H ADX {s['adx']:.0f} | Chop {s['chop']:.0f} | "
              f"RSI 4H {s['rsi4h']:.0f} | {s['ext']:+.1f} ATR from the zone",
              fund_txt(s["fund"]),
              flow_line(fl, s["side"]),
              ob_txt,
              f"Value: {va['state'].replace('_', ' ')} (info)"]
    return "\n".join(lines)


def watch_msg(coin, s, bar_close):
    L = s["side"] == "long"
    return (f"👀 TREND WATCH {s['side'].upper()}: {coin}\n"
            f"Pulled back to {s['zone_txt']}; daily trend and 4H stack intact\n"
            f"Trigger: a {'green' if L else 'red'} 4H close {'above' if L else 'below'} "
            f"{fmt(s['trigger'])}\n"
            f"Next 4H close {local_time(bar_close + 4 * 3600, day=False)} | "
            f"plan SL ≈ {fmt(s['stop_est'])} or {MIN_STOP_ATR:g} ATR, whichever is wider\n"
            f"4H ADX {s['adx']:.0f} | Chop {s['chop']:.0f} | {fund_txt(s['fund'])}\n"
            f"Entry still has to pass the chase, RSI, flow and funding checks")


def metal_rows(df, n):
    return [[int(r.t), round(r.o, 4), round(r.h, 4), round(r.l, 4), round(r.c, 4), int(r.v)]
            for r in df.tail(n).itertuples()]


def save_metals(markets):
    """Write metal candles for the browser grader; skip the write when nothing changed."""
    if not markets:
        return
    old = {}
    if METALS_FILE.exists():
        try:
            old = json.loads(METALS_FILE.read_text()).get("markets", {})
        except Exception:
            old = {}
    merged = {**old, **markets}
    if merged == old:
        return
    METALS_FILE.write_text(json.dumps({"asof": stamp(time.time()), "markets": merged},
                                      separators=(",", ":")))


# ---------- backtest (trend-pullback engine) ----------
def bt_stats(r, hours=None):
    r = pd.Series(r, dtype=float)
    if r.empty:
        return None
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    return {"n": len(r), "win": 100 * (r > 0).mean(), "avg": r.mean(), "tot": r.sum(),
            "pf": wins / losses if losses > 0 else float("inf"),
            "dd": float((eq.cummax() - eq).max()),
            "hrs": float(pd.Series(hours).median()) if hours is not None and len(hours) else NAN}


def bt_cell(st):
    if not st:
        return "-"
    pf = "∞" if st["pf"] == float("inf") else f"{st['pf']:.2f}"
    return f"{st['n']} / {st['win']:.0f}% / {st['avg']:+.2f} / {st['tot']:+.1f} / PF {pf}"


def backtest(days=None):
    """Replay the trend-pullback engine over the last BT_DAYS of 4H bars, one position per coin
    at a time, with fees and slippage. Trades are walked on 4H bars (Kraken keeps only ~30 days
    of 1H), so fills inside a bar are judged conservatively: stop before target."""
    days = days or BT_DAYS
    rows, vetoes, still_open = [], {}, 0
    for coin, pair in WATCHLIST.items():
        try:
            d, h4 = candles(pair, 1440), candles(pair, 240)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}"); continue
        fund = funding_history(coin, pair)
        start = max(80, len(h4) - days * 6)
        busy_until = 0
        for i in range(start, len(h4) - 1):
            close_t = int(h4.t.iloc[i]) + 4 * 3600
            if close_t < busy_until:
                continue
            sub = h4.iloc[:i + 1].reset_index(drop=True)
            dd = d[d.t + 86400 <= close_t].reset_index(drop=True)
            try:
                s = trend_setup(dd, sub, funding_apr(fund, close_t))
            except Exception as e:
                print(f"{coin} bar {i}: {e}"); continue
            if not s:
                continue
            if s["status"] == "veto":
                k = s["why"].split(" ")[0]
                vetoes[k] = vetoes.get(k, 0) + 1
                continue
            if s["status"] != "entry":
                continue
            fwd = h4.iloc[i + 1:]
            tr = {"side": s["side"], "entry": s["entry"], "stop": s["stop"], "atr": s["atr"],
                  "from_t": close_t}
            res = {m: manage(tr, fwd, 4 * 3600, mode=m, fee_bps=BT_FEE_BPS, slip_bps=BT_SLIP_BPS)
                   for m in BT_MODES}
            if not res["plan"]["done"]:
                still_open += 1
                busy_until = 10 ** 12
                continue
            ob_tag, _ = ob_info(order_blocks(sub), s["side"], s["entry"], s["tp1"], s["atr"])
            row = {"coin": coin, "side": s["side"], "zone": s["zone"], "t": close_t,
                   "time_utc": stamp(close_t), "entry": s["entry"], "stop": s["stop"],
                   "adx": round(s["adx"], 1), "fund": s["fund"], "ob": ob_tag,
                   "ob_ok": ob_tag not in ("in-against", "blocked")}
            for m in BT_MODES:
                rr = res[m]
                row[f"{m}_r"] = round(rr["r"], 3) if rr["done"] else NAN
                row[f"{m}_hrs"] = round((rr["end_t"] - close_t) / 3600, 1) if rr["done"] else NAN
            row["mfe_r"] = round(res["plan"]["mfe_r"], 2)
            rows.append(row)
            busy_until = res["plan"]["end_t"]
        print(f"{coin}: {sum(r['coin'] == coin for r in rows)} trades")

    df = pd.DataFrame(rows)
    out = ["# Trend-pullback backtest\n",
           f"Last {days} days of 4H bars, {len(WATCHLIST)} markets, one position per market. "
           f"Fees {BT_FEE_BPS:g} bps/side, slippage {BT_SLIP_BPS:g} bps on entries and stops. "
           f"R is net. {still_open} trades still open at the end were left out.\n",
           "Cells: n / win% / avg R / total R / profit factor. Look for rows that stay positive "
           "with n >= 30, and compare against the legacy rows in paper_summary.md.\n"]
    if df.empty:
        out.append("No completed trades in the window.\n")
    else:
        df = df.sort_values("t")
        out.append("## Exit plans on the same entries\n")
        out.append("| plan | result | max DD (R) | median hours |")
        out.append("|---|---|---|---|")
        for m in BT_MODES:
            st = bt_stats(df[f"{m}_r"].dropna(), df[f"{m}_hrs"].dropna())
            out.append(f"| {m} | {bt_cell(st)} | {st['dd']:.1f} | {st['hrs']:.0f} |")
        for col, title in (("side", "side"), ("zone", "pullback zone"), ("ob_ok", "order block ok"),
                           ("coin", "market")):
            out.append(f"\n## By {title} (plan exits)\n")
            out.append(f"| {col} | result |")
            out.append("|---|---|")
            for k, x in df.groupby(col):
                out.append(f"| {k} | {bt_cell(bt_stats(x['plan_r'].dropna()))} |")
        fk = df["fund"].notna()
        out.append(f"\nFunding known on {fk.sum()} of {len(df)} entries. "
                   f"Average best excursion {df['mfe_r'].mean():.2f}R; "
                   f"{100 * (df['mfe_r'] >= 1).mean():.0f}% reached +1R.\n")
    if vetoes:
        out.append("## Vetoed triggers\n")
        out.append(" | ".join(f"{k}: {v}" for k, v in sorted(vetoes.items(), key=lambda x: -x[1])) + "\n")
    text = "\n".join(out) + "\n"
    print(text)
    write_step_summary(text)
    return df


# ---------- one pass ----------
def run_once():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now, changed, log, out_rows = time.time(), False, [], []
    metals, entries = {}, []

    for coin, pair in WATCHLIST.items():
        try:
            d, h4, h1 = candles(pair, 1440), candles(pair, 240), candles(pair, 60)
            if pair.startswith("yf:"):
                m15, m5 = candles(pair, 15), candles(pair, 5)
                metals[coin] = {"d1": metal_rows(d, 400), "h1": metal_rows(h1, 720),
                                "m15": metal_rows(m15, 300), "m5": metal_rows(m5, 300)}
            time.sleep(1)   # stay under Kraken's public rate limit
        except Exception as e:
            print(f"skip {coin}: {e}"); continue

        try:
            fl = flow_state(h4)
        except Exception as e:
            print(f"skip {coin} flow: {e}")
            fl = {"label": "unknown", "dir": 0, "heavy": False, "text": "unavailable"}

        rows, msgs, ch = resolve_trades(state, coin, h1, now)
        if ch:
            changed = True
        out_rows += rows
        for row in rows:
            print(f"{coin}: {row[3]} {row[4]} resolved {row[12]} {row[13]:+.2f}R")
        for m in msgs:
            notify(m, urgent=False, push=TREND_PUSH)
            log.append(f"{stamp(now)},{coin},trend-manage,{m.splitlines()[0].split(':')[0]},-")

        try:
            fund = funding_apr(funding_history(coin, pair), now)
        except Exception as e:
            print(f"{coin} funding: {e}"); fund = None
        try:
            s = trend_setup(d, h4, fund)
        except Exception as e:
            print(f"skip {coin} setup: {e}"); continue
        ftxt = "n/a" if fund is None else f"{fund:+.0f}%/yr"
        if not s:
            print(f"{coin}: no setup (trend, 4H stack, chop or pullback) | funding {ftxt}")
            continue
        print(f"{coin}: {s['side']} {s['status']} via {s['zone']} | ADX {s['adx']:.0f} chop {s['chop']:.0f} "
              f"| funding {ftxt}" + (f" | veto: {s['why']}" if s["status"] == "veto" else ""))

        if s["status"] == "entry":
            key = f"{coin}_tp"
            if state.get(key, {}).get("bar") == s["bar"]:
                continue                                  # this 4H bar was already handled
            if any(t["coin"] == coin and t["kind"] == "trend" for t in state.get("open", [])):
                print(f"{coin}: already in a trend trade, new trigger ignored")
                state[key] = {"bar": s["bar"], "sent": now}; changed = True
                continue
            entries.append((coin, s, fl, h4))
        elif s["status"] == "watch":
            key = f"{coin}_watch"
            prev = state.get(key, {})
            if prev.get("side") != s["side"] or now - prev.get("sent", 0) > WATCH_COOLDOWN_HRS * 3600:
                notify(watch_msg(coin, s, s["bar"]), push=WATCH_PUSH)
                log.append(f"{stamp(now)},{coin},watch-{s['side']}{'' if WATCH_PUSH else '-muted'},"
                           f"{s['zone']},{h4.c.iloc[-1]}")
                state[key] = {"side": s["side"], "sent": now}; changed = True

    # entries: strongest 4H trend first, at most MAX_PUSH_PER_SIDE pushes per direction
    entries.sort(key=lambda x: -x[1]["adx"])
    pushed = {"long": 0, "short": 0}
    for coin, s, fl, h4 in entries:
        push = TREND_PUSH and pushed[s["side"]] < MAX_PUSH_PER_SIDE
        if push:
            pushed[s["side"]] += 1
        try:
            obs = order_blocks(h4)
        except Exception:
            obs = []
        ob_tag, ob_txt = ob_info(obs, s["side"], s["entry"], s["tp1"], s["atr"])
        va = value_state(_cols(h4), s["entry"], s["side"] == "long")
        note = "" if push or not TREND_PUSH else " (muted: same-direction cap)"
        notify(trend_msg(coin, s, fl, ob_txt, va, note), urgent=True, push=push)
        log.append(f"{stamp(now)},{coin},trend-{s['side']}{'' if push else '-muted'},{s['zone']},{s['entry']}")
        state[f"{coin}_tp"] = {"bar": s["bar"], "sent": now}
        open_trade(state, coin, "trend", s["side"], s["zone"], s["entry"], s["stop"], s["tp1"],
                   s["from_t"], now, va["state"], "fit" if va["fit"] else "no fit", "trail",
                   fl["label"], ob_tag, atr=s["atr"], pushed=push)
        changed = True

    save_metals(metals)
    orphans = expire_orphans(state, now)
    if orphans:
        out_rows += orphans; changed = True
    if changed:
        STATE_FILE.write_text(json.dumps(state, indent=1))
    if out_rows:
        if OUT_FILE.exists():
            old = pd.read_csv(OUT_FILE)
            missing_cols = [c for c in ("flow", "ob") if c not in old]
            if missing_cols:                  # file from before these columns existed
                for c in missing_cols:
                    old[c] = ""
                old[OUT_COLS].to_csv(OUT_FILE, index=False)
        new_file = not OUT_FILE.exists()
        with OUT_FILE.open("a") as f:
            if new_file: f.write(",".join(OUT_COLS) + "\n")
            f.write("\n".join(",".join(str(x) for x in r) for r in out_rows) + "\n")
        SUMMARY_FILE.write_text(summarize(len(state.get("open", []))))
        n = int((pd.read_csv(OUT_FILE).kind == "trend").sum())
        milestone = n // 30 * 30
        if milestone >= 30 and state.get("review_trend_at", 0) < milestone:
            send(f"📊 {n} trend-engine outcomes logged. Review outcomes_summary.md "
                 f"against the backtest before changing any rule.")
            state["review_trend_at"] = milestone
            STATE_FILE.write_text(json.dumps(state, indent=1))
    if log:
        new_file = not LOG_FILE.exists()
        with LOG_FILE.open("a") as f:
            if new_file: f.write("utc,coin,side,met,price\n")
            f.write("\n".join(log) + "\n")


def main():
    if "--test" in sys.argv:
        send("✅ Grader alerts are connected.")
        return
    if "--backtest" in sys.argv:
        backtest(); return
    if "--report" in sys.argv:
        report(); return
    run_once()

if __name__ == "__main__":
    main()
