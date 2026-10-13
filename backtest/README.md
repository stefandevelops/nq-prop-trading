# NautilusTrader backtest: Absorption Reversal (NQ / MNQ)

Research tool for the setup in `../PLAYBOOK.md`. It replays real CME tick data from Databento through
[NautilusTrader](https://nautilustrader.io), trades a coded version of the setup, and writes the
trades in the journal's CSV format so you can run them through the journal and the Simulator in `app.html`.

| File | What it does |
|---|---|
| `fetch_data.py` | Gets a Databento cost quote, downloads data (only with `--yes`), loads it into a Nautilus catalog |
| `strategies/absorption.py` | The strategy. Every threshold is a config field with a comment |
| `run_backtest.py` | Runs the backtest, writes `results/*_trades.csv` (journal format) and `results/*_summary.txt` |
| `make_sample_data.py` | Builds a small **synthetic** dataset to test the pipeline without a Databento key |
| `news_days.example.txt` | Example news calendar (skip days / blackout windows) |

Data, the catalog, results and `.env` are gitignored.

## 1. Environment (already set up)

NautilusTrader 1.231.0 supports Python 3.12 to 3.14, so the venv uses your system Python 3.14.

```zsh
cd "/Volumes/Samsung SSD - Stefan/AI/Cursor/Trading"
source .venv-nautilus/bin/activate
```

All commands below assume the venv is active and you are in the `Trading` folder.
To rebuild it: `python3 -m venv .venv-nautilus && .venv-nautilus/bin/pip install nautilus_trader databento`.

## 2. Test the pipeline on synthetic data

```zsh
python backtest/make_sample_data.py
python backtest/run_backtest.py --sample
```

Output files start with `SYNTHETIC_` and every note says `SYNTHETIC`. That data is a random walk with injected
"absorption" episodes, built so the strategy finds trades. **Its results mean nothing**; it only shows that
loading, backtesting and export work.

## 3. Databento account and API key

1. Sign up at [databento.com](https://databento.com). New accounts have usually come with some free credit; check on sign-up.
2. In the portal, open **API Keys** and copy your key (it starts with `db-`).
3. Put it in `Trading/.env` (this file is gitignored, never commit it or paste it anywhere):

   ```
   DATABENTO_API_KEY=db-your-key-here
   ```

   The scripts read the key only from that file or from the `DATABENTO_API_KEY` environment variable, and never print it.

## 4. Get a cost quote, then download

```zsh
# Quote only: prints size and price, downloads nothing
python backtest/fetch_data.py --start 2025-06-02 --end 2025-09-02

# Download and load into backtest/data/catalog (asks Databento for the same request, one file per day)
python backtest/fetch_data.py --start 2025-06-02 --end 2025-09-02 --yes
```

- `--end` is exclusive. Dates are UTC days; Saturdays are skipped (Globex is closed).
- Default symbol `NQ.v.0` is Databento's continuous front month **by volume**, which rolls when traders do (about a week
  before expiry). `NQ.c.0` rolls by calendar. A single contract like `NQU5` also works.
- Already downloaded days are skipped, so you can extend a range without paying twice.
- `--symbol MNQ.v.0` gets MNQ as well (stored as `MNQ.GLBX`; run it with `--instrument-id MNQ.GLBX`).
  NQ is the better default: it is the market whose order flow you read, and MNQ follows its price.

### Which data (schema)?

| Schema | What you get | Size / cost (rough) | Use |
|---|---|---|---|
| `tbbo` (default) | Every trade with aggressor side, plus best bid/ask (and sizes) just before it | Smallest useful option. Roughly $10 to $25 per month of NQ | **Start here.** Enough for delta, volume, levels and realistic fills |
| `trades` | Trades only | A bit smaller than tbbo, same $/GB | Cheapest, but fills then use last trade instead of bid/ask |
| `mbp-1` | Every top-of-book change | Many times bigger than tbbo (cheap per GB, but tens of GB per month). Slow to backtest | Adds "does the offer refill?" detail at the best price |
| `mbp-10` | 10 levels of depth on every change | Largest by far, likely $50+ per month and hundreds of GB | Bookmap-style depth research. The strategy does not use depth yet |

These are estimates from Databento's published usage rates (about $28/GB for trades/tbbo, $1.80/GB for mbp-1,
$0.50/GB for mbp-10, billed on uncompressed size) and typical NQ activity. **The script prints the real quote
before anything is downloaded.** If you end up wanting a lot of history, Databento's CME Standard subscription
(about $199/month at the time of writing) includes 12 months of tbbo and mbp-1.

