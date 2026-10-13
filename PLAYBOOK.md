# Playbook: Absorption Reversal at Key Levels (NQ / MNQ)

One setup, traded the same way every time. Do not add setups until this one has 50+ journaled trades with positive expectancy.

Educational material, not financial advice. Test on replay and sim before risking challenge money.

---

## 1. The idea

At an important price level, aggressive traders hit the market (market orders) trying to push through, but large passive limit orders absorb all of it. Price stops moving despite heavy aggression. When the aggressors give up, price snaps back the other way, often fueled by their stops.

You are not predicting the level will hold. You wait until the order flow **shows** it holding, then enter with a stop just beyond it. If the level breaks, you are out quickly with a small, defined loss.

---

## 2. Pre-market preparation (before 9:15 ET / 14:15 UK)

Mark these levels on DeepCharts and Bookmap. Only **structural** levels are entry levels; the rest are targets or context (see section 14):

| Level | Use | Why it matters |
|---|---|---|
| Prior day high and low | **Entry** | Obvious stop clusters and breakout points |
| Overnight (Globex) high and low | **Entry** | Where overnight traders are trapped |
| Prior day value area high and low | **Entry** | Edges of where the market accepted price yesterday |
| Initial balance high and low (first hour, after 10:30 ET) | **Entry** | Range the market must break to trend |
| VWAP (developing) | Target only | Where intraday traders judge "cheap" vs "expensive" |
| Prior day point of control | Context only | Yesterday's fair price; price often rotates through it |
| Round numbers (every 100 points) | Context only | Resting orders cluster here |

Also:
- Check the economic calendar. **Flat 5 minutes before and 15 minutes after** CPI, FOMC, NFP, PPI, retail sales, and big-tech earnings in the pre-market. Skip FOMC afternoons entirely.
- Note the 14-day average daily range of NQ. It sets your stop expectations (see section 6).
- Write down: "If price reaches level X, I'm watching for absorption."

---

## 3. Trading window

- **Main window:** 9:30 to 11:30 ET (14:30 to 16:30 UK; an hour earlier for you in the weeks when UK and US clocks change on different dates).
- **No entries in the first 5 minutes** after the open. Spreads and noise are too wide.
- **No new trades after 11:30 ET** unless you are already green and see an A+ setup. The lunch session chops.

---

## 4. Setup checklist (all must be true)

1. **Price is at a pre-marked structural level** (within ~3 NQ points): prior day high/low, prior day value area high/low, overnight high/low, or initial balance high/low. Not "near-ish". At it. VWAP, round numbers and the prior day POC alone do not qualify.
2. **Aggression into the level:** heavy market orders hitting into it. Large volume dots on Bookmap, strongly one-sided delta on the footprint.
3. **No progress:** despite the aggression, price fails to make new highs (or lows) beyond the level. Two or more pushes that stall is ideal.
4. **Liquidity holds or reloads:** on the Bookmap heatmap or DeepDOM, the passive orders at the level stay or refresh as they get hit (iceberg behavior), rather than being pulled.
5. **Delta divergence (optional, strengthens the trade):** cumulative delta keeps rising into resistance while price stalls (or falling into support while price holds).
6. **Room to the target:** at least 1.5R of open space to the next level or VWAP.

If any of 1 to 4 is missing, there is no trade.

---

## 5. Entry trigger

Do not fade the level while aggression is still active. Wait for the **shift**:

- **Short at resistance:** after absorption, price ticks back below the level and the next footprint bar shows sellers taking control (negative delta, offers lifting the bid). Enter short on that bar or on a small retest of the level that fails.
- **Long at support:** the mirror image. Price reclaims the level and buyers show up in the delta.

Use a limit order on a retest when possible (better price, less slippage). Use a market order only if price is leaving without you and the stop distance is still within your maximum.

---

## 6. Stop

