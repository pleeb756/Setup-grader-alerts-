# Swing backtest: 10 years, 97 stocks (robinhood list)

Run 2026-10-09. Entries at the next open, 5 bps slippage per fill, no commissions. R = profit / initial risk. One position per stock per setup. 31 breakouts skipped for gapping more than 5%; 9 trades still open at the end left out.

**Caution:** this list is today's most popular stocks, chosen partly because they went up (survivorship bias), so treat results as optimistic. The 'vs drift' column subtracts each stock's own average daily move over the hold, which is the fairer test: positive means the signal beat just owning that stock.

Cells: n / win% / avg R / total R / profit factor.

## Strategy (regime filter on)

| setup | result | avg % / trade | vs drift % | avg days | max DD (R) | max open at once |
|---|---|---|---|---|---|---|
| pullback | 4500 / 64% / +0.04 / +179.1 / PF 1.20 | +0.28 | -0.12 | 4.2 | 109.3 | 47 |
| breakout | 272 / 48% / +0.24 / +65.0 / PF 1.70 | +1.55 | -0.67 | 28.3 | 7.5 | 19 |

## First half vs second half (split 2022-02-28)

If a setup only works in one half, it's fragile. Tune rules on the first half only.

| setup | first half | second half |
|---|---|---|
| pullback | 2189 / 64% / +0.02 / +35.0 / PF 1.07 | 2311 / 65% / +0.06 / +144.1 / PF 1.36 |
| breakout | 153 / 50% / +0.26 / +40.1 / PF 1.84 | 119 / 45% / +0.21 / +24.9 / PF 1.55 |

## Does the regime filter help?

| setup | SPY above 200-day | SPY below 200-day (filter skips these) | all signals |
|---|---|---|---|
| pullback | 4489 / 64% / +0.04 / +180.3 / PF 1.20 | 342 / 61% / -0.01 / -5.0 / PF 0.94 | 4831 / 64% / +0.04 / +175.3 / PF 1.18 |
| breakout | 272 / 48% / +0.24 / +65.0 / PF 1.70 | 11 / 91% / +1.32 / +14.5 / PF 404.31 | 283 / 49% / +0.28 / +79.5 / PF 1.86 |

## By year (regime filter on)

| year | pullback | breakout |
|---|---|---|
| 2017 | 230 / 71% / +0.14 / +33.0 / PF 2.09 | 30 / 73% / +0.56 / +16.9 / PF 5.28 |
| 2018 | 380 / 56% / -0.10 / -36.6 / PF 0.68 | 31 / 35% / -0.03 / -0.8 / PF 0.95 |
| 2019 | 390 / 62% / -0.03 / -9.8 / PF 0.90 | 22 / 55% / +0.58 / +12.7 / PF 3.52 |
| 2020 | 410 / 66% / +0.01 / +3.2 / PF 1.03 | 27 / 37% / +0.13 / +3.6 / PF 1.37 |
| 2021 | 715 / 69% / +0.10 / +74.2 / PF 1.70 | 40 / 48% / +0.13 / +5.2 / PF 1.39 |
| 2022 | 69 / 39% / -0.42 / -29.1 / PF 0.21 | 8 / 25% / -0.16 / -1.3 / PF 0.68 |
| 2023 | 478 / 56% / -0.01 / -6.6 / PF 0.94 | 26 / 58% / +0.50 / +13.1 / PF 2.63 |
| 2024 | 753 / 67% / +0.10 / +77.5 / PF 1.64 | 43 / 53% / +0.48 / +20.6 / PF 2.72 |
| 2025 | 582 / 70% / +0.09 / +54.9 / PF 1.62 | 24 / 42% / +0.01 / +0.1 / PF 1.02 |
| 2026 | 493 / 63% / +0.04 / +18.3 / PF 1.22 | 21 / 29% / -0.25 / -5.2 / PF 0.57 |

## Exit reasons (regime filter on)

| setup | reason | n | avg R |
|---|---|---|---|
| breakout | gapped below stop | 45 | +0.19 |
| breakout | max hold | 35 | +1.67 |
| breakout | stop | 27 | -1.01 |
| breakout | trailing stop | 165 | +0.15 |
| pullback | closed above 5-day average | 3848 | +0.22 |
| pullback | gapped below stop | 104 | -1.24 |
| pullback | stop | 525 | -1.01 |
| pullback | time stop | 23 | -0.61 |

pullback: 66 of 96 stocks net positive. Avg best excursion 0.34R; 2% reached +1R.

breakout: 43 of 69 stocks net positive. Avg best excursion 1.19R; 47% reached +1R.

Per-trade detail: swing_bt_trades.csv


## Exit variants (regime filter on)

