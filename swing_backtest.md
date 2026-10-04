# Swing backtest: 10 years, 98 stocks (robinhood list)

Run 2026-10-04. Entries at the next open, 5 bps slippage per fill, no commissions. R = profit / initial risk. One position per stock per setup. 32 breakouts skipped for gapping more than 5%; 16 trades still open at the end left out.

**Caution:** this list is today's most popular stocks, chosen partly because they went up (survivorship bias), so treat results as optimistic. The 'vs drift' column subtracts each stock's own average daily move over the hold, which is the fairer test: positive means the signal beat just owning that stock.

Cells: n / win% / avg R / total R / profit factor.

## Strategy (regime filter on)

| setup | result | avg % / trade | vs drift % | avg days | max DD (R) | max open at once |
|---|---|---|---|---|---|---|
| pullback | 4538 / 64% / +0.04 / +181.5 / PF 1.20 | +0.28 | -0.11 | 4.2 | 110.4 | 47 |
| breakout | 294 / 44% / +0.13 / +37.8 / PF 1.45 | +0.90 | -0.64 | 19.3 | 8.4 | 15 |

## First half vs second half (split 2022-02-24)

If a setup only works in one half, it's fragile. Tune rules on the first half only.

| setup | first half | second half |
|---|---|---|
| pullback | 2221 / 64% / +0.02 / +36.4 / PF 1.07 | 2317 / 65% / +0.06 / +145.1 / PF 1.36 |
| breakout | 164 / 45% / +0.17 / +27.6 / PF 1.63 | 130 / 43% / +0.08 / +10.2 / PF 1.26 |

## Does the regime filter help?

| setup | SPY above 200-day | SPY below 200-day (filter skips these) | all signals |
|---|---|---|---|
| pullback | 4527 / 65% / +0.04 / +182.7 / PF 1.20 | 345 / 61% / -0.02 / -6.9 / PF 0.92 | 4872 / 64% / +0.04 / +175.7 / PF 1.18 |
| breakout | 294 / 44% / +0.13 / +37.8 / PF 1.45 | 15 / 87% / +1.12 / +16.7 / PF 15.77 | 309 / 46% / +0.18 / +54.6 / PF 1.64 |

## By year (regime filter on)

| year | pullback | breakout |
|---|---|---|
| 2017 | 235 / 71% / +0.14 / +32.5 / PF 2.00 | 33 / 58% / +0.43 / +14.2 / PF 4.01 |
| 2018 | 381 / 56% / -0.10 / -36.2 / PF 0.69 | 32 / 38% / +0.03 / +1.0 / PF 1.07 |
| 2019 | 399 / 61% / -0.03 / -11.3 / PF 0.89 | 24 / 42% / +0.29 / +6.9 / PF 2.21 |
| 2020 | 418 / 67% / +0.01 / +5.5 / PF 1.05 | 31 / 52% / +0.17 / +5.3 / PF 1.70 |
| 2021 | 724 / 69% / +0.10 / +75.0 / PF 1.70 | 41 / 37% / -0.05 / -1.9 / PF 0.85 |
| 2022 | 69 / 39% / -0.42 / -29.1 / PF 0.21 | 8 / 38% / -0.05 / -0.4 / PF 0.85 |
| 2023 | 481 / 57% / -0.01 / -5.9 / PF 0.94 | 28 / 54% / +0.20 / +5.6 / PF 1.58 |
| 2024 | 758 / 66% / +0.10 / +77.7 / PF 1.63 | 45 / 53% / +0.30 / +13.4 / PF 2.45 |
| 2025 | 591 / 70% / +0.09 / +55.7 / PF 1.61 | 28 / 32% / -0.08 / -2.2 / PF 0.69 |
| 2026 | 482 / 64% / +0.04 / +17.7 / PF 1.21 | 24 / 29% / -0.17 / -4.0 / PF 0.65 |

## Exit reasons (regime filter on)

| setup | reason | n | avg R |
|---|---|---|---|
| breakout | gapped below stop | 58 | -0.01 |
| breakout | max hold | 11 | +1.44 |
| breakout | stop | 11 | -1.01 |
| breakout | trailing stop | 214 | +0.16 |
| pullback | closed above 5-day average | 3879 | +0.22 |
| pullback | gapped below stop | 105 | -1.24 |
| pullback | stop | 531 | -1.01 |
| pullback | time stop | 23 | -0.61 |

pullback: 64 of 97 stocks net positive. Avg best excursion 0.34R; 2% reached +1R.

breakout: 40 of 70 stocks net positive. Avg best excursion 0.94R; 37% reached +1R.

Per-trade detail: swing_bt_trades.csv

