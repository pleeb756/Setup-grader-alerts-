"""
Paper trader + replay backtester for the A+ Setup Grader.

Reuses grader.py's own signal code (impulse, breakout, momentum shift, pullback grade), so
the paper trades are the alerts, not an approximation of them. Every signal becomes a
simulated trade with realistic handling:

  * entry at the latest closed 1H price when the signal is seen (not the stale bar the
    signal was measured on), with slippage against you
  * the alert's stop and target as absolute price levels; R is measured from YOUR entry
  * Kalshi-style fees on every entry and exit, stop fills slipped against you
  * a stop and target touched in the same 1H bar counts as the stop (conservative)
  * fixed dollar risk per trade (PT_RISK_USD), so results read in dollars and in R

Each trade is simulated three ways so management can be compared on the same signals:
  plan     full size to the alert's TP
  partial  half off at 1R, stop to entry on the rest
  wide     stop 1.5x further away (same $ risk, so smaller size), then managed as partial

Each trade also carries filter tags, so the report shows which rules would have helped:
  adx25     4H ADX >= 25 (a trending market, not a range)
  aligned   trade side matches the daily trend (close vs rising/falling daily EMA50)
  va_with   4H value area shows accepted imbalance in the trade's direction
  ob_ok     order-block tag is not in-against or blocked
  flow_with 4H money flow points the trade's way
  solo      first signal of its side in that run (the rest are the same market bet)
  best      adx25 + aligned + solo

Experiment: impulse_fade takes the opposite side of every impulse (the backtest showed
chasing impulses loses about 0.5R a trade). Stop just beyond the impulse bar's extreme
(+0.25 x 4H ATR), target back at the broken range level the impulse ran from.

Checkpoint reminder: every CHECKPOINT_N closed breakout paper trades (30, 60, 90...) the
live run sends a phone push with the breakout plan/ob_ok/solo results, as the cue to review
paper_summary.md. Needs NTFY_TOPIC in the Paper trader step's env.

Modes:
  python papertrade.py --live       open/resolve paper trades on the latest bars (every run)
  python papertrade.py --backtest   replay the last PT_DAYS of history (default 30)
  python papertrade.py --report     rebuild paper_summary.md from paper_trades.csv

Momentum shifts need 5m bars, and Kraken only serves about 2.5 days of them, so the
backtest can only replay shifts over that window. Impulse, breakout and grade signals
replay over the full PT_DAYS.
"""
import json, os, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import grader as G

# ---------- settings ----------
RISK_USD = float(os.environ.get("PT_RISK_USD", "2"))        # dollars lost at a full stop
FEE_BPS = float(os.environ.get("PT_FEE_BPS", "12"))         # per side, of notional (Kalshi ~0.12%)
SLIP_BPS = float(os.environ.get("PT_SLIP_BPS", "5"))        # entry and stop fills, against you
MAX_HOLD_HRS = int(os.environ.get("PT_MAX_HOLD_HRS", "168"))
DAYS = int(os.environ.get("PT_DAYS", "30"))                 # backtest window
USE_GRADE = os.environ.get("PT_GRADE", "1") == "1"          # include pullback-grade signals
WIDE_MULT = 1.5
ADX_MIN = 25.0
SIMS = ("plan", "partial", "wide")
FILTERS = ("all", "adx25", "aligned", "va_with", "ob_ok", "flow_with", "solo", "best")
KINDS = ("impulse", "impulse_fade", "breakout", "shift", "grade")
FADE_BUF_ATR = 0.25     # fade stop: this many 4H ATRs beyond the impulse bar's extreme
CHECKPOINT_N = int(os.environ.get("PT_CHECKPOINT_N", "30"))  # breakout trades per review push

STATE = Path("paper_state.json")
TRADES = Path("paper_trades.csv")
SUMMARY = Path("paper_summary.md")
BT_REPORT = Path("backtest_report.md")
BT_TRADES = Path("backtest_trades.csv")

H1, H4, D1 = 3600, 4 * 3600, 86400


# ---------- indicators ----------
def adx(df, n=14):
    h, l, c = (df[k].to_numpy(float) for k in ("h", "l", "c"))
    if len(c) < 2 * n + 2:
        return float("nan")
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


def daily_bias(d):
    if len(d) < 60:
        return "flat"
    e = G.ema(d.c, 50)
    c, now, before = d.c.iloc[-1], e.iloc[-1], e.iloc[-6]
    if c > now and now > before:
        return "up"
    if c < now and now < before:
        return "down"
    return "flat"


