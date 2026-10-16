# Swing backtest: 10 years, 98 stocks (robinhood list)

Run 2026-10-16. Entries at the next open, 5 bps slippage per fill, no commissions, no short borrow fees. R = profit / initial risk. One position per stock per setup. 38 breakouts/breakdowns skipped for gapping more than 5%; 23 trades still open at the end left out.

Regime filter: longs need SPY above its 200-day; shorts run in any market (SHORT_REGIME=any).

**Caution:** this list is today's most popular stocks, chosen partly because they went up (survivorship bias), so long results run optimistic and short results run pessimistic. The 'vs drift' column subtracts each stock's own average daily move over the hold (inverted for shorts), which is the fairer test: positive means the signal beat just holding (or just shorting) that stock.

Cells: n / win% / avg R / total R / profit factor.

## Strategy (regime filter on)

| setup | result | avg % / trade | vs drift % | avg days | max DD (R) | max open at once |
|---|---|---|---|---|---|---|
| pullback | 4577 / 64% / +0.04 / +175.9 / PF 1.19 | +0.27 | -0.12 | 4.2 | 110.5 | 48 |
| breakout | 279 / 48% / +0.23 / +64.1 / PF 1.67 | +1.50 | -0.72 | 28.2 | 7.5 | 19 |
| short_bounce | 2266 / 62% / +0.01 / +32.3 / PF 1.07 | +0.29 | +0.67 | 4.6 | 60.2 | 54 |
| breakdown | 85 / 22% / -0.28 / -23.8 / PF 0.50 | -2.13 | -0.48 | 23.9 | 26.7 | 9 |

## First half vs second half (split 2022-03-08)

If a setup only works in one half, it's fragile. Tune rules on the first half only.

| setup | first half | second half |
|---|---|---|
| pullback | 2213 / 64% / +0.02 / +33.9 / PF 1.07 | 2364 / 65% / +0.06 / +141.9 / PF 1.34 |
| breakout | 155 / 50% / +0.26 / +40.6 / PF 1.83 | 124 / 45% / +0.19 / +23.5 / PF 1.50 |
| short_bounce | 850 / 63% / +0.04 / +34.0 / PF 1.22 | 1416 / 61% / -0.00 / -1.6 / PF 0.99 |
| breakdown | 29 / 21% / -0.30 / -8.7 / PF 0.44 | 56 / 23% / -0.27 / -15.1 / PF 0.52 |

## Results by market regime (all signals, no filter)

| setup | SPY above 200-day | SPY below 200-day | all signals |
|---|---|---|---|
| pullback | 4566 / 64% / +0.04 / +177.1 / PF 1.20 | 349 / 60% / -0.02 / -7.8 / PF 0.91 | 4915 / 64% / +0.03 / +169.3 / PF 1.17 |
| breakout | 279 / 48% / +0.23 / +64.1 / PF 1.67 | 11 / 91% / +1.31 / +14.4 / PF 402.08 | 290 / 49% / +0.27 / +78.5 / PF 1.82 |
| short_bounce | 1372 / 62% / -0.01 / -11.5 / PF 0.96 | 894 / 62% / +0.05 / +43.8 / PF 1.31 | 2266 / 62% / +0.01 / +32.3 / PF 1.07 |
| breakdown | 53 / 28% / -0.16 / -8.7 / PF 0.70 | 32 / 12% / -0.47 / -15.1 / PF 0.16 | 85 / 22% / -0.28 / -23.8 / PF 0.50 |

## By year (regime filter on)

