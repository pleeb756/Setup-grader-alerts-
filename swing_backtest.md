# Swing backtest: 10 years, 98 stocks (robinhood list)

Run 2026-10-09. Entries at the next open, 5 bps slippage per fill, no commissions. R = profit / initial risk. One position per stock per setup. 32 breakouts skipped for gapping more than 5%; 8 trades still open at the end left out.

**Caution:** this list is today's most popular stocks, chosen partly because they went up (survivorship bias), so treat results as optimistic. The 'vs drift' column subtracts each stock's own average daily move over the hold, which is the fairer test: positive means the signal beat just owning that stock.

Cells: n / win% / avg R / total R / profit factor.

## Strategy (regime filter on)

| setup | result | avg % / trade | vs drift % | avg days | max DD (R) | max open at once |
|---|---|---|---|---|---|---|
| pullback | 4548 / 64% / +0.04 / +184.0 / PF 1.21 | +0.28 | -0.11 | 4.2 | 110.8 | 47 |
| breakout | 293 / 44% / +0.13 / +37.2 / PF 1.44 | +0.88 | -0.65 | 19.1 | 8.4 | 15 |

## First half vs second half (split 2022-02-28)

If a setup only works in one half, it's fragile. Tune rules on the first half only.

| setup | first half | second half |
|---|---|---|
| pullback | 2216 / 64% / +0.02 / +37.3 / PF 1.08 | 2332 / 65% / +0.06 / +146.7 / PF 1.37 |
| breakout | 163 / 45% / +0.17 / +27.0 / PF 1.61 | 130 / 43% / +0.08 / +10.2 / PF 1.26 |

## Does the regime filter help?

| setup | SPY above 200-day | SPY below 200-day (filter skips these) | all signals |
|---|---|---|---|
| pullback | 4537 / 64% / +0.04 / +185.2 / PF 1.21 | 345 / 61% / -0.02 / -6.9 / PF 0.92 | 4882 / 64% / +0.04 / +178.3 / PF 1.18 |
| breakout | 293 / 44% / +0.13 / +37.2 / PF 1.44 | 15 / 87% / +1.11 / +16.7 / PF 15.70 | 308 / 46% / +0.17 / +53.8 / PF 1.63 |

## By year (regime filter on)

| year | pullback | breakout |
|---|---|---|
| 2017 | 230 / 71% / +0.14 / +33.0 / PF 2.09 | 33 / 58% / +0.43 / +14.2 / PF 4.01 |
| 2018 | 381 / 56% / -0.10 / -36.3 / PF 0.68 | 31 / 35% / +0.01 / +0.3 / PF 1.02 |
| 2019 | 399 / 61% / -0.03 / -11.3 / PF 0.89 | 24 / 42% / +0.29 / +6.9 / PF 2.21 |
| 2020 | 418 / 67% / +0.01 / +5.5 / PF 1.05 | 31 / 52% / +0.17 / +5.3 / PF 1.70 |
| 2021 | 724 / 69% / +0.10 / +75.4 / PF 1.70 | 41 / 37% / -0.05 / -1.9 / PF 0.85 |
| 2022 | 69 / 39% / -0.42 / -29.1 / PF 0.21 | 8 / 38% / -0.05 / -0.4 / PF 0.85 |
| 2023 | 481 / 57% / -0.01 / -5.9 / PF 0.94 | 28 / 54% / +0.20 / +5.6 / PF 1.58 |
| 2024 | 758 / 66% / +0.10 / +78.1 / PF 1.64 | 45 / 53% / +0.30 / +13.4 / PF 2.45 |
| 2025 | 591 / 70% / +0.09 / +55.7 / PF 1.61 | 28 / 32% / -0.08 / -2.2 / PF 0.69 |
| 2026 | 497 / 63% / +0.04 / +19.0 / PF 1.22 | 24 / 29% / -0.17 / -4.0 / PF 0.65 |

## Exit reasons (regime filter on)

| setup | reason | n | avg R |
|---|---|---|---|
| breakout | gapped below stop | 58 | -0.01 |
| breakout | max hold | 10 | +1.52 |
| breakout | stop | 11 | -1.01 |
| breakout | trailing stop | 214 | +0.16 |
| pullback | closed above 5-day average | 3891 | +0.22 |
| pullback | gapped below stop | 105 | -1.24 |
| pullback | stop | 529 | -1.01 |
| pullback | time stop | 23 | -0.61 |

pullback: 67 of 97 stocks net positive. Avg best excursion 0.34R; 2% reached +1R.

breakout: 39 of 70 stocks net positive. Avg best excursion 0.94R; 37% reached +1R.

Per-trade detail: swing_bt_trades.csv


## Exit variants (regime filter on)

Same signals, entries and starting stops; only the exit changes. Stop raises (trail, lock) take effect the next day, like the evening stop updates in paper trading. Look for a row that beats LIVE on total R **and** holds up in both halves, not just the biggest number.