# ---------- signals (grader.py logic, evaluated as of one moment) ----------
def signals_at(coin, d, h4, h1, m15, m5, T):
    """Signals visible at time T from closed bars only. Entry is the latest 1H close."""
    out = []
    if len(h1) < 60 or len(h4) < 80 or len(d) < 60:
        return out
    px = float(h1.c.iloc[-1])

    im = G.impulse(h1, h4)
    if im and int(h1.t.iloc[-1]) + H1 == T:                  # only on the bar that just closed
        out.append({"kind": "impulse", "side": im["side"], "stop": im["stop"],
                    "target": im["target"], "score": "-", "key": f"{coin}|impulse|{im['bar']}"})
        # the experiment: fade it back toward the level it broke
        bar = h1.iloc[-1]
        buf = FADE_BUF_ATR * float(G.atr(h4).iloc[-1])
        if im["side"] == "long":
            fade = {"side": "short", "stop": float(bar.h) + buf}
        else:
            fade = {"side": "long", "stop": float(bar.l) - buf}
        fade.update({"kind": "impulse_fade", "target": im["level"], "score": "-",
                     "key": f"{coin}|fade|{im['bar']}"})
        out.append(fade)

    if int(h4.t.iloc[-1]) + H4 == T:                          # a 4H bar just closed
        bo = G.breakout(d, h4)
        if bo:
            plan = G.breakout_plan(bo[0], bo[1], h4)
            if plan:
                out.append({"kind": "breakout", "side": bo[0], "stop": plan["stop"],
                            "target": plan["target"], "score": "-",
                            "key": f"{coin}|breakout|{int(h4.t.iloc[-1])}"})

    if len(m15) >= 30 and len(m5) >= 30:
        ms = G.momentum_shift(h4, m15, m5)
        if ms and ms["score"] >= G.MS_MIN:
            out.append({"kind": "shift", "side": ms["side"], "stop": float(ms["stop"]),
                        "target": float(ms["tps"][2]), "score": f"{ms['score']}/7",
                        "key": f"{coin}|shift|{ms['bar']}|{ms['side']}"})

    if USE_GRADE:
        try:
            g = G.grade(d, h4, h1)
        except Exception:
            g = None
        if g and g["grade"] in ("A+", "B+") and g["stop"] is not None:
            out.append({"kind": "grade", "side": g["side"], "stop": g["stop"],
                        "target": g["target"], "score": g["grade"],
                        "key": f"{coin}|grade|{int(h4.t.iloc[-1])}|{g['side']}"})

    if not out:
        return out
    # context tags, computed once per coin and moment
    a4 = float(G.atr(h4).iloc[-1])
    obs = G.order_blocks(h4)
    fl = G.flow_state(h4)
    adx4 = adx(h4)
    bias = daily_bias(d)
    F = G._cols(h4)
    keep = []
    for s in out:
        L = s["side"] == "long"
        dsg = 1 if L else -1
        if not (np.isfinite(s["stop"]) and np.isfinite(s["target"])):
            continue
        # the alert's levels must still make sense from the current price
        if (px - s["stop"]) * dsg <= 0 or (s["target"] - px) * dsg <= 0:
            continue
        va = G.value_state(F, px, L)["state"]
        ob_tag, _ = G.ob_info(obs, s["side"], px, s["target"], a4)
        s.update({
            "coin": coin, "t": int(T), "entry": px,
            "adx": round(adx4, 1) if np.isfinite(adx4) else "",
            "adx25": bool(np.isfinite(adx4) and adx4 >= ADX_MIN),
            "aligned": (bias == "up" and L) or (bias == "down" and not L),
            "va": va, "va_with": va == ("imbalance_up" if L else "imbalance_down"),
            "ob": ob_tag, "ob_ok": ob_tag not in ("in-against", "blocked"),
            "flow": fl["label"], "flow_with": fl["dir"] == dsg,
        })
        keep.append(s)
    return keep


def tag_clusters(sigs):
    """solo = first signal of its side at that moment; the rest are the same market bet."""
    seen = set()
    for s in sorted(sigs, key=lambda x: (x["t"], list(G.WATCHLIST).index(x["coin"]))):
        k = (s["t"], s["side"], s["kind"] == "impulse_fade")   # the experiment is its own group
        s["solo"] = k not in seen
        seen.add(k)
        s["best"] = s["adx25"] and s["aligned"] and s["solo"]
    return sigs