**Recommended start:** `NQ.v.0`, `tbbo`, 3 months. Use the first 2 months to look at trades and tune, and keep
the last month untouched as an out-of-sample check (see caveats). Expect a quote in the region of $30 to $75.

## 5. Run the backtest

```zsh
python backtest/run_backtest.py                                          # whole catalog, MNQ, risk from challenge.json
python backtest/run_backtest.py --start 2026-07-01 --end 2026-08-31      # in-sample period
python backtest/run_backtest.py --start 2026-09-01 --end 2026-09-30      # out-of-sample period
python backtest/run_backtest.py --news-file backtest/news_days.txt       # skip FOMC days, blackout around CPI etc.
python backtest/run_backtest.py --set min_absorbed_ratio=0.03 time_stop_mins=8   # change any strategy setting
python backtest/diagnose_filters.py --start 2026-07-06 --end 2026-07-17  # which detection filter rejects candidates
```

- Sizing, daily rules, contract and costs come from `../challenge.json` (`plan` and `costs`). `--risk` and `--contract NQ` override.
- Make a news file from `news_days.example.txt`: `YYYY-MM-DD` skips the day, `YYYY-MM-DD HH:MM` (New York time) blocks
  entries 5 minutes before to 15 minutes after and closes open trades.
- The summary shows trades, win rate, expectancy in R and $, profit factor, max drawdown, worst losing streak,
  how often price reached 1R/2R/3R before the original stop, and how trades exited.
- $ figures use the same formula as the journal: price move minus commission and 1 tick of slippage per contract.
  Fills happen at the bid/ask (spread included), and large orders walk the book one tick per level when top-of-book size runs out.
- Expect a few seconds per trading day of real tbbo data (the synthetic set runs at about half a second per day).

### What the strategy does

- **Levels (default: structural only):** prior-day RTH high/low, prior-day value area high/low, overnight high/low,
  initial balance high/low (after 10:30). POC, VWAP and round numbers can be switched on (`use_poc`, `use_vwap`,
  `round_number_step=100`) but lost money as entry levels in both test periods. VWAP is still used as a target.
- **Absorption:** in the last 60 seconds, volume is at least 1.2x normal and leans (50%+) toward the side hitting into the
  level; the high (or low) sits within 3 points of the level, has not extended for 5+ seconds, price is still within
  5 points of it, it was tested at least twice, and aggressive volume traded within 1 point of it is at least 2% of a
  normal 60-second window. NQ trades thinly at any single price, so this is calibrated from real data (it gives about
  1-2 setups a day), not a guess. A level is ignored after 3 tests in a day.
- **Entry:** within 2 minutes, price trades 1 point back through the level and the last 15 seconds of delta flips. Market order.
- **Stop:** 3 points beyond the absorption extreme, at least 6 points, skip if more than 25. Needs 1.5R of room to the next level/VWAP.
- **Management:** half off at 1R and the stop to breakeven; the rest at 2R or VWAP if closer; out after 10 minutes if 1R
  is not reached, after 30 minutes in any case, on opposite absorption, before news, and at 12:00.
- **Daily rules:** entries 9:35 to 11:30 ET, max 4 trades, stop after 2 losses, after -$400 or +$500, or after giving
  back 1R from +2R.

### Results so far (NQ tbbo, Jul-Sep 2026, MNQ, $200 risk, placeholder challenge rules)

| Run | Trades | Win rate | Expectancy (gross / net) | Net P&L | Max drawdown |
|---|---|---|---|---|---|
| All levels, Jul-Aug (in-sample) | 77 | 52% | -0.02R / -$20 per trade | -$1,575 | $2,386 |
| Structural levels, Jul-Aug (in-sample) | 39 | 59% | +0.16R / +$8 per trade | +$309 | $691 |
| Structural levels, Sep (out-of-sample) | 16 | 50% | +0.12R / -$1 per trade | -$17 | $1,172 |
| All levels, Sep (out-of-sample) | 46 | 39% | -0.29R / -$72 per trade | -$3,326 | $3,394 |

Replaying the structural-level trading days against the challenge rules (day-block bootstrap, 60 trading days):
about 11% pass, 29% fail, 60% still alive. Conclusion: the coded version of the setup has no proven edge yet. It is
roughly break-even at structural levels and clearly losing at round numbers and VWAP. Costs are about 0.09R per trade
(~10 MNQ x $1.80), so a small gross edge disappears. The structural-level filter was chosen after seeing Jul-Aug,
so only the September row is a fair test, and 16 trades is far too few to judge. Files: `results/insample_structural_*`,
`results/oos_sept_*`.

