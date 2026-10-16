"""
Trend trader: 2/3 TQQQ + 1/3 QQQ while QQQ is above its 200-day average, cash otherwise.

Runs once a day after the close (GitHub Actions, same schedule as the grader) on the Alpaca PAPER
account (live URLs are refused):

  1. Reads QQQ's daily closes and its 200-day simple moving average.
  2. ON  (QQQ closed above the average): target TREND_TQQQ_PCT of equity in TQQQ and the rest of
     TREND_INVEST_PCT in QQQ. OFF (closed below): target cash.
  3. Trades when the signal flips, when a position is missing, or when either holding drifts more
     than TREND_BAND_PCT points of equity from its target. Orders are day market orders placed in the
     evening, so Alpaca fills them at the next open. Sells go by fractional quantity, buys by dollar
     amount, capped at the buying power left (anything short is topped up on a later evening).
  4. Anything else in the account (old swing-grader positions and orders) is cancelled and closed,
     so the account holds only this strategy. TREND_CLEAN_OTHERS=0 turns that off.

Pushes to your phone only when it trades or the signal flips. Logs orders to trend_trades.csv, the last run's output to trend_last_run.md,
daily equity to trend_equity.csv, and state to trend_state.json.

Backtest (strategies.py, 2016-10 to 2026-10): +34%/yr, worst drop -47%. The backtest switched at the
close; live trades fill at the next open, so results will differ a little.

  python trend_trader.py            normal evening run (skips outside the after-close window)
  FORCE_RUN=1 python trend_trader.py
"""
import datetime as dt
import json
import os
import time
from pathlib import Path

import pandas as pd

import grader as G

TQQQ_PCT = float(os.environ.get("TREND_TQQQ_PCT", "67"))
INVEST_PCT = float(os.environ.get("TREND_INVEST_PCT", "100"))
BAND_PCT = float(os.environ.get("TREND_BAND_PCT", "5"))
SMA = int(os.environ.get("TREND_SMA", "200"))
CLEAN_OTHERS = os.environ.get("TREND_CLEAN_OTHERS", "1") == "1"
FORCE = os.environ.get("FORCE_RUN") == "1"
SIGNAL, LEVERED, BASE = "QQQ", "TQQQ", "QQQ"
STATE = Path("trend_state.json")
TRADES = Path("trend_trades.csv")
EQUITY = Path("trend_equity.csv")
LAST_RUN = Path("trend_last_run.md")


def targets(on, equity):
    if not on:
        return {LEVERED: 0.0, BASE: 0.0}
    inv = equity * INVEST_PCT / 100
    return {LEVERED: inv * TQQQ_PCT / 100, BASE: inv * (100 - TQQQ_PCT) / 100}


def log_trade(rows):
    if not rows:
        return
    new = not TRADES.exists()
    with TRADES.open("a") as f:
        if new:
            f.write("date,symbol,side,amount,reason\n")
        f.write("\n".join(rows) + "\n")