Same signals, entries and starting stops; only the exit changes. Stop raises (trail, lock) take effect the next day, like the evening stop updates in paper trading. Look for a row that beats LIVE on total R **and** holds up in both halves, not just the biggest number.

| setup | exit rule | result | avg % / trade | vs drift % | avg days | max DD (R) | 1st half | 2nd half |
|---|---|---|---|---|---|---|---|---|
| breakout | LIVE: half at 2R, trail 4 ATR | 272 / 48% / +0.24 / +65.0 / PF 1.70 | +1.55 | -0.67 | 28.3 | 7.5 | 153 / 50% / +0.26 / +40.1 / PF 1.84 | 119 / 45% / +0.21 / +24.9 / PF 1.55 |
| breakout | old live: half at 2R, trail 3 ATR | 287 / 45% / +0.14 / +39.1 / PF 1.48 | +0.95 | -0.61 | 19.4 | 7.7 | 162 / 46% / +0.17 / +28.2 / PF 1.65 | 125 / 43% / +0.09 / +10.9 / PF 1.28 |
| breakout | half at 2R, trail 5 ATR | 266 / 48% / +0.28 / +74.4 / PF 1.71 | +1.74 | -0.94 | 34.1 | 9.8 | 150 / 51% / +0.30 / +45.7 / PF 1.83 | 116 / 46% / +0.25 / +28.7 / PF 1.58 |
| breakout | half at 2R, trail 2 ATR | 309 / 41% / +0.01 / +4.4 / PF 1.07 | +0.13 | -0.66 | 9.8 | 10.9 | 173 / 46% / +0.03 / +4.8 / PF 1.13 | 136 / 35% / -0.00 / -0.4 / PF 0.99 |
| breakout | half at 3R, trail 4 ATR | 272 / 48% / +0.24 / +65.3 / PF 1.70 | +1.55 | -0.68 | 28.3 | 7.1 | 153 / 50% / +0.26 / +40.4 / PF 1.84 | 119 / 45% / +0.21 / +24.9 / PF 1.55 |
| breakout | no half-sell, trail 3 ATR | 287 / 45% / +0.14 / +41.4 / PF 1.51 | +1.03 | -0.53 | 19.4 | 7.7 | 162 / 46% / +0.20 / +32.1 / PF 1.74 | 125 / 43% / +0.07 / +9.3 / PF 1.24 |
| breakout | no half-sell, trail 4 ATR | 272 / 48% / +0.25 / +68.8 / PF 1.74 | +1.65 | -0.58 | 28.3 | 7.1 | 153 / 50% / +0.29 / +43.7 / PF 1.91 | 119 / 45% / +0.21 / +25.1 / PF 1.56 |
| breakout | no half-sell, trail 5 ATR | 266 / 48% / +0.31 / +81.5 / PF 1.78 | +1.91 | -0.78 | 34.1 | 9.8 | 150 / 51% / +0.34 / +51.3 / PF 1.93 | 116 / 46% / +0.26 / +30.1 / PF 1.61 |
| breakout | half at 2R, trail 4, lock +0.5R at +1R | 273 / 52% / +0.24 / +64.5 / PF 1.73 | +1.51 | -0.57 | 26.6 | 7.1 | 154 / 55% / +0.27 / +41.2 / PF 1.91 | 119 / 48% / +0.20 / +23.3 / PF 1.54 |
| breakout | no half-sell, trail 4, lock +1R at +2R | 272 / 48% / +0.25 / +67.2 / PF 1.72 | +1.60 | -0.60 | 28.2 | 7.1 | 153 / 50% / +0.29 / +43.9 / PF 1.91 | 119 / 45% / +0.20 / +23.3 / PF 1.52 |
| pullback | LIVE: sell after close above 5-day avg | 4500 / 65% / +0.04 / +179.1 / PF 1.20 | +0.28 | -0.12 | 4.2 | 109.7 | 2189 / 64% / +0.02 / +35.0 / PF 1.07 | 2311 / 65% / +0.06 / +144.1 / PF 1.36 |
| pullback | let it run: trail 2.5 ATR, max 20 days | 3668 / 43% / +0.10 / +382.8 / PF 1.29 | +0.61 | -0.52 | 12.1 | 81.2 | 1817 / 42% / +0.10 / +187.9 / PF 1.28 | 1851 / 43% / +0.11 / +194.9 / PF 1.29 |
| pullback | let it run: trail 2.5, lock +0.25R at +0.5R, max 20 days | 3944 / 59% / +0.08 / +303.9 / PF 1.25 | +0.47 | -0.43 | 9.7 | 88.8 | 1943 / 59% / +0.06 / +125.3 / PF 1.21 | 2001 / 60% / +0.09 / +178.6 / PF 1.30 |
