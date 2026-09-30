# Paper trading (live alerts)

Risk $2/trade, fees 12 bps/side, slippage 5 bps. R is net of costs. Win = net R > 0.

7 closed, 17 open. Updated 2026-09-30 01:21 UTC.

Open paper trades:
- LTC shift short @ 69.21 (SL 72.15, TP 60.39) since 2026-09-29 00:00 UTC
- NEAR shift short @ 4.76 (SL 5.23, TP 3.58) since 2026-09-29 01:00 UTC
- SUI shift short @ 1.15 (SL 1.24, TP 0.94175) since 2026-09-29 01:00 UTC
- WLD shift short @ 0.48720 (SL 0.52839, TP 0.37884) since 2026-09-29 01:00 UTC
- ZEC impulse short @ 1,402.58 (SL 1,458.12, TP 1,291.49) since 2026-09-29 02:00 UTC
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

Cells: n / win% / avg R / total R. Look for rows that stay positive with n >= 30.


## ALL (7 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 7 / 0% / -0.92 / -6.4 | 7 / 29% / -0.48 / -3.4 | 7 / 29% / -0.38 / -2.7 |
| adx25 | 2 / 0% / -1.14 / -2.3 | 2 / 0% / -1.14 / -2.3 | 2 / 50% / -0.22 / -0.4 |
| aligned | 3 / 0% / -0.88 / -2.6 | 3 / 33% / -0.37 / -1.1 | 3 / 33% / -0.30 / -0.9 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 6 / 0% / -0.85 / -5.1 | 6 / 17% / -0.59 / -3.5 | 6 / 33% / -0.24 / -1.4 |
| flow_with | - | - | - |
| solo | 5 / 0% / -0.99 / -4.9 | 5 / 20% / -0.68 / -3.4 | 5 / 40% / -0.27 / -1.4 |
| best | - | - | - |

## impulse (2 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 2 / 0% / -1.38 / -2.8 | 2 / 100% / +0.15 / +0.3 | 2 / 0% / -1.25 / -2.5 |
| adx25 | - | - | - |
| aligned | 1 / 0% / -1.40 / -1.4 | 1 / 100% / +0.13 / +0.1 | 1 / 0% / -1.27 / -1.3 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 1 / 0% / -1.40 / -1.4 | 1 / 100% / +0.13 / +0.1 | 1 / 0% / -1.27 / -1.3 |
| flow_with | - | - | - |
| solo | 1 / 0% / -1.40 / -1.4 | 1 / 100% / +0.13 / +0.1 | 1 / 0% / -1.27 / -1.3 |
| best | - | - | - |

## impulse_fade (5 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 5 / 0% / -0.73 / -3.7 | 5 / 0% / -0.73 / -3.7 | 5 / 40% / -0.03 / -0.2 |
| adx25 | 2 / 0% / -1.14 / -2.3 | 2 / 0% / -1.14 / -2.3 | 2 / 50% / -0.22 / -0.4 |
| aligned | 2 / 0% / -0.62 / -1.2 | 2 / 0% / -0.62 / -1.2 | 2 / 50% / +0.18 / +0.4 |
| va_with | - | - | - |
| ob_ok | 5 / 0% / -0.73 / -3.7 | 5 / 0% / -0.73 / -3.7 | 5 / 40% / -0.03 / -0.2 |
| flow_with | - | - | - |
| solo | 4 / 0% / -0.89 / -3.5 | 4 / 0% / -0.89 / -3.5 | 4 / 50% / -0.02 / -0.1 |
| best | - | - | - |

All signals, partial management: profit factor 0.08, max drawdown 3.5R ($7).

