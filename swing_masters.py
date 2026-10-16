"""
Famous traders' swing systems, coded from their published rules and backtested side by side.

Every system trades the same Robinhood popular list over the last MASTERS_YEARS years in a
$START_USD cash account (fractional shares, 5 bps slippage per fill, positions marked to market
daily so the worst drop includes open losses). One position per stock per system.

  Qullamaggie breakout   Stock up 30%+ in 3 months, holding rising 10/20/50-day averages, ADR 3.5%+,
                         tight 10-day flag (range <= 15%). Buy-stop at the flag high (skip if it opens
                         more than 1 ATR above). Stop: entry-day low, never more than 1 ATR. Sell 1/3
                         at the 5th day's close and move the stop to breakeven; the rest exits on the
                         first close below the 10-day average (a 20-day version too).
  Qullamaggie EP         Episodic pivot: gap up 10%+ on 3x+ normal volume, closing in the top half of the
                         day, in a stock not already up 50%+ in 3 months. Buy the gap day's close; stop
                         at the gap day's low (max 10%). 1/3 off at day 5, breakeven stop, rest exits on
                         a close below the 20-day. (Real EPs need a news/earnings catalyst; this data
                         has none, so the gap-and-volume rule stands in for it.)
  Turtle System 2        Long only. Buy-stop at the 55-day high; stop 2N (N = 20-day ATR) below entry;
                         exit on a break of the 20-day low. Pyramiding (adding up to 4 units) left out.
  Weinstein stage 2      Weekly bars. Close breaks above the prior 12-week high, the 30-week average is
                         turning up with price above it, volume 2x the prior 10-week average, and
                         Mansfield relative strength vs SPY above zero. Buy next week's open; stop at
                         the 12-week base low (max 15%); sell after a weekly close below the 30-week.
  Clenow momentum        Stocks on the Move: rank by 90-day exponential regression slope (annualized) x
                         R squared; skip stocks below their 100-day average or with a 15%+ gap in 90
                         days. Weekly: hold the top 20% of the list, sized at 0.1% of equity per ATR;
                         new buys only while SPY is above its 200-day.

Breakout, EP, Turtle and Weinstein trades are sized to risk RISK_PCT of equity at the initial stop,
capped at CAP_PCT of equity per position and the cash left.

Benchmarks: SPY, the 2/3 TQQQ + 1/3 QQQ trend strategy (strategies.py), and holding the whole popular
list equally (rebalanced monthly). That last one matters: the list is today's winners, so beating
it is the fair test of whether a system adds anything beyond hindsight.

Writes swing_masters_report.md and swing_masters_trades.csv.   python swing_masters.py
"""
import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd

import grader as G
import strategies as S

YEARS = int(os.environ.get("MASTERS_YEARS", "10"))
START_USD = 2000.0
RISK_PCT = float(os.environ.get("MASTERS_RISK_PCT", "1.0"))
CAP_PCT = float(os.environ.get("MASTERS_CAP_PCT", "25"))
SLIP = G.SLIP_BPS / 1e4
REPORT = Path("swing_masters_report.md")
TRADES = Path("swing_masters_trades.csv")


# ---------------- shared trade manager (long only) ----------------
def manage(dates, O, H, L, C, i, entry, stop, partial_k=None, close_ma=None, low_exit=None, stop_from=None):
    """Run a long trade filled at `entry` on bar i. From bar i+1: gap/intraday stop checks, an optional
    1/3 partial at bar i+partial_k's close (then stop to breakeven), an optional exit at the next open
    after a close below close_ma, and an optional intraday exit at low_exit[k] (e.g. a 20-day low).
    stop_from: the bar index from which the stop is live (defaults to i+1). Returns (ret %, exit index)."""
    q, real, pend = 1.0, 0.0, False
    for k in range(i + 1, len(O)):
        if pend:
            px = O[k] * (1 - SLIP)
            return 100 * (real + q * (px / entry - 1)), k
        level = stop
        if low_exit is not None and np.isfinite(low_exit[k]):
            level = max(level, low_exit[k])
        if O[k] <= level:
            return 100 * (real + q * (O[k] * (1 - SLIP) / entry - 1)), k
        if L[k] <= level:
            return 100 * (real + q * (level * (1 - SLIP) / entry - 1)), k
        if partial_k and k - i == partial_k and q == 1.0:
            real += (1 / 3) * (C[k] * (1 - SLIP) / entry - 1)
            q = 2 / 3
            stop = max(stop, entry)
        if close_ma is not None and np.isfinite(close_ma[k]) and C[k] < close_ma[k]:
            pend = True
    return 100 * (real + q * (C[-1] / entry - 1)), len(O) - 1          # still open: marked at last close