# ---------- trade simulation ----------
def simulate(sig, h1, mode, now=None):
    """Replay closed 1H bars after the signal. Returns a result dict, or None if still open."""
    L = sig["side"] == "long"
    d = 1 if L else -1
    slip, fee = SLIP_BPS / 1e4, FEE_BPS / 1e4
    entry = sig["entry"] * (1 + d * slip)
    risk = abs(entry - sig["stop"])
    if risk <= 0:
        return {"outcome": "invalid", "r": 0.0, "pnl": 0.0, "mfe_r": 0.0, "hours": 0.0, "exit_t": sig["t"]}
    tgt_r = abs(sig["target"] - entry) / risk
    if mode == "wide":
        risk *= WIDE_MULT
    stop = entry - d * risk
    target = entry + d * tgt_r * risk
    one_r = entry + d * risk
    qty = RISK_USD / risk
    cost = entry * qty * fee
    open_q, pnl, partial_done, mfe = 1.0, 0.0, False, 0.0
    bars = h1[h1.t >= sig["t"]]
    exit_t, outcome = None, None

    def close(q, price, slipped):
        px = price * (1 - d * slip) if slipped else price
        return q * qty * (px - entry) * d - q * qty * px * fee

    for b in bars.itertuples():
        mfe = max(mfe, ((b.h - entry) if L else (entry - b.l)) / risk)
        hit_stop = b.l <= stop if L else b.h >= stop
        if hit_stop:
            pnl += close(open_q, stop, True)
            open_q, exit_t = 0.0, b.t + H1
            outcome = "breakeven" if partial_done else "loss"
            break
        if mode != "plan" and not partial_done and (b.h >= one_r if L else b.l <= one_r):
            pnl += close(0.5, one_r, False)
            open_q, partial_done, stop = 0.5, True, entry
            if b.l <= entry if L else b.h >= entry:        # same bar came back to entry
                pnl += close(open_q, entry, True)
                open_q, exit_t, outcome = 0.0, b.t + H1, "breakeven"
                break
        if b.h >= target if L else b.l <= target:
            pnl += close(open_q, target, False)
            open_q, exit_t, outcome = 0.0, b.t + H1, "win"
            break
        if b.t + H1 - sig["t"] >= MAX_HOLD_HRS * H1:
            pnl += close(open_q, b.c, True)
            open_q, exit_t, outcome = 0.0, b.t + H1, "time"
            break
    if outcome is None:
        return None
    pnl -= cost
    return {"outcome": outcome, "r": round(pnl / RISK_USD, 3), "pnl": round(pnl, 2),
            "mfe_r": round(mfe, 2), "hours": round((exit_t - sig["t"]) / H1, 1), "exit_t": int(exit_t)}


def flatten(sig, results):
    row = {k: sig[k] for k in ("coin", "kind", "side", "score", "t", "entry", "stop", "target",
                               "adx", "va", "ob", "flow", "adx25", "aligned", "va_with",
                               "ob_ok", "flow_with", "solo", "best")}
    row["time_utc"] = G.stamp(sig["t"])
    for m in SIMS:
        res = results[m]
        for k in ("outcome", "r", "pnl", "mfe_r", "hours"):
            row[f"{m}_{k}"] = res[k]
    return row


# ---------- reporting ----------
def stats(df, sim):
    r = df[f"{sim}_r"].astype(float)
    if r.empty:
        return None
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    eq = r.cumsum()
    dd = float((eq.cummax() - eq).max()) if len(eq) else 0.0
    return {"n": len(r), "win": 100 * (r > 0).mean(), "avg": r.mean(), "tot": r.sum(),
            "pf": (wins / losses) if losses > 0 else float("inf"), "dd": dd}


