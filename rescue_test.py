"""
"Never sell at a loss" test: what if losing trades were held until they got back to +RESCUE_PCT,
and then either sold there or allowed to ride?

Rule tested (long setups only: a short held against you has no ceiling): each setup runs its
normal plan, but any exit that would close below the entry (initial stop, trailing stop below
entry, gap through the stop, time stop, a pullback's 5-day exit while underwater) is skipped.
The position is held until price reaches entry +RESCUE_PCT. Three versions from there:
  sell    sell at +RESCUE_PCT (or at the open if it gaps past)
  ride5   set the stop at +RESCUE_PCT, then trail it TRAIL_ATR x ATR behind the highest high
  ride0   same, but the first stop is breakeven
Exits that are already profitable happen as before. Trades still underwater on the last day are
marked at the last close and reported as "still stuck", never dropped.

Same signals, entries and one-position-per-stock rule as the main backtest; every version uses the
same trade list. While a rescued trade is open, that stock can't take a new signal for the setup.

Portfolio view: $START_USD account, each trade sized as the live plan sizes it (1% of equity at the
original stop distance, max 35% of equity, cash only), marked to market daily, so the worst drop
includes open losses and money tied up in stuck trades shows up as skipped signals.

Writes rescue_report.md and rescue_trades.csv.   python rescue_test.py
"""
import datetime as dt
import os
from pathlib import Path

import numpy as np
import pandas as pd

import grader as G

RESCUE_PCT = float(os.environ.get("RESCUE_PCT", "0.05"))
START_USD = 2000.0
REPORT = Path("rescue_report.md")


