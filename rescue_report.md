# Hold losers until +5%, then sell or ride: 10-year test, 98 stocks (robinhood list)

Run 2026-10-16. Long setups only (shorts held against you have no ceiling: an earlier run lost 28-31% per trade on average). Same signals and entries as swing_backtest.md; every version uses the same trade list. A 'losing exit' is any exit that would close below the entry. Ride versions: once a rescued trade is back to +5%, the stop goes to +5% (or breakeven) and then trails 4 ATR behind the highest high. Anything still underwater at the end is marked at the last close.

**Survivorship warning:** stocks that fell and never came back dropped off today's popular list, so they aren't here. Real results of holding losers would be worse than shown.

## Per trade

| setup | version | trades | win % | avg % / trade | avg days held | still stuck underwater at end |
|---|---|---|---|---|---|---|
| breakout | normal (current plan) | 244 | 48% | +1.24% | 28.0 | - |
| breakout | hold losers, sell at +5% | 244 | 98% | +5.28% | 111.0 | 7 (avg -37%) |
| breakout | hold losers, then ride: stop at +5%, trail 4 ATR | 244 | 96% | +5.50% | 114.3 | 7 (avg -37%) |
| breakout | hold losers, then ride: stop at breakeven, trail 4 ATR | 244 | 85% | +6.42% | 124.8 | 7 (avg -37%) |

breakout: 128 losing trades rescued. Worst open loss while waiting: -95%. Rescued trades alone, avg result: sell at +5% +2.8%, ride from +5% +3.2%, ride from breakeven +5.0%.

| setup | version | trades | win % | avg % / trade | avg days held | still stuck underwater at end |
|---|---|---|---|---|---|---|
| pullback | normal (current plan) | 2253 | 65% | +0.23% | 4.2 | - |
| pullback | hold losers, sell at +5% | 2253 | 98% | +2.61% | 46.5 | 61 (avg -29%) |
| pullback | hold losers, then ride: stop at +5%, trail 4 ATR | 2253 | 97% | +2.86% | 48.2 | 61 (avg -29%) |
| pullback | hold losers, then ride: stop at breakeven, trail 4 ATR | 2253 | 87% | +3.51% | 55.0 | 61 (avg -29%) |

pullback: 780 losing trades rescued. Worst open loss while waiting: -100%. Rescued trades alone, avg result: sell at +5% +2.6%, ride from +5% +3.3%, ride from breakeven +5.2%.


## $2,000 account (1% risk sizing at the original stop, max 35% per trade, cash only, marked to market daily)

| setup | version | ending $ | growth / yr | worst drop (incl. open losses) | trades taken | signals skipped (no cash) |
|---|---|---|---|---|---|---|
| breakout | normal (current plan) | $2,607 | +3.0% | -11% | 198 | 46 |
| breakout | hold losers, sell at +5% | $4,749 | +10.0% | -27% | 154 | 90 |
| breakout | hold losers, then ride: stop at +5%, trail 4 ATR | $4,806 | +10.1% | -30% | 150 | 94 |
| breakout | hold losers, then ride: stop at breakeven, trail 4 ATR | $4,474 | +9.2% | -29% | 133 | 111 |
| pullback | normal (current plan) | $3,468 | +6.2% | -18% | 1521 | 732 |
| pullback | hold losers, sell at +5% | $8,936 | +17.7% | -31% | 542 | 1711 |
| pullback | hold losers, then ride: stop at +5%, trail 4 ATR | $10,555 | +19.8% | -24% | 568 | 1685 |
| pullback | hold losers, then ride: stop at breakeven, trail 4 ATR | $5,929 | +12.5% | -43% | 449 | 1804 |