- Place the stop **2 to 4 NQ points beyond the extreme of the absorption** (the highest high for a short, the lowest low for a long).
- Typical stop: **10 to 20 NQ points.**
- **Maximum stop: 25 points.** If the logical stop is further away, skip the trade or wait for a better entry. Do not move the stop to fit.
- On high-volatility days (average daily range well above normal), widen the stop toward the top of the range and **trade fewer contracts** to keep the same dollar risk.
- The stop never moves further away. It only moves toward breakeven or into profit.

---

## 7. Targets and management

| Step | Action |
|---|---|
| Target 1 at **1R** | Close half the position. Move the stop on the rest to breakeven. |
| Target 2 at **2R**, or the next level / VWAP if closer | Close the rest. |
| No progress after 10 minutes | Exit at market. Absorption trades should work quickly. |
| Opposite absorption appears against you | Exit. The order flow changed its mind. |

This combines a high win rate (reaching 1R) with the bigger winners that a pure 1R strategy gives up. If your journal later shows that 1.5R or 2R as a single target performs better, change it, but only based on 50+ trades.

When logging the trade, enter your **average exit price** and the **MFE** (how far price went before it would have hit your original stop).

---

## 8. Position sizing

Fixed dollar risk per trade, taken from your challenge plan (example: $150 to $200 on a $2,000 drawdown):

```
MNQ contracts = risk in $ / (stop in points x $2)
NQ contracts  = risk in $ / (stop in points x $20)
```

Example: $200 risk, 18 point stop gives 200 / 36 = 5 MNQ (round down). Always round down.

Use MNQ until you are at least $1,000 into profit on the challenge. Only scale up from profit, never to recover losses.

---

## 9. Do not trade when

- Price is in the middle of the range, away from your levels.
- The only level in play is VWAP, a round number or the prior day POC. These lost money as entry levels in the backtest.
- The setup is not A+. Costs eat a small edge, so B setups are not worth taking.
- A major news release is within the blackout window.
- The level has already been tested 3+ times today (each test weakens it).
- The market is trending hard through levels without pausing (absorption setups get run over on strong trend days; switch to observation).
- You hit your daily stop, or you feel the urge to "make it back".

---

## 10. Daily rules

- Maximum **3 trades** per day (2 is fine). Fewer, better trades: each one costs about 0.09R in commission and slippage.
- Stop after **2 losses**, or after losing your **daily stop** (example: $400).
- Stop after reaching your **daily goal** (example: $500), or once you're up 2R and give back 1R of it.
- No trading the day after a rule break. Review the journal instead.

---

## 11. Example (hypothetical)

> Overnight high is 21,515. At 9:48 ET price rallies into 21,512 to 21,516. Bookmap shows large buy volume dots and the footprint delta is strongly positive for three bars, but price cannot close above 21,516. A large offer at 21,515 keeps refilling. Cumulative delta makes a higher high while price makes an equal high.
>
> The next bar closes at 21,508 with negative delta. Entry short at 21,508 on a retest. Stop at 21,520 (12 points above entry, 4 points above the absorption high). Risk $200 gives 200 / 24 = 8 MNQ.
>
> Target 1 at 21,496 (1R): close 4 MNQ, move stop to 21,508. Target 2 at 21,484 (2R) or VWAP at 21,489 if it's closer: close the rest at VWAP.

---

## 12. Testing plan before the challenge

1. **Replay (Bookmap replay or DeepCharts market replay):** 30 trades of this setup only. Log every one in the journal, including MFE.
2. **Live sim:** 30 more trades, in real time, with the daily rules applied.
3. **Check the numbers:** expectancy per trade above +0.2R, and "expectancy, rules followed" clearly better than "rules broken".
4. **Simulate:** in the journal's "Which target fits your entries" table, click Simulate on the best row. Aim for a 70%+ pass rate in the Simulator using IQ Capital's real rules.
5. Only then buy the challenge, and trade it exactly as you did on sim.

---

## 13. Weekly review

- Which trades broke the checklist? What did they cost?
- Were the losers valid setups that failed (fine) or bad setups (fix)?
- Which levels produced the best trades? Focus there.
- Is the MFE table pointing to a different target than the one you use?

---

## 14. Backtest evidence (Jul–Sep 2026)