| year | pullback | breakout | short_bounce | breakdown |
|---|---|---|---|---|
| 2017 | 215 / 73% / +0.15 / +32.0 / PF 2.17 | 30 / 73% / +0.56 / +16.8 / PF 5.15 | 33 / 64% / +0.06 / +1.9 / PF 1.26 | 4 / 25% / -0.03 / -0.1 / PF 0.95 |
| 2018 | 381 / 56% / -0.10 / -36.3 / PF 0.68 | 31 / 35% / -0.03 / -0.8 / PF 0.95 | 170 / 63% / +0.02 / +3.7 / PF 1.10 | 10 / 20% / -0.23 / -2.3 / PF 0.50 |
| 2019 | 399 / 61% / -0.03 / -11.3 / PF 0.89 | 23 / 52% / +0.53 / +12.2 / PF 3.17 | 216 / 56% / -0.05 / -10.0 / PF 0.76 | 4 / 0% / -0.60 / -2.4 / PF 0.00 |
| 2020 | 423 / 66% / +0.01 / +4.7 / PF 1.05 | 28 / 39% / +0.17 / +4.7 / PF 1.49 | 264 / 71% / +0.11 / +28.4 / PF 1.71 | 7 / 29% / -0.20 / -1.4 / PF 0.63 |
| 2021 | 731 / 69% / +0.10 / +73.8 / PF 1.67 | 40 / 48% / +0.13 / +5.2 / PF 1.39 | 99 / 52% / -0.08 / -7.9 / PF 0.72 | 1 / 0% / -1.01 / -1.0 / PF 0.00 |
| 2022 | 69 / 39% / -0.42 / -29.1 / PF 0.21 | 8 / 25% / -0.16 / -1.3 / PF 0.68 | 663 / 66% / +0.12 / +76.4 / PF 1.90 | 24 / 17% / -0.41 / -9.9 / PF 0.23 |
| 2023 | 484 / 56% / -0.02 / -8.5 / PF 0.92 | 26 / 58% / +0.50 / +13.1 / PF 2.63 | 288 / 58% / -0.08 / -24.1 / PF 0.68 | 13 / 15% / -0.54 / -7.0 / PF 0.16 |
| 2024 | 763 / 66% / +0.10 / +77.5 / PF 1.63 | 44 / 52% / +0.44 / +19.5 / PF 2.50 | 139 / 57% / -0.08 / -11.6 / PF 0.73 | 5 / 60% / +0.88 / +4.4 / PF 4.36 |
| 2025 | 598 / 71% / +0.10 / +58.1 / PF 1.64 | 27 / 44% / +0.03 / +0.8 / PF 1.08 | 206 / 58% / -0.04 / -7.8 / PF 0.85 | 10 / 40% / -0.09 / -0.9 / PF 0.86 |
| 2026 | 514 / 63% / +0.03 / +14.9 / PF 1.16 | 22 / 27% / -0.28 / -6.1 / PF 0.53 | 188 / 60% / -0.09 / -16.6 / PF 0.71 | 7 / 14% / -0.47 / -3.3 / PF 0.30 |

## Exit reasons (regime filter on)

| setup | reason | n | avg R |
|---|---|---|---|
| breakdown | gapped above stop | 17 | -0.02 |
| breakdown | max hold | 8 | +1.06 |
| breakdown | stop | 20 | -1.01 |
| breakdown | trailing stop | 40 | -0.29 |
| breakout | gapped below stop | 49 | +0.19 |
| breakout | max hold | 35 | +1.67 |
| breakout | stop | 27 | -1.01 |
| breakout | trailing stop | 168 | +0.14 |
| pullback | closed above 5-day average | 3911 | +0.22 |
| pullback | gapped below stop | 108 | -1.24 |
| pullback | stop | 535 | -1.01 |
| pullback | time stop | 23 | -0.61 |
| short_bounce | closed below 5-day average | 1948 | +0.19 |
| short_bounce | gapped above stop | 78 | -1.27 |
| short_bounce | stop | 218 | -1.01 |
| short_bounce | time stop | 22 | -0.71 |

pullback: 66 of 98 stocks net positive. Avg best excursion 0.34R; 2% reached +1R.

breakout: 42 of 70 stocks net positive. Avg best excursion 1.19R; 47% reached +1R.

short_bounce: 52 of 94 stocks net positive. Avg best excursion 0.33R; 3% reached +1R.

breakdown: 10 of 49 stocks net positive. Avg best excursion 0.92R; 35% reached +1R.

Per-trade detail: swing_bt_trades.csv


## Exit variants (regime filter on)

Same signals, entries and starting stops; only the exit changes. Stop moves (trail, lock) take effect the next day, like the evening stop updates in paper trading. Look for a row that beats LIVE on total R **and** holds up in both halves, not just the biggest number.