def report_md(df, title, note=""):
    if df.empty:
        return f"# {title}\n\n{note}\nNo closed trades yet.\n"
    df = df.sort_values("t")
    out = [f"# {title}\n", f"Risk ${RISK_USD:g}/trade, fees {FEE_BPS:g} bps/side, slippage "
           f"{SLIP_BPS:g} bps. R is net of costs. Win = net R > 0.\n", note,
           "Cells: n / win% / avg R / total R. Look for rows that stay positive with n >= 30.\n"]
    for kind in ("ALL",) + KINDS:
        sub = df if kind == "ALL" else df[df.kind == kind]
        if sub.empty:
            continue
        out.append(f"\n## {kind} ({len(sub)} signals)\n")
        out.append("| filter | " + " | ".join(SIMS) + " |")
        out.append("|---|" + "---|" * len(SIMS))
        for f in FILTERS:
            s2 = sub if f == "all" else sub[sub[f].astype(str).str.lower() == "true"]
            cells = []
            for m in SIMS:
                st = stats(s2, m)
                cells.append("-" if not st else
                             f"{st['n']} / {st['win']:.0f}% / {st['avg']:+.2f} / {st['tot']:+.1f}")
            out.append(f"| {f} | " + " | ".join(cells) + " |")
    st = stats(df, "partial")
    if st:
        out.append(f"\nAll signals, partial management: profit factor {st['pf']:.2f}, "
                   f"max drawdown {st['dd']:.1f}R (${st['dd'] * RISK_USD:.0f}).\n")
    return "\n".join(out) + "\n"


def write_step_summary(text):
    step = os.environ.get("GITHUB_STEP_SUMMARY")
    if step:
        with open(step, "a") as f:
            f.write(text)


# ---------- data ----------
def fetch(pair):
    d, h4, h1 = G.candles(pair, 1440), G.candles(pair, 240), G.candles(pair, 60)
    try:
        m15, m5 = G.candles(pair, 15), G.candles(pair, 5)
    except Exception:
        m15 = m5 = h1.iloc[:0]
    return d, h4, h1, m15, m5


def upto(df, step, T):
    """Bars closed by time T (all columns, original order)."""
    n = int(np.searchsorted(df.t.to_numpy() + step, T, side="right"))
    return df.iloc[:n]


# ---------- backtest ----------
def backtest():
    t0 = time.time()
    sigs, data = [], {}
    for coin, pair in G.WATCHLIST.items():
        try:
            data[coin] = fetch(pair)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}")
            continue
        d, h4, h1, m15, m5 = data[coin]
        end = int(h1.t.iloc[-1]) + H1
        start = max(end - DAYS * D1, int(h1.t.iloc[0]) + 80 * H1)
        busy_until, seen = {}, set()
        n0 = len(sigs)
        for T in range(start - start % H1, end + 1, H1):
            h1_T = upto(h1, H1, T)
            if len(h1_T) == 0 or int(h1_T.t.iloc[-1]) + H1 != T:
                continue                                   # no bar closed at T (metals off-hours)
            try:
                found = signals_at(coin, upto(d, D1, T), upto(h4, H4, T), h1_T,
                                   upto(m15, 900, T), upto(m5, 300, T), T)
            except Exception as e:
                print(f"{coin} {G.stamp(T)}: {e}")
                continue
            for s in found:
                if s["key"] in seen or busy_until.get(s["kind"], 0) > T:
                    continue
                seen.add(s["key"])
                res = {m: simulate(s, h1, m) for m in SIMS}
                if any(r is None for r in res.values()):
                    continue                               # still open at the end of the data
                s["_res"] = res
                busy_until[s["kind"]] = max(r["exit_t"] for r in res.values())
                sigs.append(s)
        print(f"{coin}: {len(sigs) - n0} signals")
    tag_clusters(sigs)
    rows = [flatten(s, s["_res"]) for s in sigs]
    df = pd.DataFrame(rows)
    df.to_csv(BT_TRADES, index=False)
    m5_days = min((len(v[4]) * 300 / D1 for v in data.values() if len(v[4])), default=0)
    note = (f"Replayed {DAYS} days on 1H steps. Momentum shifts only cover about "
            f"{m5_days:.1f} days (Kraken's 5m history), so their sample is small.\n")
    text = report_md(df, f"Backtest: last {DAYS} days", note)
    BT_REPORT.write_text(text)
    print(text)
    write_step_summary(text)
    print(f"done in {time.time() - t0:.0f}s")


