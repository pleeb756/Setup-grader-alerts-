# Hold losers until +5%: 10-year test, 98 stocks (robinhood list)

Run 2026-10-16. Same signals and entries as swing_backtest.md. 'Normal' = the plan as it runs now; 'hold losers' = every losing exit skipped until price is back to +5% from entry. Trades still underwater at the end are marked at the last close (counted, not dropped).

**Survivorship warning matters most here:** the list is today's popular stocks, so stocks that fell and never came back (and dropped off the list) aren't in it. Real results of 'never sell at a loss' would be worse than shown.

## Per trade

| setup | version | trades | win % | avg % / trade | avg days held | longest hold (days) | worst open loss | still stuck at end |
|---|---|---|---|---|---|---|---|---|
| pullback | normal | 2524 | 65% | +0.23% | 4.2 | 11 | - | - |
| pullback | hold losers | 2524 | 98% | +2.66% | 46.7 | 2186 | -100% | 66 (avg -28%) |
| breakout | normal | 261 | 47% | +1.25% | 28.1 | 61 | - | - |
| breakout | hold losers | 261 | 98% | +5.38% | 112.4 | 1409 | -95% | 8 (avg -32%) |
| short_bounce | normal | 951 | 64% | +0.64% | 4.5 | 11 | - | - |
| short_bounce | hold losers | 951 | 93% | -27.66% | 124.8 | 2292 | -5634% | 68 (avg -446%) |
| breakdown | normal | 74 | 23% | -2.06% | 24.3 | 61 | - | - |
| breakdown | hold losers | 74 | 77% | -31.02% | 251.6 | 2290 | -939% | 17 (avg -158%) |

## Rescued trades: how long the wait was

| setup | losing trades | got back to +5% within 1 month | 3 months | 1 year | never (still stuck) |
|---|---|---|---|---|---|
| pullback | 892 | 31% | 59% | 83% | 7% |
| breakout | 139 | 18% | 47% | 78% | 6% |
| short_bounce | 344 | 35% | 55% | 70% | 20% |
| breakdown | 57 | 19% | 51% | 61% | 30% |

## $2,000 account (1% risk sizing at the original stop, max 35% per trade, cash only)

| setup | version | ending $ | growth / yr | worst drop (incl. open losses) | trades taken | signals skipped (no cash) |
|---|---|---|---|---|---|---|
| breakout | normal | $2,548 | +2.7% | -12% | 209 | 52 |
| breakout | hold losers | $4,849 | +10.2% | -23% | 162 | 99 |
| pullback | normal | $3,135 | +5.0% | -14% | 1601 | 923 |
| pullback | hold losers | $6,908 | +14.4% | -26% | 484 | 2040 |
