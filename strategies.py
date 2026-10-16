"""
Strategy comparison: which approach grows a small account fastest, and how hard is the ride?

Replays CMP_YEARS of daily history and runs every strategy on the same $START_USD account:

  Benchmarks        SPY, QQQ and TQQQ bought once and held.
  Trend filters     Hold QQQ, or TQQQ (3x Nasdaq-100), while QQQ closed above its 200-day
                    average the day before; otherwise cash. A "2% band" version only switches
                    after QQQ moves 2% past the average, which cuts whipsaw trades.
  Momentum (stocks) On the first trading day of each month, hold the TOP_N stocks of the
                    Robinhood popular list with the best 6-month return that are above their own
                    200-day average, equal weight, while SPY is above its 200-day; else cash.
                    Today's popular list is survivorship-biased, so this one runs optimistic.
  Momentum (ETFs)   Same rule on the 11 S&P sector ETFs: no survivorship bias.
  Breakouts         The grader's breakout trades from swing_bt_trades.csv (run --backtest first),
                    sized to risk 1% of equity, max 35% in one position, cash only.

Signals use the prior day's close; switches pay COST_BPS per side. Fractional shares assumed
(Alpaca supports them). No taxes, no dividends beyond what Yahoo's adjusted prices include.

Writes strategies_report.md with growth per year, worst drop, worst calendar year, first half vs
second half, and a year-by-year table.

  python strategies.py
"""
import datetime as dt
import heapq
import os
from pathlib import Path

import numpy as np
import pandas as pd

import grader as G

CMP_YEARS = int(os.environ.get("CMP_YEARS", "10"))
START_USD = float(os.environ.get("START_USD", "2000"))
COST_BPS = float(os.environ.get("COST_BPS", "5"))
TOP_N = (3, 5)
LOOKBACK = 126                 # 6-month momentum
TREND = 200
BAND = 0.02
SECTORS = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
REPORT = Path("strategies_report.md")


# ---------------- data ----------------
def closes(symbols, years):
    raw = G.yf.download(sorted(set(symbols)), period=f"{years}y", interval="1d", auto_adjust=True,
                        threads=True, progress=False)["Close"]
    raw.index = pd.DatetimeIndex(raw.index).tz_localize(None) if raw.index.tz is not None else raw.index
    return raw.dropna(how="all")


# ---------------- strategy engines (each returns a daily return series) ----------------
def hold(px):
    return px.pct_change().fillna(0.0)


def trend_hold(asset, signal, band=0.0):
    """Hold `asset` while `signal` closed above its 200-day average (with an optional band)."""
    ma = signal.rolling(TREND).mean()
    state, pos = False, []
    for s, m in zip(signal, ma):
        if np.isfinite(m):
            if not state and s > m * (1 + band):
                state = True
            elif state and s < m * (1 - band):
                state = False
        pos.append(1.0 if state else 0.0)
    pos = pd.Series(pos, index=signal.index).shift(1).fillna(0.0)      # act on yesterday's close
    ret = asset.pct_change().fillna(0.0) * pos
    turnover = pos.diff().abs().fillna(0.0)
    return ret - turnover * COST_BPS / 1e4


def momentum(px, spy, top_n, use_regime=True):
    """Monthly rotation into the top_n by 6-month return that are above their 200-day."""
    rets = px.pct_change().fillna(0.0)
    mom = px / px.shift(LOOKBACK) - 1
    above = px > px.rolling(TREND).mean()
    spy_ok = spy > spy.rolling(TREND).mean()
    month = px.index.to_period("M")
    first_day = pd.Series(month, index=px.index) != pd.Series(month, index=px.index).shift(1)
    w = pd.DataFrame(0.0, index=px.index, columns=px.columns)
    cur = pd.Series(0.0, index=px.columns)
    for i, d in enumerate(px.index):
        if i > 0 and first_day.iloc[i]:
            prev = px.index[i - 1]                                   # decide on last month's final close
            cur = pd.Series(0.0, index=px.columns)
            if (not use_regime) or bool(spy_ok.loc[prev]):
                score = mom.loc[prev].where(above.loc[prev]).dropna()
                picks = score.nlargest(top_n).index
                if len(picks):
                    cur[picks] = 1.0 / top_n                         # unfilled slots stay in cash
        w.iloc[i] = cur.values
    held = w.shift(1).fillna(0.0)
    gross = (held * rets).sum(axis=1)
    # weights drift between rebalances; charge costs on the rebalance-day change in target weights
    turnover = w.diff().abs().sum(axis=1).fillna(0.0)
    return gross - turnover * COST_BPS / 1e4


def breakout_curve(index, risk=0.01, cap=0.35):
    """Daily equity curve of the grader's breakout trades (needs swing_bt_trades.csv)."""
    if not G.BT_TRADES.exists():
        return None
    t = pd.read_csv(G.BT_TRADES, parse_dates=["entry_date", "exit_date"])
    t = t[(t.variant == "filtered") & (t.setup == "breakout")].sort_values(["entry_date", "sym"])
    t["sd"] = (t.entry - t.stop).abs() / t.entry
    eq, open_, realized = START_USD, [], {}

    def close_until(d):
        nonlocal eq
        while open_ and open_[0][0] <= d:
            x, notional, ret = heapq.heappop(open_)
            eq += notional * ret / 100
            realized[x] = eq

    for r in t.itertuples():
        close_until(r.entry_date - pd.Timedelta(days=1))
        used = sum(n for _, n, _ in open_)
        notional = min(eq * risk / r.sd, eq * cap, eq - used)
        if notional < 1:
            continue
        heapq.heappush(open_, (r.exit_date, notional, r.ret_pct))
    close_until(pd.Timestamp.max - pd.Timedelta(days=2))
    curve = pd.Series(realized).sort_index()
    curve = curve[~curve.index.duplicated(keep="last")]
    return curve.reindex(index, method="ffill").fillna(START_USD)


