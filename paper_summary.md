# Paper trading (live alerts)

Risk $2/trade, fees 12 bps/side, slippage 5 bps. R is net of costs. Win = net R > 0.

16 closed, 21 open. Updated 2026-09-30 14:03 UTC.

Open paper trades:
- LTC shift short @ 69.21 (SL 72.15, TP 60.39) since 2026-09-29 00:00 UTC
- NEAR shift short @ 4.76 (SL 5.23, TP 3.58) since 2026-09-29 01:00 UTC
- SUI shift short @ 1.15 (SL 1.24, TP 0.94175) since 2026-09-29 01:00 UTC
- LINK grade long @ 14.75 (SL 14.01, TP 17.17) since 2026-09-29 05:00 UTC
- AAVE impulse long @ 163.75 (SL 156.29, TP 178.68) since 2026-09-29 08:00 UTC
- AAVE breakout long @ 163.75 (SL 154.81, TP 181.62) since 2026-09-29 08:00 UTC
- kSHIB shift long @ 0.00583 (SL 0.00561, TP 0.00652) since 2026-09-29 12:00 UTC
- ADA shift long @ 0.25371 (SL 0.24255, TP 0.28721) since 2026-09-29 12:00 UTC
- WLD grade long @ 0.50590 (SL 0.48060, TP 0.65116) since 2026-09-29 12:00 UTC
- BNB shift long @ 766.50 (SL 753.17, TP 806.48) since 2026-09-29 12:00 UTC
- XRP shift long @ 1.52 (SL 1.47, TP 1.67) since 2026-09-29 12:00 UTC
- BTC shift long @ 84,324.20 (SL 83,075.30, TP 88,070.90) since 2026-09-29 12:00 UTC
- ETH shift short @ 2,673.60 (SL 2,732.05, TP 2,498.26) since 2026-09-29 16:00 UTC
- Palladium grade short @ 1,229.00 (SL 1,265.97, TP 1,142.17) since 2026-09-29 19:00 UTC
- LINK shift short @ 14.67 (SL 15.40, TP 12.37) since 2026-09-29 23:00 UTC
- AAVE shift short @ 159.52 (SL 167.73, TP 134.90) since 2026-09-30 04:00 UTC
- Palladium shift long @ 1,243.50 (SL 1,216.99, TP 1,323.03) since 2026-09-30 08:00 UTC
- Gold shift long @ 4,218.30 (SL 4,172.44, TP 4,355.88) since 2026-09-30 12:00 UTC
- BTC impulse long @ 85,261.70 (SL 84,320.98, TP 87,143.14) since 2026-09-30 13:00 UTC
- DOGE impulse long @ 0.09727 (SL 0.09606, TP 0.09970) since 2026-09-30 13:00 UTC
- kSHIB impulse long @ 0.00595 (SL 0.00587, TP 0.00610) since 2026-09-30 13:00 UTC

Cells: n / win% / avg R / total R. Look for rows that stay positive with n >= 30.


## ALL (16 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 16 / 12% / -0.76 / -12.2 | 16 / 31% / -0.60 / -9.6 | 16 / 38% / -0.41 / -6.6 |
| adx25 | 5 / 0% / -1.08 / -5.4 | 5 / 0% / -1.03 / -5.1 | 5 / 20% / -0.62 / -3.1 |
| aligned | 5 / 0% / -0.88 / -4.4 | 5 / 20% / -0.52 / -2.6 | 5 / 20% / -0.47 / -2.3 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 13 / 15% / -0.67 / -8.7 | 13 / 31% / -0.59 / -7.7 | 13 / 46% / -0.25 / -3.3 |
| flow_with | 5 / 40% / -0.02 / -0.1 | 5 / 60% / -0.12 / -0.6 | 5 / 60% / -0.07 / -0.3 |
| solo | 8 / 12% / -0.75 / -6.0 | 8 / 25% / -0.69 / -5.5 | 8 / 38% / -0.41 / -3.2 |
| best | - | - | - |

## impulse (5 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 5 / 0% / -1.41 / -7.0 | 5 / 40% / -0.80 / -4.0 | 5 / 0% / -1.27 / -6.4 |
| adx25 | 1 / 0% / -1.77 / -1.8 | 1 / 0% / -1.77 / -1.8 | 1 / 0% / -1.51 / -1.5 |
| aligned | 2 / 0% / -1.42 / -2.8 | 2 / 50% / -0.65 / -1.3 | 2 / 0% / -1.28 / -2.6 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 3 / 0% / -1.54 / -4.6 | 3 / 33% / -1.03 / -3.1 | 3 / 0% / -1.36 / -4.1 |
| flow_with | 1 / 0% / -1.07 / -1.1 | 1 / 0% / -1.07 / -1.1 | 1 / 0% / -1.05 / -1.1 |
| solo | 2 / 0% / -1.24 / -2.5 | 2 / 50% / -0.47 / -0.9 | 2 / 0% / -1.16 / -2.3 |
| best | - | - | - |

## impulse_fade (10 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 10 / 20% / -0.41 / -4.1 | 10 / 30% / -0.46 / -4.6 | 10 / 60% / +0.08 / +0.8 |
| adx25 | 3 / 0% / -0.86 / -2.6 | 3 / 0% / -0.78 / -2.3 | 3 / 33% / -0.19 / -0.6 |
| aligned | 3 / 0% / -0.51 / -1.5 | 3 / 0% / -0.43 / -1.3 | 3 / 33% / +0.08 / +0.2 |
| va_with | - | - | - |
| ob_ok | 10 / 20% / -0.41 / -4.1 | 10 / 30% / -0.46 / -4.6 | 10 / 60% / +0.08 / +0.8 |
| flow_with | 4 / 50% / +0.25 / +1.0 | 4 / 75% / +0.12 / +0.5 | 4 / 75% / +0.18 / +0.7 |
| solo | 5 / 20% / -0.50 / -2.5 | 5 / 20% / -0.70 / -3.5 | 5 / 60% / +0.02 / +0.1 |
| best | - | - | - |

## shift (1 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.02 / -1.0 |
| adx25 | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.02 / -1.0 |
| aligned | - | - | - |
| va_with | - | - | - |
| ob_ok | - | - | - |
| flow_with | - | - | - |
| solo | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.04 / -1.0 | 1 / 0% / -1.02 / -1.0 |
| best | - | - | - |

All signals, partial management: profit factor 0.08, max drawdown 8.6R ($17).

