# Daily checklist: NQ breakout playbook (MNQ)

Print this. Tick every box. Full reasoning in `PLAYBOOK.md` sections 15–16. Times are ET, UK in brackets (UK clocks change a week before the US in late October and late March: open is 13:30 UK that week).

## Before the open (by 9:15 ET / 14:15 UK)

- [ ] Run `.venv-nautilus/bin/python backtest/premarket_levels.py` (about $0.13 of Databento credit). Check the "data up to" time; overnight levels are only as fresh as that.
- [ ] Optional: start the screen agent, `.venv-nautilus/bin/python signals/screen_agent.py` (alerts only; it reads your Bookmap / DeepCharts windows and logs every reading to `signals/log/`).
- [ ] Mark on DeepCharts and Bookmap: PDH, PDL, prior VAH / VAL / POC, ONH, ONL. Note where price is: **inside / above / below** prior value.
- [ ] Note the median 15-min opening range and IB size from the script; today's stop sizes will be in that region.
- [ ] Economic calendar: flat 5 min before to 15 min after CPI, NFP, FOMC, PPI, retail sales. No trading on FOMC afternoons.
- [ ] State of mind: slept, no revenge from yesterday, no rule break yesterday (if there was: review only, no trading).

## Setups (only these two, first side to accept only)

| | ORB 15m (from 9:45 / 14:45 UK) | IB acceptance (from 10:30 / 15:30 UK) |
|---|---|---|
| Range | High / low of 9:30–9:45 | High / low of 9:30–10:30 |
| Trigger | A 5-min candle **closes** beyond the range | **Two** consecutive 5-min closes beyond the IB |
| Entry | Close of the trigger candle | Close of the second candle |
| Stop | Far side of the range; skip if over 120 pts | 30 pts back inside the IB edge |
| Target | 2R | IB edge + half the IB range |
| Limits | 2 attempts per direction | No entries after 13:00 (18:00 UK) |

Flat by 15:55 (20:55 UK). Stop never moves further away; trail only toward profit.

## Order-flow confirmation (tag every trade)

- **Yes** = all three: delta agrees with the break on the trigger candle(s); big trades print in the **body** of the candle (in the wick = absorption, stand aside); the retest of the edge holds with passive liquidity reloading on Bookmap / DeepDOM.
- **Partial** = one or two of the three.
- **No** = none, or absorption against you at the edge. Still take it during the forward test (we are measuring whether confirmation helps), but tag it honestly.

## Size: MNQ contracts = risk / (stop pts × $2 + $1.80), round down

| Stop (pts) | 30 | 50 | 60 | 80 | 100 | 120 |
|---|---|---|---|---|---|---|
| $250 risk | 4 | 2 | 2 | 1 | 1 | 1 |
| $350 risk | 5 | 3 | 2 | 2 | 1 | 1 |
| $450 risk (Position Loss max) | 7 | 4 | 3 | 2 | 2 | 1 |

If 0 contracts fit, skip. Never round up. **Plan: flat $350 on the Position Loss account, extend ($19 / 30 days) instead of raising risk** (PLAYBOOK.md section 18). Reminder to extend at day 25.

## Daily rules

- [ ] Max **3 trades**, one position at a time. Stop after **2 losers** or **−2R** on the day.
- [ ] Stop for the day after **+3R**, or after giving back 1R from +2R.
- [ ] Daily Loss account: the $1,000 daily limit is a soft breach (2nd one closes the account). Your −2R stop keeps you far from it.
- [ ] Position Loss account: **any single position losing $500+ incl. costs is a breach** (3rd closes the account). Bracket order (stop attached) on every entry, planned risk never above $450, never add to a loser.

## After the close (5 minutes)

- [ ] Log every trade in `app.html` → Journal: setup, entry, stop, exit, MFE, **Confirm** (yes / partial / no), **Day type**, rules followed.
- [ ] Day type: **trend** if price extended more than one IB range beyond the IB; otherwise **balance**.
- [ ] After 30+ trades: check "Does order-flow confirmation help?" in the journal. Go live on the challenge only if confirmed trades show +0.3R or better and good pass odds.