# ---------- live paper trading ----------
def live():
    state = json.loads(STATE.read_text()) if STATE.exists() else {"open": [], "seen": {}}
    now = time.time()
    new_rows, fresh = [], []
    open_by = {(t["coin"], t["kind"]) for t in state["open"]}
    for coin, pair in G.WATCHLIST.items():
        try:
            d, h4, h1, m15, m5 = fetch(pair)
            time.sleep(1)
        except Exception as e:
            print(f"skip {coin}: {e}")
            continue
        # resolve open paper trades for this coin
        keep = []
        for tr in state["open"]:
            if tr["coin"] != coin:
                keep.append(tr)
                continue
            res = {m: simulate(tr, h1, m) for m in SIMS}
            if all(r is not None for r in res.values()):
                new_rows.append(flatten(tr, res))
                print(f"{coin}: paper {tr['kind']} {tr['side']} closed "
                      f"plan {res['plan']['r']:+.2f}R / partial {res['partial']['r']:+.2f}R")
            else:
                keep.append(tr)
        state["open"] = keep
        open_by = {(t["coin"], t["kind"]) for t in keep}
        # new signals on the latest closed bars
        T = int(h1.t.iloc[-1]) + H1
        try:
            found = signals_at(coin, d, h4, h1, m15, m5, T)
        except Exception as e:
            print(f"{coin}: signal error {e}")
            continue
        for s in found:
            if s["key"] in state["seen"] or (coin, s["kind"]) in open_by:
                continue
            state["seen"][s["key"]] = now
            fresh.append(s)
            open_by.add((coin, s["kind"]))
    tag_clusters(fresh)
    for s in fresh:
        state["open"].append({k: (bool(v) if isinstance(v, (bool, np.bool_)) else v)
                              for k, v in s.items()})
        print(f"{s['coin']}: paper OPEN {s['kind']} {s['side']} @ {G.fmt(s['entry'])} "
              f"SL {G.fmt(s['stop'])} TP {G.fmt(s['target'])} | adx {s['adx']} "
              f"{'aligned' if s['aligned'] else 'counter'} | {s['va']} | OB {s['ob']}")
    # forget dedupe keys older than two weeks
    state["seen"] = {k: v for k, v in state["seen"].items() if now - v < 14 * D1}
    STATE.write_text(json.dumps(state, indent=1, default=float))
    if new_rows:
        df_new = pd.DataFrame(new_rows)
        df_new.to_csv(TRADES, mode="a", header=not TRADES.exists(), index=False)
    checkpoint(state)
    STATE.write_text(json.dumps(state, indent=1, default=float))
    write_summary(state)


def checkpoint(state):
    """Push a review reminder each time closed breakout paper trades pass a multiple of CHECKPOINT_N."""
    if not TRADES.exists():
        return
    df = pd.read_csv(TRADES)
    bo = df[df.kind == "breakout"]
    reached = len(bo) // CHECKPOINT_N * CHECKPOINT_N
    if reached < CHECKPOINT_N or state.get("checkpoint", 0) >= reached:
        return
    lines = [f"📊 PAPER CHECKPOINT: {len(bo)} breakout paper trades closed",
             "Time to review paper_summary.md (plan = hold to TP):"]
    for label, sub in (("all", bo), ("ob_ok", bo[bo.ob_ok.astype(str).str.lower() == "true"]),
                       ("solo", bo[bo.solo.astype(str).str.lower() == "true"])):
        st = stats(sub, "plan")
        if st:
            lines.append(f"{label}: n={st['n']} win {st['win']:.0f}% avg {st['avg']:+.2f}R "
                         f"total {st['tot']:+.1f}R")
    lines.append("Backtest had ob_ok +0.17R, solo +0.43R. Still positive = edge holding.")
    G.send("\n".join(lines), urgent=True)
    state["checkpoint"] = reached
    print(f"checkpoint push sent at {reached} breakout trades")


def write_summary(state=None):
    state = state or (json.loads(STATE.read_text()) if STATE.exists() else {"open": []})
    df = pd.read_csv(TRADES) if TRADES.exists() else pd.DataFrame()
    open_lines = [f"- {t['coin']} {t['kind']} {t['side']} @ {G.fmt(t['entry'])} "
                  f"(SL {G.fmt(t['stop'])}, TP {G.fmt(t['target'])}) since {G.stamp(t['t'])} UTC"
                  for t in state["open"]]
    note = (f"{len(df)} closed, {len(state['open'])} open. Updated {G.stamp(time.time())} UTC.\n\n"
            "Open paper trades:\n" + ("\n".join(open_lines) if open_lines else "- none") + "\n")
    text = report_md(df, "Paper trading (live alerts)", note)
    SUMMARY.write_text(text)
    return text


def main():
    if "--backtest" in sys.argv:
        backtest()
    elif "--report" in sys.argv:
        text = write_summary()
        print(text)
        write_step_summary(text)
    else:
        live()


if __name__ == "__main__":
    main()