def rescue(setup, res, entry, bars, atr_, ride=None):
    """Continue a losing trade from its exit bar until it reaches entry + RESCUE_PCT.
    ride=None: sell at +RESCUE_PCT. ride="target": once there, set the stop at +RESCUE_PCT and
    trail it TRAIL_ATR x ATR behind the highest high. ride="entry": same, but the first stop is
    breakeven. Long setups only (a short held against you has no ceiling)."""
    slip = G.SLIP_BPS / 1e4
    target = entry * (1 + RESCUE_PCT)
    O, H, L, C = (bars[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    k0 = res["days"]                       # first bar after the bar the normal exit happened on
    worst, hit = 0.0, None
    for k in range(k0, len(O)):
        worst = max(worst, (entry - L[k]) / entry)
        if O[k] >= target or H[k] >= target:
            hit = k
            break
    if hit is None:
        return {"done": False, "exit_px": C[-1], "days": len(O), "worst": worst, "riding": False}
    if ride is None:
        px = O[hit] * (1 - slip) if O[hit] >= target else target
        return {"done": True, "exit_px": px, "days": hit + 1, "worst": worst, "riding": False}
    stop = target if ride == "target" else entry
    best = max(H[hit], target)
    stop = max(stop, best - G.TRAIL_ATR * atr_)
    for k in range(hit + 1, len(O)):
        if O[k] <= stop:
            return {"done": True, "exit_px": O[k] * (1 - slip), "days": k + 1, "worst": worst, "riding": False}
        if L[k] <= stop:
            return {"done": True, "exit_px": stop * (1 - slip), "days": k + 1, "worst": worst, "riding": False}
        best = max(best, H[k])
        stop = max(stop, best - G.TRAIL_ATR * atr_)       # takes effect from the next bar
    return {"done": True, "exit_px": C[-1], "days": len(O), "worst": worst, "riding": True}


VERSIONS = (("sell", None), ("ride5", "target"), ("ride0", "entry"))
LABELS = {"base": "normal (current plan)", "sell": "hold losers, sell at +5%",
          "ride5": "hold losers, then ride: stop at +5%, trail 4 ATR",
          "ride0": "hold losers, then ride: stop at breakeven, trail 4 ATR"}


def run_setup(df, setup):
    O, A, BL, BH, PV, REG, sig = G.setup_arrays(df, setup)
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        if i <= busy or i + 1 >= len(df) or not G.setup_allowed(setup, REG[i]):
            continue
        o = O[i + 1]
        if G.chased(setup, o, PV[i]):
            continue
        stop = G.initial_stop(setup, o * (1 + G.SLIP_BPS / 1e4), A[i], BL[i], BH[i])
        bars = df.iloc[i + 1:]
        res = G.simulate(setup, o, stop, A[i], bars)
        if not res["done"]:
            break                           # normal plan still open at the end (all versions)
        entry = res["entry"]
        row = {"sym": df.attrs["sym"], "setup": setup, "entry_date": bars.index[0], "entry": entry,
               "stop": stop, "rescued": res["r"] < 0, "worst": np.nan,
               "base_ret": res["ret_pct"], "base_days": res["days"], "base_exit": res["exit_date"]}
        for v, mode in VERSIONS:
            row.update({f"{v}_ret": res["ret_pct"], f"{v}_days": res["days"], f"{v}_exit": res["exit_date"],
                        f"{v}_stuck": False, f"{v}_riding": False})
        if res["r"] < 0:
            q = 0.5 if res["half"] else 1.0
            half_real = res["r"] - q * (res["exit_px"] - entry) / res["risk"] if res["half"] else 0.0
            for v, mode in VERSIONS:
                rr = rescue(setup, res, entry, bars, A[i], mode)
                r_new = half_real + q * (rr["exit_px"] - entry) / res["risk"]
                row.update({f"{v}_ret": r_new * res["risk"] / entry * 100, f"{v}_days": rr["days"],
                            f"{v}_exit": bars.index[rr["days"] - 1], f"{v}_stuck": not rr["done"],
                            f"{v}_riding": rr["riding"]})
                row["worst"] = rr["worst"] * 100
        rows.append(row)
        longest = max(row[f"{v}_days"] for v, _ in VERSIONS)
        busy = i + longest                   # same trade list for every version
        if longest >= len(bars):
            break
    return rows


def portfolio(t, ret_col, exit_col, closes):
    """$2,000 account, 1% risk at the original stop, max 35% per position, cash only.
    Open positions are marked to market every day, so the worst drop includes open losses."""
    if t.empty:
        return START_USD, 0.0, 0.0, 0, 0
    t = t.sort_values(["entry_date", "sym"]).reset_index(drop=True)
    days = closes.index[closes.index >= t.entry_date.min()]
    by_day = {d: g for d, g in t.groupby("entry_date")}
    cash, held, curve, taken, skipped = START_USD, [], [], 0, 0
    for day in days:
        # exits first (their proceeds are free cash for today's entries, like the next-open fills)
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
                if not np.isfinite(c):
                    c = h["last"]
                h["last"] = c
                v += h["n"] * (1 + h["d"] * (c / h["entry"] - 1))
            return v

        if day in by_day:
            for r in by_day[day].itertuples():
                eq = cash + mtm()
                sd = abs(r.entry - r.stop) / r.entry
                n = min(eq * 0.01 / sd, eq * 0.35, cash)
                if n < 1:
                    skipped += 1
                    continue
                cash -= n
                held.append({"sym": r.sym, "n": n, "ret": getattr(r, ret_col), "exit": getattr(r, exit_col),
                             "entry": r.entry, "d": G.SIGN[r.setup], "last": r.entry})
                taken += 1
        curve.append(cash + mtm())
    eqs = pd.Series(curve, index=days)
    years = (days[-1] - days[0]).days / 365.25
    mdd = float((1 - eqs / eqs.cummax()).max())
    return eqs.iloc[-1], (eqs.iloc[-1] / START_USD) ** (1 / years) - 1, mdd, taken, skipped


def main():
    syms, src = G.robinhood_top100()
    data = G.load_data(syms, f"{G.BT_YEARS}y")
    spy = data["SPY"]
    rows = []
    closes = pd.DataFrame({k: v.Close for k, v in data.items()})
    for sym in syms:
        if sym not in data or sym == "SPY":
            continue
        df = G.add_ind(data[sym].copy(), spy)
        df.attrs["sym"] = sym
        for s in ("breakout", "pullback"):
            rows += run_setup(df, s)
        print(f"{sym}: done")
    t = pd.DataFrame(rows)
    t.to_csv("rescue_trades.csv", index=False)

    out = [f"# Hold losers until +{RESCUE_PCT:.0%}, then sell or ride: {G.BT_YEARS}-year test, "
           f"{len(data) - 1} stocks ({src} list)\n",
           f"Run {dt.date.today()}. Long setups only (shorts held against you have no ceiling: an earlier run "
           "lost 28-31% per trade on average). Same signals and entries as swing_backtest.md; every version uses "
           "the same trade list. A 'losing exit' is any exit that would close below the entry. Ride versions: once "
           f"a rescued trade is back to +{RESCUE_PCT:.0%}, the stop goes to +{RESCUE_PCT:.0%} (or breakeven) and "
           f"then trails {G.TRAIL_ATR:g} ATR behind the highest high. Anything still underwater at the end is "
           "marked at the last close.\n",
           "**Survivorship warning:** stocks that fell and never came back dropped off today's popular list, so "
           "they aren't here. Real results of holding losers would be worse than shown.\n",
           "## Per trade\n",
           "| setup | version | trades | win % | avg % / trade | avg days held | still stuck underwater at end |",
           "|---|---|---|---|---|---|---|"]
    for s in ("breakout", "pullback"):
        x = t[t.setup == s]
        if x.empty:
            continue
        out.append(f"| {s} | {LABELS['base']} | {len(x)} | {(x.base_ret > 0).mean():.0%} | "
                   f"{x.base_ret.mean():+.2f}% | {x.base_days.mean():.1f} | - |")
        for v, _ in VERSIONS:
            st = x[x[f"{v}_stuck"]]
            out.append(f"| {s} | {LABELS[v]} | {len(x)} | {(x[f'{v}_ret'] > 0).mean():.0%} | "
                       f"{x[f'{v}_ret'].mean():+.2f}% | {x[f'{v}_days'].mean():.1f} | "
                       f"{len(st)}" + (f" (avg {st[f'{v}_ret'].mean():+.0f}%)" if len(st) else "") + " |")
        r = x[x.rescued]
        out.append(f"\n{s}: {len(r)} losing trades rescued. Worst open loss while waiting: -{r.worst.max():.0f}%. "
                   f"Rescued trades alone, avg result: sell at +5% {r.sell_ret.mean():+.1f}%, "
                   f"ride from +5% {r.ride5_ret.mean():+.1f}%, ride from breakeven {r.ride0_ret.mean():+.1f}%.\n")
        out += ["| setup | version | trades | win % | avg % / trade | avg days held | still stuck underwater at end |",
                "|---|---|---|---|---|---|---|"] if s == "breakout" else []

    out += ["\n## $2,000 account (1% risk sizing at the original stop, max 35% per trade, cash only, "
            "marked to market daily)\n",
            "| setup | version | ending $ | growth / yr | worst drop (incl. open losses) | trades taken | signals skipped (no cash) |",
            "|---|---|---|---|---|---|---|"]
    for s in ("breakout", "pullback"):
        x = t[t.setup == s]
        for v in ("base", "sell", "ride5", "ride0"):
            eq, cagr, mdd, n, sk = portfolio(x, f"{v}_ret", f"{v}_exit", closes)
            out.append(f"| {s} | {LABELS[v]} | ${eq:,.0f} | {cagr:+.1%} | -{mdd:.0%} | {n} | {sk} |")
    text = "\n".join(out) + "\n"
    REPORT.write_text(text)
    print(text)
    G.step_summary(text)


if __name__ == "__main__":
    main()