A coded version of this setup was backtested in NautilusTrader on real Databento NQ tbbo data (MNQ, $200 risk, costs about $1.80 per MNQ round turn including slippage). Jul–Aug was used for tuning (in-sample), September was held out (out-of-sample). Full details: `backtest/README.md`.

| Run | Trades | Win rate | Expectancy (gross) | Net P&L |
|---|---|---|---|---|
| All levels, Jul–Aug | 77 | 52% | -0.02R | -$1,575 |
| Structural levels, Jul–Aug | 39 | 59% | +0.16R | +$309 |
| Structural levels, Sep | 16 | 50% | +0.12R | -$17 |
| All levels, Sep | 46 | 39% | -0.29R | -$3,326 (challenge failed) |

What it means:
- Round numbers, VWAP and the prior day POC lost money as entry levels in both periods. Only fade structural levels; use VWAP as a target.
- At structural levels the gross edge is small (+0.12 to +0.16R) and costs (about 0.09R per trade at ~10 MNQ) take most of it. Take fewer trades, only A+ setups, and prefer limit entries on the retest to cut slippage.

Caveats:
- The code only approximates discretionary order-flow reading in Bookmap and DeepCharts.
- 16 out-of-sample trades is far too few to judge anything.
- The structural-only filter was chosen after seeing Jul–Aug, so the in-sample numbers are optimistic.
- The edge is unproven. Your own journaled replay and sim trades (section 12) are the real test.

## 15. Auction setups tested on 2+ years (Jul 2024 – Sep 2026)

Three auction-theory setups were coded on NQ 1-minute bars (`backtest/research_setups.py`). Rules were chosen on Jul 2024 – Dec 2025 (353 sessions) and checked once on Jan – Sep 2026 (178 sessions). Bars have no aggressor side, so this tests the auction structure only; your order-flow read is the filter on top. "Family" means every reasonable parameter combination of the setup, which is a better guide than the single best one.

| Setup | Family 2024–25 | Family 2026 | Verdict |
|---|---|---|---|
| A. Value area rotation (80% rule) | median +0.03R, 58% of variants profitable | median −0.10R, 42% | No mechanical edge. Discretionary only. |
| B. Failed auction at PDH/PDL/ONH/ONL | median −0.11R, 8% | median −0.06R, 29% | No mechanical edge. Needs a real absorption read to have any chance. |
| C. Initial balance breakout with acceptance | median +0.11R, 75% | median +0.16R, 66% | Positive in both periods. The core setup. |

**Setup C, simple version (use this one):**
- After 10:30 ET, two consecutive 5-minute closes beyond the IB high (long) or IB low (short). First side to accept only, no entries after 13:00.
- Enter at the close of the second 5-minute bar. Stop 30 points back inside the IB edge. Target the IB edge plus half the IB range. Flat by 15:55.
- Result: 2024–25 232 trades, 56% win, +0.19R; 2026 117 trades, 48% win, +0.19R. Average stop about 50 points.
- Order-flow filter to add by hand: on the acceptance bars, delta and stacked imbalances should agree with the break, and the retest of the IB edge should hold with passive liquidity, not get absorbed against you.
- The "best" parameter set in 2024–25 (retest entry, 1x IB target) lost in 2026. Parameter rankings did not carry over between periods (rank correlation −0.27), so don't optimise; keep the simple version.

**What this means for the challenge:**
- NQ in this period needs 50–80 point structure stops. A 25-point stop sits inside 1-minute noise (bars are often 30–50 points tall). On MNQ at $250 risk that is 1–2 contracts.
- An edge of about +0.2R at under one trade a day makes roughly +3R in 21 sessions, and the target is 12R at $250 risk. Rolling 21-day challenges with setup C alone: 0% pass at $250 risk (all timeouts), 3–16% at $350, 23–30% at $500 with 17–31% failing. With a 42-day window (one $19 extension): 21% pass and 0% fail at $250 in 2026, 43–53% pass at $500 but 32–43% fail.
- Passing needs either more good trades per day (your discretionary A+ reversals at structural levels on balance days, added to C on trend days) or a bigger edge from the order-flow filter. Measure both in the journal before buying the challenge.