def arrays(df):
    return (df.index, *(df[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume")))


def atr_arr(df, n=14):
    return G.atr(df, n).to_numpy(float)


# ---------------- systems that produce trade lists ----------------
def qulla_breakout(sym, df, ma_len=10):
    dates, O, H, L, C, V = arrays(df)
    s = pd.Series(C, index=dates)
    sma10, sma20, sma50 = (s.rolling(n).mean().to_numpy() for n in (10, 20, 50))
    ma_exit = s.rolling(ma_len).mean().to_numpy()
    a = atr_arr(df)
    adr = (pd.Series(H / L - 1, index=dates).rolling(20).mean()).to_numpy()
    pivot = pd.Series(H, index=dates).rolling(10).max().shift(1).to_numpy()     # flag high, prior 10 days
    flag_lo = pd.Series(L, index=dates).rolling(10).min().shift(1).to_numpy()
    dv20 = (s * V).rolling(20).mean().to_numpy()
    out, busy = [], -1
    for i in range(130, len(C)):
        p = i - 1                                                     # setup known at yesterday's close
        if i <= busy or not np.isfinite(pivot[i]) or C[p] < 10 or dv20[p] < 50e6:
            continue
        if not (C[p] >= 1.30 * C[p - 63] and C[p] > sma10[p] > sma20[p] > sma50[p] and sma20[p] > sma20[p - 5]
                and adr[p] >= 0.035 and pivot[i] / flag_lo[i] - 1 <= 0.15):
            continue
        if H[i] <= pivot[i] or O[i] > pivot[i] + a[p]:
            continue
        entry = max(O[i], pivot[i]) * (1 + SLIP)
        stop = max(L[i], entry - a[p])
        ret, k = manage(dates, O, H, L, C, i, entry, stop, partial_k=5, close_ma=ma_exit)
        out.append(dict(sym=sym, entry_date=dates[i], entry=entry, stop=stop, ret=ret, exit=dates[k], days=k - i + 1))
        busy = k
    return out


def qulla_ep(sym, df):
    dates, O, H, L, C, V = arrays(df)
    s = pd.Series(C, index=dates)
    sma20 = s.rolling(20).mean().to_numpy()
    vol50 = pd.Series(V, index=dates).rolling(50).mean().shift(1).to_numpy()
    dv20 = (s * V).rolling(20).mean().to_numpy()
    out, busy = [], -1
    for i in range(130, len(C)):
        if i <= busy or C[i - 1] < 10 or dv20[i - 1] < 50e6 or not np.isfinite(vol50[i]):
            continue
        rng = H[i] - L[i]
        if not (O[i] >= 1.10 * C[i - 1] and V[i] >= 3 * vol50[i] and rng > 0 and (C[i] - L[i]) / rng >= 0.5
                and C[i - 1] <= 1.5 * C[i - 64]):
            continue
        entry = C[i] * (1 + SLIP)
        stop = max(L[i], entry * 0.90)
        ret, k = manage(dates, O, H, L, C, i, entry, stop, partial_k=5, close_ma=sma20)
        out.append(dict(sym=sym, entry_date=dates[i], entry=entry, stop=stop, ret=ret, exit=dates[k], days=k - i + 1))
        busy = k
    return out


def turtle_s2(sym, df):
    dates, O, H, L, C, V = arrays(df)
    n = G.atr(df, 20).to_numpy(float)
    hi55 = pd.Series(H, index=dates).rolling(55).max().shift(1).to_numpy()
    lo20 = pd.Series(L, index=dates).rolling(20).min().shift(1).to_numpy()
    dv20 = (pd.Series(C * V, index=dates)).rolling(20).mean().to_numpy()
    out, busy = [], -1
    for i in range(60, len(C)):
        if i <= busy or not np.isfinite(hi55[i]) or C[i - 1] < 10 or dv20[i - 1] < 50e6:
            continue
        if H[i] <= hi55[i]:
            continue
        entry = max(O[i], hi55[i]) * (1 + SLIP)
        stop = entry - 2 * n[i - 1]
        ret, k = manage(dates, O, H, L, C, i, entry, stop, low_exit=lo20)
        out.append(dict(sym=sym, entry_date=dates[i], entry=entry, stop=stop, ret=ret, exit=dates[k], days=k - i + 1))
        busy = k
    return out


def weinstein(sym, df, spy):
    wk = df.index.to_period("W-FRI")
    g = df.groupby(wk)
    W = pd.DataFrame({"Open": g.Open.first(), "High": g.High.max(), "Low": g.Low.min(),
                      "Close": g.Close.last(), "Volume": g.Volume.sum()})
    first_day = g.apply(lambda x: x.index[0])
    last_day = g.apply(lambda x: x.index[-1])
    spy_w = spy.Close.groupby(spy.index.to_period("W-FRI")).last().reindex(W.index).ffill()
    O, H, L, C, V = (W[k].to_numpy(float) for k in ("Open", "High", "Low", "Close", "Volume"))
    ma30 = W.Close.rolling(30).mean().to_numpy()
    res12 = W.High.rolling(12).max().shift(1).to_numpy()
    base_lo = W.Low.rolling(12).min().shift(1).to_numpy()
    vavg = W.Volume.rolling(10).mean().shift(1).to_numpy()
    rs = W.Close / spy_w
    mrs = (rs / rs.rolling(52).mean() - 1).to_numpy()
    dv = (W.Close * W.Volume / 5).rolling(4).mean().to_numpy()
    out, busy = [], -1
    for j in range(53, len(C) - 1):
        if j < busy or not np.isfinite(ma30[j]) or C[j] < 10 or dv[j] < 50e6:
            continue
        if not (C[j] > res12[j] and C[j] > ma30[j] and ma30[j] >= ma30[j - 1] and V[j] >= 2 * vavg[j]
                and mrs[j] > 0):
            continue
        i = j + 1                                                     # buy next week's open
        entry = O[i] * (1 + SLIP)
        stop = max(base_lo[j], entry * 0.85)
        ret, k = _weinstein_manage(O, H, L, C, i, entry, stop, ma30)
        exit_day = first_day.iloc[k] if k < len(C) else last_day.iloc[-1]
        out.append(dict(sym=sym, entry_date=first_day.iloc[i], entry=entry, stop=stop, ret=ret,
                        exit=exit_day, days=int((exit_day - first_day.iloc[i]).days * 5 / 7) + 1))
        busy = k + 1
    return out


def _weinstein_manage(O, H, L, C, i, entry, stop, ma30):
    """Weekly: the stop is live from the entry week; a weekly close below the 30-week sells at the next
    week's open. Returns (ret %, index of the week whose first day is the exit day)."""
    pend = False
    for k in range(i, len(O)):
        if pend:
            return 100 * (O[k] * (1 - SLIP) / entry - 1), k
        if k > i and O[k] <= stop:
            return 100 * (O[k] * (1 - SLIP) / entry - 1), k
        if L[k] <= stop:
            return 100 * (stop * (1 - SLIP) / entry - 1), min(k + 1, len(O) - 1)
        if C[k] < ma30[k]:
            pend = True
    return 100 * (C[-1] / entry - 1), len(O) - 1


# ---------------- weight-based systems ----------------
def clenow(stocks, spy, atrs):
    """Weekly Stocks-on-the-Move rotation. stocks: closes; atrs: 20-day ATR frame."""
    logp = np.log(stocks)
    t = pd.Series(np.arange(len(stocks), dtype=float), index=stocks.index)
    slope = logp.rolling(90).cov(t).div(t.rolling(90).var(), axis=0)
    r2 = logp.rolling(90).corr(t) ** 2
    score = ((np.exp(slope) ** 252) - 1) * r2
    ma100 = stocks.rolling(100).mean()
    gap = stocks.pct_change().abs().rolling(90).max()
    ok = (stocks > ma100) & (gap < 0.15)
    spy_ok = spy > spy.rolling(200).mean()
    top_n = max(1, int(round(0.2 * stocks.shape[1])))
    week = pd.Series(stocks.index.to_period("W-FRI"), index=stocks.index)
    first = week != week.shift(1)
    rets = stocks.pct_change().fillna(0.0)
    w = pd.DataFrame(0.0, index=stocks.index, columns=stocks.columns)
    cur = pd.Series(0.0, index=stocks.columns)
    for i, d in enumerate(stocks.index):
        if i > 0 and first.iloc[i]:
            p = stocks.index[i - 1]
            sc = score.loc[p].where(ok.loc[p]).dropna()
            ranked = list(sc.sort_values(ascending=False).index[:top_n])
            keep = [s for s in cur[cur > 0].index if s in ranked]
            target = pd.Series(0.0, index=stocks.columns)
            size = (0.001 * stocks.loc[p] / atrs.loc[p]).clip(upper=CAP_PCT / 100)
            total = 0.0
            for s_ in keep + [s for s in ranked if s not in keep and bool(spy_ok.loc[p])]:
                if not np.isfinite(size[s_]) or total >= 1:
                    continue
                target[s_] = min(size[s_], 1 - total)
                total += target[s_]
            cur = target
        w.iloc[i] = cur.values
    held = w.shift(1).fillna(0.0)
    turnover = w.diff().abs().sum(axis=1).fillna(0.0)
    return (held * rets).sum(axis=1) - turnover * G.SLIP_BPS / 1e4


def equal_weight(stocks):
    rets = stocks.pct_change()
    have = stocks.notna() & stocks.shift(200).notna()
    w = have.div(have.sum(axis=1), axis=0).fillna(0.0)
    month = pd.Series(stocks.index.to_period("M"), index=stocks.index)
    w = w.where(month != month.shift(1)).ffill().fillna(0.0)
    return (w.shift(1) * rets.fillna(0.0)).sum(axis=1)


# ---------------- portfolio for trade lists ----------------
def portfolio(t, closes, start):
    t = t[t.entry_date > start].sort_values(["entry_date", "sym"]).reset_index(drop=True)
    days = closes.index[closes.index > start]
    by_day = {d: g for d, g in t.groupby("entry_date")}
    cash, held, curve, taken = START_USD, [], [], 0
    for day in days:
        still = []
        for h in held:
            if h["exit"] <= day:
                cash += h["n"] * (1 + h["ret"] / 100)
            else:
                still.append(h)
        held = still

        def mtm():
            v = 0.0
            for h in held:
                c = closes.at[day, h["sym"]]
                if np.isfinite(c):
                    h["last"] = c
                v += h["n"] * h["last"] / h["entry"]
            return v

        if day in by_day:
            for r in by_day[day].itertuples():
                eq = cash + mtm()
                sd = max((r.entry - r.stop) / r.entry, 0.005)
                n = min(eq * RISK_PCT / 100 / sd, eq * CAP_PCT / 100, cash)
                if n < 1:
                    continue
                cash -= n
                held.append({"sym": r.sym, "n": n, "ret": r.ret, "exit": r.exit, "entry": r.entry, "last": r.entry})
                taken += 1
        curve.append(cash + mtm())
    return pd.Series(curve, index=days), taken


def main():
    syms, src = G.robinhood_top100()
    data = G.load_data(list(syms) + ["QQQ", "TQQQ"], f"{YEARS + 2}y")
    spy = data["SPY"]
    closes = pd.DataFrame({k: v.Close for k, v in data.items()})
    stock_syms = [s for s in syms if s in data and s not in ("SPY", "QQQ", "TQQQ")]
    start = closes.index[-1] - pd.DateOffset(years=YEARS)

    systems = {"Qullamaggie breakout (10-day exit)": [], "Qullamaggie breakout (20-day exit)": [],
               "Qullamaggie episodic pivot": [], "Turtle System 2 (55/20)": [], "Weinstein stage 2": []}
    for sym in stock_syms:
        df = data[sym]
        systems["Qullamaggie breakout (10-day exit)"] += qulla_breakout(sym, df, 10)
        systems["Qullamaggie breakout (20-day exit)"] += qulla_breakout(sym, df, 20)
        systems["Qullamaggie episodic pivot"] += qulla_ep(sym, df)
        systems["Turtle System 2 (55/20)"] += turtle_s2(sym, df)
        systems["Weinstein stage 2"] += weinstein(sym, df, spy)
        print(f"{sym}: done")

    all_trades, curves, stats_rows = [], {}, {}
    for name, rows in systems.items():
        t = pd.DataFrame(rows)
        if t.empty:
            continue
        t["system"] = name
        all_trades.append(t)
        eq, taken = portfolio(t, closes, start)
        curves[name] = eq
        tt = t[t.entry_date > start]
        stats_rows[name] = {"n": len(tt), "taken": taken, "win": (tt.ret > 0).mean(), "avg": tt.ret.mean(),
                            "days": tt.days.mean()}
    pd.concat(all_trades).to_csv(TRADES, index=False)

    stocks = closes[stock_syms]
    atrs = pd.DataFrame({s: G.atr(data[s], 20) for s in stock_syms})
    def curve(r):
        return START_USD * (1 + r[r.index > start]).cumprod()
    curves["Clenow momentum (Stocks on the Move)"] = curve(clenow(stocks, spy.Close, atrs))
    curves["Benchmark: hold the whole popular list equally"] = curve(equal_weight(stocks))
    curves["Benchmark: SPY buy & hold"] = curve(closes["SPY"].pct_change().fillna(0.0))
    q, tq = closes["QQQ"], closes["TQQQ"]
    mix = 0.67 * S.trend_hold(tq, q) + 0.33 * S.trend_hold(q, q)
    curves["Benchmark: 67% TQQQ + 33% QQQ trend"] = curve(mix)

    res = {k: S.summarize(v) for k, v in curves.items()}
    order = sorted(res, key=lambda k: -res[k]["final"])
    first, last = curves["Benchmark: SPY buy & hold"].index[[0, -1]]
    out = [f"# Famous traders' swing systems: ${START_USD:,.0f} start, {first.date()} to {last.date()}\n",
           f"Run {dt.date.today()}. {len(stock_syms)} stocks ({src} list). Trade systems risk {RISK_PCT:g}% of equity "
           f"at the initial stop, max {CAP_PCT:g}% per position, cash only, {G.SLIP_BPS:g} bps slippage per fill, "
           "marked to market daily. Rules as published; details in swing_masters.py.\n",
           "**Survivorship warning:** the list is today's most popular stocks, so every long system here runs "
           "optimistic. Compare each system with 'hold the whole popular list equally': that row has the same "
           "bias, so beating it is the fair test.\n",
           "| system | ending $ | growth / yr | worst drop | worst year | 1st half / yr | 2nd half / yr | trades (taken) | win % | avg % / trade | avg days |",
           "|---|---|---|---|---|---|---|---|---|---|---|"]
    for k in order:
        r = res[k]
        st = stats_rows.get(k)
        extra = (f"{st['n']} ({st['taken']}) | {st['win']:.0%} | {st['avg']:+.2f}% | {st['days']:.0f}" if st
                 else "- | - | - | -")
        out.append(f"| {k} | ${r['final']:,.0f} | {r['cagr']:+.1%} | -{r['dd']:.0%} | {r['worst_yr']:+.0%} | "
                   f"{r['h1']:+.1%} | {r['h2']:+.1%} | {extra} |")
    yrs = sorted({y for r in res.values() for y in r["years"]})
    out += ["\n## Year by year\n", "| system | " + " | ".join(str(y) for y in yrs) + " |",
            "|---|" + "---|" * len(yrs)]
    for k in order:
        out.append(f"| {k} | " + " | ".join(f"{res[k]['years'].get(y, float('nan')):+.0%}" for y in yrs) + " |")
    text = "\n".join(out) + "\n"
    REPORT.write_text(text)
    print(text)
    G.step_summary(text)


if __name__ == "__main__":
    main()