def main():
    now = dt.datetime.now(G.ET)
    today = now.date()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if not G.PAPER:
        print("Alpaca paper keys missing (or a live URL): nothing to do.")
        return
    if not FORCE:
        if now.weekday() >= 5 or (now.hour, now.minute) < G.RUN_AFTER_ET:
            print("Outside the after-close window.")
            return
        if state.get("last_run") == str(today):
            print("Already ran today.")
            return

    px = G.yf.download([SIGNAL, LEVERED], period="2y", interval="1d", auto_adjust=True,
                       progress=False)["Close"].dropna()
    last_bar = px.index[-1].date()
    if not FORCE and last_bar != today:
        print(f"Latest bar is {last_bar}, not today (holiday?).")
        return
    q = px[SIGNAL]
    sma = q.rolling(SMA).mean()
    on = bool(q.iloc[-1] > sma.iloc[-1])
    prev = state.get("signal")
    flipped = prev is not None and prev != on

    notes, rows = [], []
    acct = G.ap("GET", "/v2/account")
    equity, bp = float(acct["equity"]), float(acct["buying_power"])

    def safe(label, fn):
        """Run one Alpaca call; on failure record why and carry on with the rest."""
        try:
            return fn(), True
        except Exception as e:
            notes.append(f"⚠ {label} failed: {str(e)[:160]}")
            return None, False

    def order(sym, side, amount=None, qty=None):
        """Market day order (fills at the next open). Tries dollars, then fractional shares, then
        whole shares, since Alpaca can refuse some fractional orders outside market hours."""
        price = last_px[sym]
        tries = []
        if amount is not None:
            tries.append({"notional": f"{amount:.2f}"})
            qty = amount / price
        tries += [{"qty": f"{qty:.6f}"}, {"qty": str(int(qty))}]
        for t in tries:
            if t.get("qty") == "0":
                continue
            try:
                G.ap("POST", "/v2/orders", json={"symbol": sym, "side": side, "type": "market",
                                                 "time_in_force": "day", **t})
                return t
            except Exception as e:
                last_err = str(e)[:160]
        notes.append(f"⚠ {side} {sym} failed: {last_err if tries else 'nothing to send'}")
        return None

    last_px = {s: float(px[s].iloc[-1]) for s in (LEVERED, BASE)}

    # 1) clear anything that isn't this strategy
    positions = {p["symbol"]: p for p in (G.ap("GET", "/v2/positions") or [])}
    if CLEAN_OTHERS:
        cancelled = []
        for o in G.ap("GET", "/v2/orders", params={"status": "open", "limit": 500}) or []:
            _, ok = safe(f"cancel {o['symbol']} order", lambda o=o: G.ap("DELETE", f"/v2/orders/{o['id']}"))
            if ok:
                cancelled.append(o["id"])
                notes.append(f"🚫 cancelled open {o['side']} order for {o['symbol']}")
        for _ in range(20):                                       # cancels are async: wait until done
            still = {o["id"] for o in G.ap("GET", "/v2/orders", params={"status": "open", "limit": 500}) or []}
            if not still & set(cancelled):
                break
            time.sleep(1)
        for sym in [s for s in positions if s not in (LEVERED, BASE)]:
            qty = abs(float(positions[sym]["qty"]))
            _, ok = safe(f"close {sym}", lambda sym=sym: G.ap("DELETE", f"/v2/positions/{sym}"))
            if not ok:
                p_ = positions[sym]
                last_px[sym] = float(p_.get("current_price") or float(p_["market_value"]) / qty)
                ok = order(sym, "sell", qty=qty) is not None
            if ok:
                notes.append(f"🧹 closing {sym} ({qty:g} sh) at the open: not part of the trend strategy")
                rows.append(f"{today},{sym},sell,{qty:g} sh,cleanup")
        positions = {s: p for s, p in positions.items() if s in (LEVERED, BASE)}

    # 2) rebalance toward the targets
    held = {s: float(positions[s]["market_value"]) if s in positions else 0.0 for s in (LEVERED, BASE)}
    tgt = targets(on, equity)
    band = equity * BAND_PCT / 100
    need = flipped or prev is None or any(
        abs(tgt[s] - held[s]) > band or (tgt[s] > 0 and held[s] == 0) or (tgt[s] == 0 and held[s] > 0)
        for s in tgt)
    if need:
        for s in (LEVERED, BASE):                                  # sells first
            diff = tgt[s] - held[s]
            if diff < -1:
                why = "signal off" if not on else "rebalance"
                if tgt[s] == 0:
                    _, ok = safe(f"close {s}", lambda s=s: G.ap("DELETE", f"/v2/positions/{s}"))
                    if not ok:
                        ok = order(s, "sell", qty=abs(float(positions[s]["qty"]))) is not None
                    if ok:
                        notes.append(f"🔻 sell all {s} (~{G.money(held[s])}) at the open")
                        rows.append(f"{today},{s},sell,all,{why}")
                else:
                    sent = order(s, "sell", qty=-diff / last_px[s])
                    if sent:
                        notes.append(f"🔻 sell ~{G.money(-diff)} of {s} at the open")
                        rows.append(f"{today},{s},sell,{list(sent.values())[0]} sh,{why}")
        # then buys; if buying power is short, scale every buy down by the same factor so the
        # TQQQ/QQQ mix stays on target (the rest goes in on a later evening)
        buys = {s: tgt[s] - held[s] for s in (LEVERED, BASE) if tgt[s] - held[s] > 1}
        scale = min(1.0, bp * 0.98 / sum(buys.values())) if buys else 1.0
        for s, diff in buys.items():
            amt = round(diff * scale, 2)
            if amt < 1:
                continue
            sent = order(s, "buy", amount=amt)
            if sent:
                how = f"${amt:.2f}" if "notional" in sent else f"{sent['qty']} sh"
                notes.append(f"🟢 buy {how} of {s} at the open")
                rows.append(f"{today},{s},buy,{how},{'signal on' if flipped or prev is None else 'rebalance'}")
        if buys and scale < 1:
            notes.append(f"   (cash covers {scale:.0%} of the target today; the rest goes in once cash frees up)")

    # 3) record and report
    state.update(signal=on, last_run=str(today), qqq=round(float(q.iloc[-1]), 2), sma=round(float(sma.iloc[-1]), 2))
    STATE.write_text(json.dumps(state, indent=1))
    log_trade(rows)
    new = not EQUITY.exists()
    with EQUITY.open("a") as f:
        if new:
            f.write("date,equity,signal\n")
        f.write(f"{today},{equity:.2f},{'on' if on else 'off'}\n")
    head = (f"QQQ {G.money(q.iloc[-1])} vs 200-day {G.money(sma.iloc[-1])}: "
            f"{'ON (67% TQQQ / 33% QQQ)' if on else 'OFF (cash)'}. Paper equity {G.money(equity)}.")
    print(head)
    print("\n".join(notes) or "No trades needed.")
    if flipped:
        G.send(f"Trend signal {'ON' if on else 'OFF'}", head + "\n" + "\n".join(notes), "high",
               "chart_with_upwards_trend" if on else "warning")
    elif notes:
        G.send("Trend trader", head + "\n" + "\n".join(notes), "default", "page_facing_up")
    text = f"## Trend trader, {now:%Y-%m-%d %H:%M} ET\n\n{head}\n\n" + (
        "\n".join(f"- {n}" for n in notes) or "No trades needed.") + "\n"
    LAST_RUN.write_text(text)
    G.step_summary(text)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:                                         # leave the reason in the repo
        LAST_RUN.write_text(f"## Trend trader failed {dt.datetime.now(G.ET):%Y-%m-%d %H:%M} ET\n\n"
                            f"{type(e).__name__}: {e}\n")
        raise
