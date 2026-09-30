# Paper trading (live alerts)

Risk $2/trade, fees 12 bps/side, slippage 5 bps. R is net of costs. Win = net R > 0.

20 closed, 21 open. Updated 2026-09-30 19:35 UTC.

Open paper trades:
- LTC shift short @ 69.21 (SL 72.15, TP 60.39) since 2026-09-29 00:00 UTC
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
- VVV shift long @ 28.18 (SL 26.46, TP 33.34) since 2026-09-30 16:00 UTC
- Silver breakout short @ 60.62 (SL 61.03, TP 59.80) since 2026-09-30 16:00 UTC
- Silver grade short @ 60.62 (SL 61.66, TP 57.17) since 2026-09-30 16:00 UTC
- HYPE shift long @ 87.72 (SL 84.87, TP 96.28) since 2026-09-30 16:00 UTC

Cells: n / win% / avg R / total R. Look for rows that stay positive with n >= 30.


## ALL (20 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 20 / 10% / -0.85 / -16.9 | 20 / 25% / -0.72 / -14.4 | 20 / 30% / -0.55 / -11.1 |
| adx25 | 6 / 0% / -1.07 / -6.4 | 6 / 0% / -1.03 / -6.2 | 6 / 17% / -0.69 / -4.1 |
| aligned | 8 / 0% / -1.01 / -8.1 | 8 / 12% / -0.79 / -6.3 | 8 / 12% / -0.72 / -5.8 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 14 / 14% / -0.71 / -9.9 | 14 / 29% / -0.64 / -8.9 | 14 / 43% / -0.32 / -4.4 |
| flow_with | 7 / 29% / -0.33 / -2.3 | 7 / 43% / -0.41 / -2.9 | 7 / 43% / -0.36 / -2.5 |
| solo | 10 / 10% / -0.83 / -8.3 | 10 / 20% / -0.78 / -7.8 | 10 / 30% / -0.54 / -5.4 |
| best | - | - | - |

## impulse (8 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 8 / 0% / -1.34 / -10.7 | 8 / 25% / -0.96 / -7.7 | 8 / 0% / -1.23 / -9.8 |
| adx25 | 1 / 0% / -1.77 / -1.8 | 1 / 0% / -1.77 / -1.8 | 1 / 0% / -1.51 / -1.5 |
| aligned | 5 / 0% / -1.31 / -6.5 | 5 / 20% / -1.00 / -5.0 | 5 / 0% / -1.20 / -6.0 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 4 / 0% / -1.46 / -5.8 | 4 / 25% / -1.08 / -4.3 | 4 / 0% / -1.30 / -5.2 |
| flow_with | 2 / 0% / -1.15 / -2.3 | 2 / 0% / -1.15 / -2.3 | 2 / 0% / -1.10 / -2.2 |
| solo | 3 / 0% / -1.24 / -3.7 | 3 / 33% / -0.73 / -2.2 | 3 / 0% / -1.16 / -3.5 |
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

## shift (2 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.02 / -2.0 |
| adx25 | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.02 / -2.0 |
| aligned | - | - | - |
| va_with | - | - | - |
| ob_ok | - | - | - |
| flow_with | 1 / 0% / -1.03 / -1.0 | 1 / 0% / -1.03 / -1.0 | 1 / 0% / -1.02 / -1.0 |
| solo | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.03 / -2.1 | 2 / 0% / -1.02 / -2.0 |
| best | - | - | - |

All signals, partial management: profit factor 0.05, max drawdown 13.3R ($27).

