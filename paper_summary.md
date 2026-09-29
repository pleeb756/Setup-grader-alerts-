# Paper trading (live alerts)

Risk $2/trade, fees 12 bps/side, slippage 5 bps. R is net of costs. Win = net R > 0.

6 closed, 16 open. Updated 2026-09-29 16:01 UTC.

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
- AAVE impulse_fade short @ 171.41 (SL 174.54, TP 168.96) since 2026-09-29 12:00 UTC
- XRP shift long @ 1.52 (SL 1.47, TP 1.67) since 2026-09-29 12:00 UTC
- BTC shift long @ 84,324.20 (SL 83,075.30, TP 88,070.90) since 2026-09-29 12:00 UTC
- ETH shift short @ 2,673.60 (SL 2,732.05, TP 2,498.26) since 2026-09-29 16:00 UTC

Cells: n / win% / avg R / total R. Look for rows that stay positive with n >= 30.


## ALL (6 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 6 / 0% / -0.88 / -5.3 | 6 / 33% / -0.37 / -2.2 | 6 / 17% / -0.55 / -3.3 |
| adx25 | 1 / 0% / -1.13 / -1.1 | 1 / 0% / -1.13 / -1.1 | 1 / 0% / -1.08 / -1.1 |
| aligned | 3 / 0% / -0.88 / -2.6 | 3 / 33% / -0.37 / -1.1 | 3 / 33% / -0.30 / -0.9 |
| va_with | 1 / 0% / -1.36 / -1.4 | 1 / 100% / +0.17 / +0.2 | 1 / 0% / -1.24 / -1.2 |
| ob_ok | 5 / 0% / -0.78 / -3.9 | 5 / 20% / -0.48 / -2.4 | 5 / 20% / -0.42 / -2.1 |
| flow_with | - | - | - |
| solo | 4 / 0% / -0.95 / -3.8 | 4 / 25% / -0.56 / -2.3 | 4 / 25% / -0.50 / -2.0 |
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

## impulse_fade (4 signals)

| filter | plan | partial | wide |
|---|---|---|---|
| all | 4 / 0% / -0.63 / -2.5 | 4 / 0% / -0.63 / -2.5 | 4 / 25% / -0.20 / -0.8 |
| adx25 | 1 / 0% / -1.13 / -1.1 | 1 / 0% / -1.13 / -1.1 | 1 / 0% / -1.08 / -1.1 |
| aligned | 2 / 0% / -0.62 / -1.2 | 2 / 0% / -0.62 / -1.2 | 2 / 50% / +0.18 / +0.4 |
| va_with | - | - | - |
| ob_ok | 4 / 0% / -0.63 / -2.5 | 4 / 0% / -0.63 / -2.5 | 4 / 25% / -0.20 / -0.8 |
| flow_with | - | - | - |
| solo | 3 / 0% / -0.80 / -2.4 | 3 / 0% / -0.80 / -2.4 | 3 / 33% / -0.25 / -0.7 |
| best | - | - | - |

All signals, partial management: profit factor 0.12, max drawdown 2.4R ($5).

