"""
A+ Setup Grader - alert runner for GitHub Actions.
Grades each coin with the same rules as the browser grader, using closed
Kraken candles: five scored checks (level, confirmations, R:R, volume, clean
price action), daily trend as context only, and the RSI re-entry gate deciding
Actionable vs Wait. Sends a phone push (ntfy) when a coin grades B+ or better
("setup graded, waiting on RSI") or turns Actionable (grade plus RSI gate).
Also flags 4H breakouts and momentum shifts, where 5m and 15m flip against
the 4H trend with divergence and money-flow confluence pointing to a 4H cross.

Value area: each grade is tagged with the market state from a 4H volume profile
(balance, imbalance up/down, or an unaccepted probe) and whether the setup fits
that state. Info only unless VA_GATE=1, which also requires a fit for Actionable.

Outcomes: every graded or momentum-shift alert with a stop and target is tracked
on closed 1H bars until stop, target, or MAX_HOLD_HRS, then written to
outcomes.csv and summarized in outcomes_summary.md. Run with --report to print it.
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
OUT_FILE = Path("outcomes.csv")
SUMMARY_FILE = Path("outcomes_summary.md")

# Value area (auction market theory) settings
VA_BARS = int(os.environ.get("VA_BARS", "42"))        # 4H bars in the profile (42 = 7 days)
VA_ACCEPT = int(os.environ.get("VA_ACCEPT", "3"))     # 4H closes outside value needed for acceptance
VA_PCT = 0.70                                         # share of volume inside the value area
VA_BINS = 60
VA_GATE = os.environ.get("VA_GATE", "0") == "1"       # 1 = Actionable also requires a state fit

# Outcome tracking
MAX_HOLD_HRS = int(os.environ.get("MAX_HOLD_HRS", "336"))  # 14 days, then close at market

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

# ---------- outcome tracking ----------
OUT_COLS = ["alert_utc", "resolved_utc", "coin", "kind", "side", "grade", "va_state", "va_fit",
            "target_src", "entry", "stop", "target", "outcome", "r", "mfe_r", "mae_r", "hours"]


def open_trade(state, coin, kind, side, grade_, entry, stop, target, from_t, now,
               va_state="", va_fit="", target_src=""):
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
                   "va_fit": va_fit, "target_src": target_src or ""})


def walk_trade(tr, h1, now):
    """Replay closed 1H bars after the alert. Stop and target in the same bar counts as a loss."""
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
            round(mfe, 3), round(mae, 3), round((end_t - tr["t"]) / 3600, 1)]


def resolve_trades(state, coin, h1, now):
    rows, keep = [], []
    for tr in state.get("open", []):
        row = walk_trade(tr, h1, now) if tr["coin"] == coin else None
        (rows.append(row) if row else keep.append(tr))
    if rows:
        state["open"] = keep
    return rows


def expire_orphans(state, now):
    """Close trades for coins no longer on the watchlist once they pass the hold limit."""
    rows, keep = [], []
    for tr in state.get("open", []):
        if tr["coin"] not in WATCHLIST and now - tr["t"] > MAX_HOLD_HRS * 3600:
            rows.append([stamp(tr["t"]), stamp(now), tr["coin"], tr["kind"], tr["side"], tr["grade"],
                         tr.get("va_state", ""), tr.get("va_fit", ""), tr.get("target_src", ""),
                         tr["entry"], tr["stop"], tr["target"], "dropped", 0.0, 0.0, 0.0,
                         round((now - tr["t"]) / 3600, 1)])
        else:
            keep.append(tr)
    if rows:
        state["open"] = keep
    return rows


def summarize(n_open=0):
    """Win rate and expectancy by alert kind, grade, value-area fit and target source."""
    if not OUT_FILE.exists():
        return "No resolved alerts yet."
    df = pd.read_csv(OUT_FILE)
    df = df[df.outcome != "dropped"].copy()
    for col in ("grade", "va_state", "va_fit", "target_src"):
        df[col] = df[col].fillna("-").astype(str)
    if df.empty:
        return "No resolved alerts yet."

    def table(by):
        g = df.groupby(by, dropna=False)
        rows = [f"| {' / '.join(by)} | n | win % | avg R | total R | avg MFE R |",
                "|---|---|---|---|---|---|"]
        for k, x in g:
            k = " / ".join(str(v) for v in (k if isinstance(k, tuple) else (k,)))
            rows.append(f"| {k} | {len(x)} | {100 * (x.outcome == 'win').mean():.0f} | "
                        f"{x.r.mean():+.2f} | {x.r.sum():+.1f} | {x.mfe_r.mean():.2f} |")
        return "\n".join(rows)

    parts = [f"# Alert outcomes\n\n{len(df)} resolved, {n_open} still open. "
             f"Updated {stamp(time.time())} UTC.\n",
             "Small samples mean little; wait for 30+ per row before changing rules.\n",
             "## By kind and grade\n\n" + table(["kind", "grade"]),
             "## By value-area fit\n\n" + table(["kind", "va_fit"]),
             "## By value-area state\n\n" + table(["kind", "va_state"]),
             "## By target source\n\n" + table(["kind", "target_src"])]
    return "\n\n".join(parts) + "\n"


def report():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    text = summarize(len(state.get("open", [])))
    print(text)
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

def fmt(p):
    if p is None: return "–"
    return f"{p:,.2f}" if p >= 1 else f"{p:.5f}"

def stamp(now):
    return time.strftime('%Y-%m-%d %H:%M', time.gmtime(now))

def va_line(best):
    va = best["va"]
    tgt = " | target from fib ext." if best.get("target_src") == "fib" else ""
    if va["state"] == "unknown":
        return va["note"] + tgt
    mark = "fits" if va["fit"] else "no fit"
    return (f"{va['state'].replace('_', ' ')}, {mark} ({va['note']}) | "
            f"VAL {fmt(va['val'])} POC {fmt(va['poc'])} VAH {fmt(va['vah'])}{tgt}")

def backtest(bars=180):
    """List every momentum shift in the last `bars` closed 4H candles (no alerts sent)."""
    for coin, pair in WATCHLIST.items():
        try:
            h4, m15, m5 = candles(pair, 240), candles(pair, 15), candles(pair, 5)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}"); continue
        found, last_side = 0, None
        for i in range(max(60, len(h4) - bars), len(h4)):
            sub = h4.iloc[:i + 1].reset_index(drop=True)
            close_t = sub.t.iloc[-1] + 4 * 3600
            c15 = m15[m15.t + 900 <= close_t].reset_index(drop=True)
            c5 = m5[m5.t + 300 <= close_t].reset_index(drop=True)
            if len(c15) < 30 or len(c5) < 30:
                continue                      # 5m/15m history does not reach that far back
            ms = momentum_shift(sub, c15, c5)
            if ms and ms["score"] >= MS_MIN and ms["side"] != last_side:
                found += 1
                last_side = ms["side"]
                when = time.strftime('%b %d %H:%M', time.gmtime(sub.t.iloc[-1]))
                eta = f"{ms['eta']:.1f}" if ms["eta"] is not None else "-"
                print(f"{coin} {when} UTC  {ms['side'].upper():5} {ms['score']}/7  "
                      f"entry {fmt(ms['entry'])}  4H cross in ~{eta} bars  "
                      f"MFI {ms['mfi']:.0f}  CMF {ms['cmf']:+.2f}"
                      + ("  DIV" if ms["div"] else ""))
        if not found:
            print(f"{coin}: no momentum shifts (5m/15m history only reaches back ~2 days)")

# ---------- one pass ----------
def run_once():
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    now, changed, log, out_rows = time.time(), False, [], []

    for coin, pair in WATCHLIST.items():
        try:
            d, h4, h1 = candles(pair, 1440), candles(pair, 240), candles(pair, 60)
            m15, m5 = candles(pair, 15), candles(pair, 5)
            time.sleep(1)   # stay under Kraken's public rate limit
        except Exception as e:
            print(f"skip {coin}: {e}"); continue

        done = resolve_trades(state, coin, h1, now)
        if done:
            out_rows += done; changed = True
            for row in done:
                print(f"{coin}: {row[3]} {row[4]} resolved {row[12]} {row[13]:+.2f}R")

        try:
            best = grade(d, h4, h1)
        except Exception as e:
            print(f"skip {coin} grade: {e}"); best = None
        if best:
            ok_grade = best["grade"] in ("A+", "B+")
            tier = 2 if best["action"] == "actionable" else 1 if ok_grade else 0
            prev = state.get(coin, {})
            if not isinstance(prev, dict) or prev.get("v") != STATE_V:
                prev = {"tier": 0, "sent": {}}          # rules changed; start tiers fresh
            sent = prev.get("sent", {})
            print(f"{coin}: {best['side']} {best['grade']} {best['passed']}/5 {best['action']} tier {tier} "
                  f"| {best['va']['state']} {'fit' if best['va']['fit'] else 'no fit'}")

            # alert on a move up into a tier, unless that tier already alerted within the cooldown
            if tier > prev.get("tier", 0) and now - sent.get(str(tier), 0) > COOLDOWN_HRS * 3600:
                label = "🚨 ACTIONABLE" if tier == 2 else "👀 Setup graded, waiting on RSI"
                missing = [k for k, v in best["checks"].items() if not v]
                rr = f" ({best['rr']:.1f}R)" if best["rr"] else ""
                msg = (f"{label}: {coin} {best['side'].upper()} {best['grade']} {best['passed']}/5\n"
                       f"Price {fmt(best['entry'])} | Stop {fmt(best['stop'])} | Target {fmt(best['target'])}{rr}\n"
                       f"RSI 4H {best['rsi4h']:.0f} / D {best['rsid']:.0f} | {best['gate_note']}\n"
                       f"Level: {best['level_note']}\n"
                       f"Volume: {best['vol_note']} | Chop {best['chop']:.0f} {best['chop_state']}\n"
                       f"Value: {va_line(best)}\n"
                       f"Trend {'with you' if best['trend_ok'] else 'not aligned'} (info only)"
                       + (f"\nMissing: {', '.join(missing)}" if missing else ""))
                send(msg, urgent=(tier == 2))
                log.append(f"{stamp(now)},{coin},{best['side']},{best['grade']} {best['passed']}/5 {best['action']},{best['entry']}")
                sent[str(tier)] = now
                open_trade(state, coin, "grade-actionable" if tier == 2 else "grade-watch",
                           best["side"], best["grade"], best["entry"], best["stop"], best["target"],
                           best["from_t"], now, best["va"]["state"],
                           "fit" if best["va"]["fit"] else "no fit", best["target_src"])
            if tier != prev.get("tier", 0) or sent != prev.get("sent", {}) or prev.get("v") != STATE_V:
                state[coin] = {"v": STATE_V, "tier": tier, "sent": sent}; changed = True

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

        ms = momentum_shift(h4, m15, m5)
        if ms:
            eta = f"{ms['eta']:.1f}" if ms["eta"] is not None else "-"
            print(f"{coin}: shift {ms['side']} {ms['score']}/7, 4H cross in ~{eta} bars")
            key = f"{coin}_ms"
            prev_ms = state.get(key, {})
            if not isinstance(prev_ms, dict):
                prev_ms = {}
            if (ms["score"] >= MS_MIN and prev_ms.get("bar") != ms["bar"]
                    and (prev_ms.get("side") != ms["side"]
                         or now - prev_ms.get("sent", 0) > MS_COOLDOWN_HRS * 3600)):
                on = [k for k, v in ms["factors"].items() if v]
                tp = " / ".join(fmt(x) for x in ms["tps"])
                arrow = "🔼" if ms["side"] == "long" else "🔽"
                send(f"{arrow} MOMENTUM SHIFT {ms['side'].upper()}: {coin} {ms['score']}/7\n"
                     f"5m+15m flipped, 4H cross in ~{eta} bars\n"
                     f"Entry {fmt(ms['entry'])} | SL {fmt(ms['stop'])}\n"
                     f"TP1-3 {tp}\n"
                     f"RSI 4H {ms['rsi4h']:.0f} | MFI {ms['mfi']:.0f} | CMF {ms['cmf']:+.2f}"
                     + ("\nDivergence confirmed" if ms["div"] else "")
                     + f"\nHave: {', '.join(on)}", urgent=True)
                log.append(f"{stamp(now)},{coin},shift-{ms['side']},{ms['score']},{ms['entry']}")
                state[key] = {"bar": ms["bar"], "side": ms["side"], "sent": now}; changed = True
                # track to TP2 (2R, matching MIN_RR) so shifts compare fairly with grades
                open_trade(state, coin, "shift", ms["side"], f"{ms['score']}/7", ms["entry"],
                           ms["stop"], ms["tps"][1], ms["from_t"], now)

    orphans = expire_orphans(state, now)
    if orphans:
        out_rows += orphans; changed = True
    if changed:
        STATE_FILE.write_text(json.dumps(state, indent=1))
    if out_rows:
        new_file = not OUT_FILE.exists()
        with OUT_FILE.open("a") as f:
            if new_file: f.write(",".join(OUT_COLS) + "\n")
            f.write("\n".join(",".join(str(x) for x in r) for r in out_rows) + "\n")
        SUMMARY_FILE.write_text(summarize(len(state.get("open", []))))
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