## 6. Import into the journal

1. Open `app.html`, go to the **Trade journal** tab.
2. Drop `backtest/results/absorption_..._trades.csv` on the import area (it is in the journal's backup format, so it imports directly).
3. Trades come in with setup "Absorption reversal", real stops, MFE/MAE in points, and a note starting with `Backtest`.
4. Use **Which target fits your entries** and the **Simulator** with "My journal trades" to test the challenge.

Consider a separate browser profile (or export your real journal first) so backtest trades don't mix with your own.
Don't import `SYNTHETIC_` files except to try out the import.

## 7. Auction setup research on 1-minute bars

```bash
.venv-nautilus/bin/python backtest/fetch_bars.py --yes          # NQ ohlcv-1m Jul 2024 - Jul 2026 ($2.58 quoted)
.venv-nautilus/bin/python backtest/research_setups.py           # design period (2024-25) only
.venv-nautilus/bin/python backtest/research_setups.py --holdout # + Jan-Sep 2026 check and rolling challenge test
```

Tests value area rotation, failed auction and IB breakout setups, writes `results/setups_*_trades.csv` (journal format).
`research_va_rotation.py` is the earlier tick-month-only version of the value area test. Findings: PLAYBOOK.md section 15.

```bash
.venv-nautilus/bin/python backtest/compare_accounts.py                 # Daily Loss ($49) vs Position Loss ($39)
.venv-nautilus/bin/python backtest/compare_accounts.py --stop-slip 4   # same, with 4 pts extra slippage on every stop-out
```

Runs the IB + ORB breakout playbook through rolling challenges under both IQ Capital rule sets. Findings: PLAYBOOK.md section 17.

```bash
.venv-nautilus/bin/python backtest/pass_planner.py   # risk per trade vs time (extensions), edge stress, risk schedules
```

Findings: PLAYBOOK.md section 18.

## 7b. Pre-market levels

```bash
.venv-nautilus/bin/python backtest/premarket_levels.py   # ~$0.13 of Databento credit per run, quotes first
```

Downloads the last ~35 days of 1-minute bars and prints today's PDH/PDL, prior value area and POC, overnight high/low,
where price sits relative to value, typical opening range and IB sizes, and MNQ sizes for common stops.
Refuses to download if the quote is above `--max-cost` (default $0.25). Use it with `CHECKLIST.md`.

## 8. Dashboard (NQ Desk Pro)

```bash
.venv-nautilus/bin/python backtest/build_dashboard.py   # ~30 s, writes dashboard/data.js
open dashboard.html
```

Re-run the builder after downloading more data or running a new backtest. Every non-synthetic `*_trades.csv` in `results/` becomes a source,
and your journal from `app.html` appears too when both are opened from the same origin (e.g. both via `python3 -m http.server`).

## Caveats (read these)

- **The code only approximates what you see.** Absorption in Bookmap and DeepCharts is a judgment call about heatmap,
  icebergs and context. Here it is a few numeric rules on trades and top-of-book. A good or bad backtest says something
  about *these rules*, not directly about your discretionary trading. Your journaled replay and sim trades remain the
  real test.
- **Overfitting.** With this many settings it is easy to find a combination that looked great in the past. Tune on one
  period (in-sample), then run it unchanged on a later period you never looked at (out-of-sample). If it falls apart, it
  was curve-fitted. Prefer few changes and round numbers.
- **Fill realism.** Fills use NQ's bid/ask and top-of-book size even when you trade MNQ (same price, thinner book).
  There is no queue modelling and no latency. 1 tick of slippage per round turn is charged in the $ figures.
- **Roll days.** Continuous `NQ.v.0` switches contract on roll; the price jumps, so prior-day levels are wrong on the
  first day after a roll. Expect a bad trade or two around roll dates, or skip them in the news file.
- **Research only.** Prop firms like IQ Capital usually route through Rithmic or Tradovate, which NautilusTrader has
  no official adapter for. Execution stays manual in DeepCharts. If you ever automate, check IQ Capital's rules on
  automated trading first; many firms restrict or ban it.
- `challenge.json` holds IQ Capital's Daily Loss 50K rules as of 11 Oct 2026. Re-check them before buying.