## 16. What the traders you follow teach for NQ (and how it tested)

| Trader | Core NQ approach (public material) |
|---|---|
| Andrea Cimi (Cimitan, creator of DeepCharts) | Opening range breakout as the base setup: 15- or 30-minute range, a 5-minute candle must close beyond it, stop on the far side of the range, about 2R, two attempts per direction, flat before the close. The edge on top is "big bubbles": a large trade printing in the candle body = follow-through, enter; in the wick = absorption, stand aside. Also trades absorption, failed auctions and stop runs. Trails on NQ rather than taking partials. |
| Fabio Valentini (World Class Edge) | IVB (initial balance / opening range) model for the daily bias, 30 minutes working best for him on NQ, confirmed by delta and big trades. Two execution models: **trend** (market out of balance: profile the impulse leg, wait for a pullback into a low-volume node, enter on aggression, target the previous balance POC) and **mean reversion** (breakout fails, price reclaims the balance, enter on the pullback with aggression, target the POC; better in London and compression). Skips balanced, low-volume chop. Says 0.5% risk per trade in prop evaluations ($250 on a 50K). |
| Pietro Valastro | Order flow (DOM, footprint, heatmap), effort vs result (VSA), volume profile and VWAP, filtered by macro sentiment and gamma exposure: trades only the most directional days, fewer trades, higher average R. |

Tested on NQ 1-minute bars, Jul 2024 – Dec 2025 (design) and Jan – Sep 2026 (holdout), without the order-flow layer:

- **Opening range breakout (Cimi / Fabio IVB):** 20 of 24 variants profitable in 2024–25 and 16 of 24 in 2026 (median +0.05R both). Most consistent: 15-minute range, 5-minute close beyond, stop at the far side, 2R target, two attempts: +0.14R (312 trades) then +0.14R (64 trades). Catch for a 50K account: the 30-minute range is about 140 points on a median day, so a far-side stop is wider than 120 points (1 MNQ at $250 risk) on 62% of days. The midpoint stop keeps trades sizable but the edge drops to about +0.05R.
- **IB acceptance breakout (section 15, setup C):** +0.19R in both periods, stop about 50 points. Same idea as IVB with a tighter, structure-based stop, which is why it suits a $2,000 drawdown better.
- **Mean reversion back into value (Fabio model 2, setups A and B):** no mechanical edge in either period. Consistent with Fabio's own warning that it fails on compression and trend days; only take it with a clear absorption read.

Takeaways:
- Everyone you follow builds the day around the opening range / initial balance and only trades with the side that wins it. The data agrees: breakout-with-acceptance is the one structure that held up in both periods.
- Their real edge is the order-flow confirmation (big trades in the body vs the wick, delta, aggression at an LVN), which bars can't test. That is exactly what your journal should measure: tag every IB/ORB trade with whether the confirmation was present.
- Pietro's filter (trade only directional days) points the same way: skip balance days for breakouts, or treat them as reversal-only days.

