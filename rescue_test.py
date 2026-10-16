"""
"Never sell at a loss" test: what if losing trades were held until they got back to +RESCUE_PCT?

Rule tested: each setup runs its normal plan, but any exit that would close at a loss (initial
stop, trailing stop below entry, gap through the stop, time stop, a pullback's 5-day exit while
underwater) is skipped. The position is held until price reaches entry +RESCUE_PCT (long) or
entry -RESCUE_PCT (short), and filled there (or at the open if it gaps past). Exits that are
already profitable happen as before. Trades still underwater on the last day are marked at the
last close and reported as "still stuck", never dropped.

Same signals, entries and one-position-per-stock rule as the main backtest. While a rescued
trade is stuck, that stock can't take a new signal for the same setup (as live would work).

Portfolio view: $START_USD account, each trade sized as the live plan sizes it (1% of equity at the
original stop distance, max 35% of equity, cash only), so the cost of money tied up in stuck
trades shows up as skipped signals.

Writes rescue_report.md.   python rescue_test.py
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


def rescue(setup, res, entry, bars):
    """Continue a losing trade from its exit bar until it reaches entry +/- RESCUE_PCT."""
    d = G.SIGN[setup]
    slip = G.SLIP_BPS / 1e4
    target = entry * (1 + d * RESCUE_PCT)
    O, H, L, C = (bars[k].to_numpy(float) for k in ("Open", "High", "Low", "Close"))
    fav = H if d > 0 else L
    k0 = res["days"]                       # first bar after the bar the normal exit happened on
    worst = 0.0
    for k in range(k0, len(O)):
        worst = max(worst, d * (entry - (L[k] if d > 0 else H[k])) / entry)
        if d * (O[k] - target) >= 0:
            return {"done": True, "exit_px": O[k] * (1 - d * slip), "days": k + 1, "worst": worst}
        if d * (fav[k] - target) >= 0:
            return {"done": True, "exit_px": target, "days": k + 1, "worst": worst}
    return {"done": False, "exit_px": C[-1], "days": len(O), "worst": worst}


def run_setup(df, setup):
    d = G.SIGN[setup]
    O, A, BL, BH, PV, REG, sig = G.setup_arrays(df, setup)
    rows, busy = [], -1
    for i in np.flatnonzero(sig):
        if i <= busy or i + 1 >= len(df) or not G.setup_allowed(setup, REG[i]):
            continue
        o = O[i + 1]
        if G.chased(setup, o, PV[i]):
            continue
        stop = G.initial_stop(setup, o * (1 + d * G.SLIP_BPS / 1e4), A[i], BL[i], BH[i])
        bars = df.iloc[i + 1:]
        res = G.simulate(setup, o, stop, A[i], bars)
        if not res["done"]:
            break                           # normal plan still open at the end (both versions)
        entry = res["entry"]
        base_ret = res["ret_pct"]
        row = {"sym": df.attrs["sym"], "setup": setup, "entry_date": bars.index[0], "entry": entry,
               "stop": stop, "base_ret": base_ret, "base_days": res["days"],
               "base_exit_date": res["exit_date"], "rescued": False, "stuck": False,
               "ret": base_ret, "days": res["days"], "exit_date": res["exit_date"], "worst": np.nan}
        if res["r"] < 0:
            rr = rescue(setup, res, entry, bars)
            half_real = (res["r"] - (0.5 if res["half"] else 1.0) * d * (res["exit_px"] - entry) / res["risk"]) \
                if res["half"] else 0.0
            q = 0.5 if res["half"] else 1.0
            r_new = half_real + q * d * (rr["exit_px"] - entry) / res["risk"]
            row.update(rescued=True, stuck=not rr["done"], ret=r_new * res["risk"] / entry * 100,
                       days=rr["days"], exit_date=bars.index[rr["days"] - 1], worst=rr["worst"] * 100)
        rows.append(row)
        busy = i + row["days"]
        if row["stuck"]:
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
        for s in G.SETUPS:
            rows += run_setup(df, s)
        print(f"{sym}: done")
    t = pd.DataFrame(rows)
    t.to_csv("rescue_trades.csv", index=False)

    out = [f"# Hold losers until +{RESCUE_PCT:.0%}: {G.BT_YEARS}-year test, {len(data) - 1} stocks ({src} list)\n",
           f"Run {dt.date.today()}. Same signals and entries as swing_backtest.md. 'Normal' = the plan as it runs now; "
           f"'hold losers' = every losing exit skipped until price is back to +{RESCUE_PCT:.0%} from entry. "
           "Trades still underwater at the end are marked at the last close (counted, not dropped).\n",
           "**Survivorship warning matters most here:** the list is today's popular stocks, so stocks that "
           "fell and never came back (and dropped off the list) aren't in it. Real results of 'never sell at "
           "a loss' would be worse than shown.\n",
           "## Per trade\n",
           "| setup | version | trades | win % | avg % / trade | avg days held | longest hold (days) | worst open loss | still stuck at end |",
           "|---|---|---|---|---|---|---|---|---|"]
    for s in G.SETUPS:
        x = t[t.setup == s]
        if x.empty:
            continue
        out.append(f"| {s} | normal | {len(x)} | {(x.base_ret > 0).mean():.0%} | {x.base_ret.mean():+.2f}% | "
                   f"{x.base_days.mean():.1f} | {x.base_days.max()} | - | - |")
        stuck = x[x.stuck]
        out.append(f"| {s} | hold losers | {len(x)} | {(x.ret > 0).mean():.0%} | {x.ret.mean():+.2f}% | "
                   f"{x.days.mean():.1f} | {x.days.max()} | -{x.worst.max():.0f}% | "
                   f"{len(stuck)} (avg {stuck.ret.mean():+.0f}%) |" if len(stuck) else
                   f"| {s} | hold losers | {len(x)} | {(x.ret > 0).mean():.0%} | {x.ret.mean():+.2f}% | "
                   f"{x.days.mean():.1f} | {x.days.max()} | -{x.worst.max():.0f}% | 0 |")

    out += ["\n## Rescued trades: how long the wait was\n",
            "| setup | losing trades | got back to +5% within 1 month | 3 months | 1 year | never (still stuck) |",
            "|---|---|---|---|---|---|"]
    for s in G.SETUPS:
        x = t[(t.setup == s) & t.rescued]
        if x.empty:
            continue
        wait = x.days - x.base_days
        ok = ~x.stuck
        out.append(f"| {s} | {len(x)} | {((wait <= 21) & ok).mean():.0%} | {((wait <= 63) & ok).mean():.0%} | "
                   f"{((wait <= 252) & ok).mean():.0%} | {x.stuck.mean():.0%} |")

    out += ["\n## $2,000 account (1% risk sizing at the original stop, max 35% per trade, cash only)\n",
            "| setup | version | ending $ | growth / yr | worst drop (incl. open losses) | trades taken | signals skipped (no cash) |",
            "|---|---|---|---|---|---|---|"]
    for s in ("breakout", "pullback"):
        x = t[t.setup == s]
        for label, rc, ec in (("normal", "base_ret", "base_exit_date"), ("hold losers", "ret", "exit_date")):
            eq, cagr, mdd, n, sk = portfolio(x, rc, ec, closes)
            out.append(f"| {s} | {label} | ${eq:,.0f} | {cagr:+.1%} | -{mdd:.0%} | {n} | {sk} |")
    text = "\n".join(out) + "\n"
    REPORT.write_text(text)
    print(text)
    G.step_summary(text)


if __name__ == "__main__":
    main()