| setup | exit rule | result | avg % / trade | vs drift % | avg days | max DD (R) | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|
| breakout | LIVE: half at 2R, trail 3 ATR | 293 / 44% / +0.13 / +37.2 / PF 1.44 | +0.88 | -0.65 | 19.1 | 8.4 | 163 / 45% / +0.17 / +27.0 / PF 1.61 | 130 / 43% / +0.08 / +10.2 / PF 1.26 |
| breakout | half at 3R, trail 3 ATR | 293 / 44% / +0.12 / +35.2 / PF 1.42 | +0.85 | -0.69 | 19.1 | 8.4 | 163 / 45% / +0.17 / +27.1 / PF 1.62 | 130 / 43% / +0.06 / +8.1 / PF 1.20 |
| breakout | half at 4R, trail 3 ATR | 293 / 44% / +0.13 / +37.4 / PF 1.45 | +0.91 | -0.63 | 19.1 | 8.3 | 163 / 45% / +0.18 / +29.0 / PF 1.66 | 130 / 43% / +0.06 / +8.4 / PF 1.21 |
| breakout | no half-sell, trail 3 ATR | 293 / 44% / +0.13 / +39.5 / PF 1.47 | +0.96 | -0.57 | 19.1 | 8.3 | 163 / 45% / +0.19 / +30.9 / PF 1.70 | 130 / 43% / +0.07 / +8.6 / PF 1.22 |
| breakout | no half-sell, trail 4 ATR | 278 / 47% / +0.24 / +67.3 / PF 1.70 | +1.58 | -0.61 | 28.1 | 7.5 | 154 / 49% / +0.28 / +43.6 / PF 1.90 | 124 / 45% / +0.19 / +23.8 / PF 1.50 |
| breakout | half at 2R, trail 2 ATR | 316 / 41% / +0.01 / +3.5 / PF 1.05 | +0.11 | -0.67 | 9.8 | 10.9 | 174 / 46% / +0.03 / +4.9 / PF 1.13 | 142 / 36% / -0.01 / -1.5 / PF 0.95 |
| breakout | half at 2R, trail 4 ATR | 278 / 47% / +0.23 / +63.5 / PF 1.66 | +1.49 | -0.70 | 28.1 | 8.2 | 154 / 49% / +0.26 / +40.1 / PF 1.82 | 124 / 45% / +0.19 / +23.5 / PF 1.50 |
| breakout | half at 2R, trail 3, lock +0.5R at +1R | 294 / 46% / +0.12 / +34.0 / PF 1.41 | +0.76 | -0.73 | 18.6 | 8.0 | 164 / 46% / +0.14 / +23.3 / PF 1.54 | 130 / 45% / +0.08 / +10.7 / PF 1.27 |
| breakout | half at 3R, trail 3, lock +0.5R at +1R | 294 / 46% / +0.11 / +32.6 / PF 1.39 | +0.74 | -0.75 | 18.6 | 8.2 | 164 / 46% / +0.14 / +23.2 / PF 1.54 | 130 / 45% / +0.07 / +9.3 / PF 1.24 |
| breakout | no half-sell, trail 3, lock +0.5R at +1R | 294 / 46% / +0.11 / +33.4 / PF 1.40 | +0.76 | -0.72 | 18.6 | 8.2 | 164 / 46% / +0.14 / +23.6 / PF 1.55 | 130 / 45% / +0.08 / +9.8 / PF 1.25 |
| breakout | no half-sell, trail 3, breakeven at +1R | 293 / 44% / +0.11 / +30.8 / PF 1.37 | +0.71 | -0.83 | 19.0 | 8.7 | 163 / 44% / +0.14 / +22.2 / PF 1.52 | 130 / 43% / +0.07 / +8.6 / PF 1.22 |
| breakout | no half-sell, trail 4, lock +1R at +2R | 278 / 47% / +0.24 / +65.8 / PF 1.69 | +1.54 | -0.63 | 28.0 | 7.5 | 154 / 49% / +0.28 / +43.8 / PF 1.90 | 124 / 45% / +0.18 / +21.9 / PF 1.47 |
| pullback | LIVE: sell after close above 5-day avg | 4548 / 65% / +0.04 / +184.0 / PF 1.21 | +0.28 | -0.11 | 4.2 | 110.5 | 2216 / 64% / +0.02 / +37.3 / PF 1.08 | 2332 / 65% / +0.06 / +146.7 / PF 1.37 |
| pullback | let it run: trail 2.5 ATR, max 20 days | 3707 / 43% / +0.11 / +391.3 / PF 1.29 | +0.61 | -0.51 | 12.1 | 82.2 | 1838 / 42% / +0.10 / +190.3 / PF 1.28 | 1869 / 43% / +0.11 / +201.1 / PF 1.30 |
| pullback | let it run: trail 2.5, lock +0.25R at +0.5R, max 20 days | 3986 / 60% / +0.08 / +308.5 / PF 1.25 | +0.47 | -0.43 | 9.7 | 89.4 | 1965 / 59% / +0.06 / +125.2 / PF 1.20 | 2021 / 60% / +0.09 / +183.2 / PF 1.31 |