Sources: [Cimitan ORB rules and backtest (PickMyTrade)](https://blog.pickmytrade.trade/andrea-cimitan-opening-range-breakout-strategy/), [Cimitan at Chart Academy](https://www.chartacademy.com/instructors/andrea-cimitan), [Fabio's AMT + LVN playbook (TradeZella)](https://www.tradezella.com/playbooks/auction-market-playbook), [World Class Edge course outline](https://worldclassedge.app/student-area/the-complete-order-flow/video-10), [Fabio strategy summary](https://youtubesummary.com/summary/HUYBdYnXUNc), [Pietro Valastro](https://pietrovalastro.framer.ai/). Third-party summaries can be inaccurate; the traders' own courses are the authority.

## 17. Which IQ Capital 50K version: Daily Loss ($49) or Position Loss ($39)

The IB acceptance + ORB 15m playbook (max 3 trades, stop after 2 losers) was run through rolling challenges under both rule sets (`backtest/compare_accounts.py`). Position Loss assumed: $3,000 EOD trailing drawdown locking at $50,000, no daily limit, a position losing $500+ is a breach, 3rd breach fails. "Stress" adds 4 points of slippage to every stop-out (fast-market fills).

Pass rate, and expected fees per pass (fee ÷ pass rate, +$19 extension for 42 days), holdout Jan–Sep 2026 with stress:

| Window, risk per trade | Daily Loss | Position Loss |
|---|---|---|
| 21 days, $350 | 12% pass, 16% fail, $407 per pass | 12% pass, 1% fail, $324 per pass |
| 21 days, $450 | 30% pass, 29% fail, $161 | 30% pass, 10% fail, $128 |
| 42 days, $350 | 47% pass, 29% fail, $143 | 47% pass, 9% fail, $122 |
| 42 days, $450 | 61% pass, 36% fail, $112 | 66% pass, 16% fail, $88 |
| 42 days, $500 | 58% pass, 42% fail | 53% pass, 47% fail (29% from breaches) |

The design period (2024–25) shows the same pattern at lower pass rates (42 days at $450: 43% vs 51%).

What it means:
- **Position Loss is the better account for this strategy**, provided planned risk stays at $450 or less. Same passes, a third to half the failures (the $3,000 drawdown absorbs losing streaks), and $10 cheaper. The daily loss limit never matters here because you stop after 2 losers anyway.
- **At $500 planned risk Position Loss becomes the worse choice**: any slippage on a full stop-out is a breach, and 3 breaches end the account. Leave a $50 buffer. Never widen a stop or add to a loser.
- Timeouts, not failures, are the main problem at $250–350. Even with the cheaper account, the mechanical edge needs about 6 weeks (one extension) and $350–450 risk to give decent odds. Order-flow confirmation that lifts the edge is still what makes 21 days realistic.
- Caveats: overlapping rolling windows are not independent, the holdout is only 178 sessions, and the Position Loss drawdown lock is assumed. Check the exact rules with IQ Capital before buying.

## 18. Getting a higher pass rate: buy time, not risk

IQ Capital challenges can be extended by 30 days for $19 as often as needed. With a small positive edge, the pass rate is limited by time far more than by the drawdown, so the cheapest way to raise it is to extend instead of sizing up. Tested with `backtest/pass_planner.py`: Position Loss account, 4 points extra slippage on stops, real rolling windows over Jul 2024 – Sep 2026 plus a no-deadline resampling of real days.

| Risk per trade (flat) | 21 sessions (1 month) | 63 sessions (3 months) | 105 sessions (5 months) | No deadline | No deadline, edge cut by 0.1R | Median time to pass |
|---|---|---|---|---|---|---|
| $250 | 2% | 33% | 74% | 84% | 35% | about 4 months |
| **$350** | 8% | 54% | 79% | **80%** | **44%** | **about 2.5 months** |
| $450 | 21% | 75% | 84% | 69% | 26% | about 1.5 months |

Fees per pass at $350 come to about $100 ($39 plus two or three extensions, spread over the attempts that fail).

Balance-dependent schedules ($450 dropping to $250 below the start, $250 rising to $450 after +$1,000, $450 dropping to $250 after +$1,500) did not beat flat $350 in a way worth trusting, and all were worse if the edge is smaller than measured.

The plan:
- **Position Loss account, flat $350 risk, extend as needed.** Expect 2–3 months. About 80% pass if the backtested edge holds. Don't raise risk because it feels slow; the $350 row holds up best when the edge is weaker than measured.
- $450 passes faster in the real sequence but drops to 69% in the resampling and 26% with a weaker edge. It is the fallback only if you can't keep paying $19 a month.
- **The edge is the whole game.** Cutting it by 0.1R per trade halves the pass rate; removing it leaves 10–20%. Conversely, an order-flow filter that adds 0.1R pushes the pass rate well above 80% and shortens the time. That is what the forward-test journal measures.
- Extensions must be bought before the account expires, from the dashboard "EXTEND" button. Set a reminder at day 25 of every 30.