# ---------------- stats ----------------
def summarize(eq):
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    cagr = (eq.iloc[-1] / eq.iloc[0]) ** (1 / years) - 1
    dd = (1 - eq / eq.cummax()).max()
    yr = eq.resample("YE").last()
    yr = yr / pd.concat([pd.Series([eq.iloc[0]], index=[eq.index[0]]), yr.iloc[:-1]]).values - 1
    mid = eq.index[0] + (eq.index[-1] - eq.index[0]) / 2
    h1, h2 = eq[eq.index <= mid], eq[eq.index > mid]

    def g(x):
        y = (x.index[-1] - x.index[0]).days / 365.25
        return (x.iloc[-1] / x.iloc[0]) ** (1 / y) - 1

    return {"final": eq.iloc[-1], "cagr": cagr, "dd": dd, "worst_yr": yr.min(), "h1": g(h1), "h2": g(h2),
            "years": {d.year: v for d, v in yr.items()}, "calmar": cagr / dd if dd > 0 else float("inf")}


def main():
    syms, src = G.robinhood_top100()
    px = closes(list(syms) + ["SPY", "QQQ", "TQQQ"] + SECTORS, CMP_YEARS + 2)
    start = px.index[-1] - pd.DateOffset(years=CMP_YEARS)
    spy, qqq, tqqq = px["SPY"], px["QQQ"], px["TQQQ"]
    stocks = px[[s for s in syms if s in px and s not in ("SPY", "QQQ", "TQQQ")]]
    sectors = px[[s for s in SECTORS if s in px]]

    runs = {
        "SPY buy & hold": hold(spy),
        "QQQ buy & hold": hold(qqq),
        "TQQQ buy & hold (3x, no filter)": hold(tqqq),
        "QQQ, 200-day filter": trend_hold(qqq, qqq),
        "TQQQ, QQQ 200-day filter": trend_hold(tqqq, qqq),
        "TQQQ, QQQ 200-day filter, 2% band": trend_hold(tqqq, qqq, BAND),
        "Sector ETF momentum, top 3": momentum(sectors, spy, 3),
    }
    for n in TOP_N:
        runs[f"Stock momentum, top {n} (popular list)"] = momentum(stocks, spy, n)
    runs["Stock momentum, top 3, no SPY filter"] = momentum(stocks, spy, 3, use_regime=False)

    curves = {k: START_USD * (1 + v[v.index > start]).cumprod() for k, v in runs.items()}
    bo = breakout_curve(curves["SPY buy & hold"].index)
    if bo is not None:
        curves["Breakouts (grader), 1% risk"] = bo
    # half TQQQ trend + half stock momentum, rebalanced monthly
    mix = 0.5 * runs["TQQQ, QQQ 200-day filter, 2% band"] + 0.5 * runs["Stock momentum, top 5 (popular list)"]
    curves["50% TQQQ trend + 50% stock momentum top 5"] = START_USD * (1 + mix[mix.index > start]).cumprod()

    res = {k: summarize(v) for k, v in curves.items()}
    order = sorted(res, key=lambda k: -res[k]["final"])
    first, last = curves["SPY buy & hold"].index[[0, -1]]
    out = [f"# Strategy comparison: ${START_USD:,.0f} start, {first.date()} to {last.date()}\n",
           f"Run {dt.date.today()}. Signals use the prior close; {COST_BPS:g} bps per switch; fractional shares; "
           f"no taxes. Stock list: {len(stocks.columns)} names ({src}).\n",
           "**Survivorship warning:** the stock list is today's most popular names, which are popular partly "
           "because they went up. Stock momentum and breakouts run optimistic. The sector-ETF and QQQ/TQQQ "
           "rows have no such bias.\n",
           "Calmar = growth per year ÷ worst drop (higher = more growth per unit of pain).\n",
           "| strategy | ending $ | growth / yr | worst drop | worst year | 1st half / yr | 2nd half / yr | Calmar |",
           "|---|---|---|---|---|---|---|---|"]
    for k in order:
        r = res[k]
        out.append(f"| {k} | ${r['final']:,.0f} | {r['cagr']:+.1%} | -{r['dd']:.0%} | {r['worst_yr']:+.0%} | "
                   f"{r['h1']:+.1%} | {r['h2']:+.1%} | {r['calmar']:.2f} |")
    yrs = sorted({y for r in res.values() for y in r["years"]})
    out += ["\n## Year by year\n", "| strategy | " + " | ".join(str(y) for y in yrs) + " |",
            "|---|" + "---|" * len(yrs)]
    for k in order:
        out.append(f"| {k} | " + " | ".join(f"{res[k]['years'].get(y, float('nan')):+.0%}" for y in yrs) + " |")
    text = "\n".join(out) + "\n"
    REPORT.write_text(text)
    print(text)
    G.step_summary(text)


if __name__ == "__main__":
    main()