| setup | exit rule | result | avg % / trade | vs drift % | avg days | max DD (R) | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|
| breakout | LIVE: half at 2R, trail 4 ATR | 279 / 48% / +0.23 / +64.1 / PF 1.67 | +1.50 | -0.72 | 28.2 | 7.5 | 155 / 50% / +0.26 / +40.6 / PF 1.83 | 124 / 45% / +0.19 / +23.5 / PF 1.50 |
| breakout | old live: half at 2R, trail 3 ATR | 294 / 44% / +0.13 / +37.7 / PF 1.45 | +0.90 | -0.66 | 19.3 | 8.4 | 164 / 45% / +0.17 / +27.6 / PF 1.63 | 130 / 43% / +0.08 / +10.2 / PF 1.26 |
| breakout | half at 2R, trail 5 ATR | 272 / 48% / +0.27 / +73.8 / PF 1.69 | +1.70 | -0.98 | 34.1 | 9.8 | 152 / 51% / +0.30 / +45.9 / PF 1.82 | 120 / 45% / +0.23 / +27.9 / PF 1.54 |
| breakout | half at 2R, trail 2 ATR | 317 / 41% / +0.01 / +2.9 / PF 1.04 | +0.10 | -0.69 | 9.8 | 10.9 | 175 / 45% / +0.02 / +4.4 / PF 1.12 | 142 / 36% / -0.01 / -1.5 / PF 0.95 |
| breakout | half at 3R, trail 4 ATR | 279 / 48% / +0.23 / +64.4 / PF 1.67 | +1.50 | -0.72 | 28.2 | 7.1 | 155 / 50% / +0.26 / +40.9 / PF 1.84 | 124 / 45% / +0.19 / +23.5 / PF 1.50 |
| breakout | no half-sell, trail 3 ATR | 294 / 44% / +0.14 / +40.1 / PF 1.48 | +0.98 | -0.58 | 19.3 | 8.3 | 164 / 45% / +0.19 / +31.5 / PF 1.71 | 130 / 43% / +0.07 / +8.6 / PF 1.22 |
| breakout | no half-sell, trail 4 ATR | 279 / 48% / +0.24 / +67.9 / PF 1.71 | +1.59 | -0.63 | 28.2 | 7.0 | 155 / 50% / +0.28 / +44.1 / PF 1.91 | 124 / 45% / +0.19 / +23.8 / PF 1.50 |
| breakout | no half-sell, trail 5 ATR | 272 / 48% / +0.30 / +80.6 / PF 1.75 | +1.86 | -0.83 | 34.1 | 9.8 | 152 / 51% / +0.34 / +51.5 / PF 1.92 | 120 / 45% / +0.24 / +29.1 / PF 1.56 |
| breakout | half at 2R, trail 4, lock +0.5R at +1R | 280 / 51% / +0.23 / +63.7 / PF 1.70 | +1.45 | -0.62 | 26.6 | 7.3 | 156 / 54% / +0.27 / +41.7 / PF 1.91 | 124 / 48% / +0.18 / +22.0 / PF 1.49 |
| breakout | no half-sell, trail 4, lock +1R at +2R | 279 / 48% / +0.24 / +66.3 / PF 1.69 | +1.55 | -0.65 | 28.1 | 6.9 | 155 / 50% / +0.29 / +44.4 / PF 1.91 | 124 / 45% / +0.18 / +21.9 / PF 1.47 |
| pullback | LIVE: sell after close above 5-day avg | 4577 / 64% / +0.04 / +175.9 / PF 1.19 | +0.27 | -0.12 | 4.2 | 110.5 | 2213 / 64% / +0.02 / +33.9 / PF 1.07 | 2364 / 65% / +0.06 / +141.9 / PF 1.34 |
| pullback | let it run: trail 2.5 ATR, max 20 days | 3736 / 43% / +0.11 / +416.5 / PF 1.31 | +0.63 | -0.50 | 12.1 | 85.2 | 1837 / 43% / +0.11 / +196.8 / PF 1.29 | 1899 / 42% / +0.12 / +219.8 / PF 1.33 |
| pullback | let it run: trail 2.5, lock +0.25R at +0.5R, max 20 days | 4015 / 59% / +0.08 / +308.5 / PF 1.25 | +0.49 | -0.42 | 9.7 | 92.0 | 1962 / 59% / +0.07 / +129.2 / PF 1.21 | 2053 / 60% / +0.09 / +179.4 / PF 1.29 |
| short_bounce | LIVE: cover after close below 5-day avg | 2266 / 62% / +0.01 / +32.3 / PF 1.07 | +0.29 | +0.67 | 4.6 | 60.2 | 851 / 63% / +0.04 / +34.4 / PF 1.22 | 1415 / 61% / -0.00 / -2.0 / PF 0.99 |
| short_bounce | let it run: trail 2.5 ATR, max 20 days | 1801 / 35% / -0.09 / -156.5 / PF 0.80 | -0.56 | +0.49 | 12.3 | 156.0 | 655 / 32% / -0.14 / -93.9 / PF 0.68 | 1146 / 38% / -0.05 / -62.7 / PF 0.87 |
| breakdown | LIVE: half at 2R, trail 4 ATR | 85 / 22% / -0.28 / -23.8 / PF 0.50 | -2.13 | -0.48 | 23.9 | 26.7 | 30 / 23% / -0.26 / -7.7 / PF 0.51 | 55 / 22% / -0.29 / -16.1 / PF 0.49 |
| breakdown | half at 2R, trail 3 ATR | 89 / 24% / -0.24 / -21.1 / PF 0.48 | -1.86 | -0.67 | 15.9 | 23.0 | 32 / 28% / -0.26 / -8.4 / PF 0.41 | 57 / 21% / -0.22 / -12.7 / PF 0.51 |
| breakdown | no half-cover, trail 4 ATR | 85 / 22% / -0.30 / -25.6 / PF 0.46 | -2.29 | -0.64 | 23.9 | 27.9 | 30 / 23% / -0.24 / -7.2 / PF 0.54 | 55 / 22% / -0.34 / -18.5 / PF 0.42 |
| breakdown | half at 2R, trail 4, lock +0.5R at +1R | 87 / 37% / -0.20 / -17.5 / PF 0.60 | -1.55 | -0.22 | 20.0 | 20.9 | 30 / 27% / -0.23 / -7.0 / PF 0.55 | 57 / 42% / -0.18 / -10.5 / PF 0.62 |
