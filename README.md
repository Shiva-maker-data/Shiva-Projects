# NIFTY 50 / SENSEX Daily Watchlist Agent

A personal, automated agent that scans the NIFTY 50 + SENSEX universe every
day, runs a transparent rule-based technical analysis for **Intraday**,
**Short-Term (swing)**, and **Long-Term** setups, and emails you a ranked
watchlist with entry zone, target(s) (with %), and stop-loss (with %) for
each pick.

Short-Term and Long-Term picks are tracked across runs (`positions.py`,
state in `state/open_positions.json`): once a stock is suggested, it won't
be suggested again while that idea is still "open" -- instead, each email
opens with a **Position Updates** section reporting what happened to
earlier picks once they actually hit target1, hit the stop-loss, or timed
out past their horizon. Intraday isn't tracked this way since it squares
off same-day by design. (Long-Term conditions like "above the 200-day SMA"
barely change day to day, so without this the same name could otherwise
get re-suggested for a week straight or more -- confirmed empirically
before this was added: Long-Term picks repeated ~2 of 3 slots day-over-day
on average, vs ~0.2 of 3 for Short-Term.)

## What this is (and isn't)

- **Is:** a decision-support tool. It fetches real price/volume data,
  computes standard indicators (RSI, MACD, SMAs, Bollinger Bands, ATR,
  volume trends, VWAP), scores each stock 0-100 per horizon based on how
  many bullish conditions line up, and shows you the exact reasons behind
  every score.
- **Isn't:** a guarantee of profit, insider information, or SEBI-registered
  investment advice. It's a heuristic screener you're using for your own
  personal research. Every email includes a disclaimer and every pick
  includes a stop-loss because **losses are possible on any single idea** --
  respect the stop-loss and size positions sensibly.
- Data comes from two free sources: Yahoo Finance for OHLCV history (the
  ONLY source actually used for every RSI/MACD/SMA/target/stop-loss
  calculation), plus a secondary cross-check against NSE India's public
  quote API purely as a sanity check on the displayed price. In practice,
  NSE's site blocks essentially all automated requests (confirmed running
  from both a home network and GitHub's cloud servers -- it's bot-detection
  on NSE's end, not fixable by better headers), so expect that cross-check
  to be unavailable most/all of the time. This does NOT affect analysis
  quality -- NSE's price was never an input to any calculation, only a
  redundant confirmation. See `data_sources.py` for a documented extension
  point to add a broker API (Zerodha Kite / Upstox) later for genuine
  exchange-grade data if that redundancy matters to you.

## Rule engine v2 -- audit, redesign, and what actually changed

The original (v1) engine scored each stock on isolated technical
indicators only. An audit (done deliberately adversarially, not just
describing the existing code) found real, specific problems:

1. **No market regime gate** -- a breakout during a market-wide selloff
   scored identically to one during a broad rally.
2. **No sector confirmation or relative strength** -- pure single-stock
   technicals, blind to whether a stock's sector/the index was
   leading or lagging.
3. **Correlated indicators double-counted** -- MACD, RSI, and Bollinger
   Band position all substantially measure the same underlying "momentum
   turning" signal, but were scored and summed independently, inflating
   apparent conviction without genuinely independent confirmation.
4. **Entry zone wasn't structure-based** -- always a fixed tiny band
   around whatever price happened to be, so the system could never say
   "you've already missed this, don't chase."
5. **No position sizing, no confidence measure separate from score, no
   explicit data-quality gate, no multi-timeframe conflict check for
   Intraday, and the backtest was descriptive (hit-rate only), not
   rigorous** (no expectancy, profit factor, drawdown, or train/OOS split).

v2 addresses all of these -- see `config.py` (every weight/threshold,
named and centralized), `market_regime.py` (NIFTY trend/momentum/
volatility classification), `sector.py` (sector trend + relative strength
vs NIFTY, manually mapped where a genuinely good free sector-index fit
exists -- deliberately left unmapped elsewhere rather than forced),
`position_sizing.py` (risk-based, grade-scaled sizing), and the rewritten
`analyzer.py` (weighted, non-double-counted scoring; SCORE vs CONFIDENCE as
separate numbers; structure-derived entry with chase detection; a
STRONG BUY/BUY/WATCH/NO TRADE classification -- **no fabricated
SELL/STRONG SELL signal**, since this is long-only NSE cash-equity in
scope and retail cash accounts can't short; "should I exit" is answered by
`positions.py`'s target/stop-loss tracking instead).

**One explicit, important limitation:** the backtest validates the Market
Regime factor point-in-time (same NIFTY-regime-bundle approach as
`IndicatorBundle`, no lookahead), but Sector Strength and Relative
Strength are NOT yet point-in-time backtested (they fall back to neutral
defaults in `backtest.py`, same as the live path does when that data is
genuinely unavailable) -- extending the point-in-time approach to ~9
sector indices with correct date alignment is real follow-up work, not
done here. Backtested scores are therefore not identical in magnitude to
what ships live.

## Backtested performance -- read this before trusting a score or a grade

Real numbers from a 3-year / 51-symbol / 10,617-simulated-trade v2
backtest run (`compute_performance_metrics` in `backtest.py` -- win rate,
expectancy, profit factor, max drawdown, Sharpe/Sortino-like ratios, a
regime-bucket breakdown, and a train/out-of-sample split by entry date):

- **The 20%-in-90-days target still shows no edge, and it gets worse at
  higher score cutoffs**, exactly as the earlier v1 backtest found: hit
  rate 5.0% (score>=0) -> 4.3% (>=40) -> 3.5% (>=60).
- **Judged by the tool's own target1/stop-loss objective, expectancy is
  at or slightly below breakeven across the board**: +0.03%/trade at
  score>=0, -0.05%/trade at the live default (>=40), -0.18%/trade at
  >=60 (profit factor 1.02 -> 0.97 -> 0.91). Higher score does not mean
  better realized outcome in this window.
- **A genuinely important, counter-intuitive finding from the regime
  breakdown, reported exactly as measured, not softened:** stocks
  signaled during a BULLISH market regime performed *worst*
  (expectancy -0.81%/trade, profit factor 0.63, n=447), while stocks
  signaled during STRONG_BEARISH performed *best*
  (expectancy +0.79%/trade, profit factor 1.46, n=312). This is the
  opposite of the Market Regime factor's design assumption ("bearish
  market = suppress the score"), which was built directly from the
  request's own specification ("if NIFTY is strongly bearish, do not
  aggressively recommend long positions"). Plausible explanations
  (mean-reversion bounces off oversold conditions outperforming
  already-extended "everything is bullish" entries) exist, but so does
  the simpler one: this is one 3-year window's specific character, not a
  validated causal pattern. **Do not conclude the regime gate should be
  flipped from this alone** -- it's exactly the kind of result that needs
  more history/regimes before acting on, and is reported here specifically
  so it isn't hidden.
- **Train/out-of-sample split is at least time-consistent**: expectancy
  -0.05%/trade (train, Jul 2024-Jun 2025) vs -0.06%/trade (out-of-sample,
  Jun 2025-Jun 2026) -- nearly identical. Rule weights were fixed before
  this backtest was ever run and never adjusted based on its results, so
  this isn't a classic overfitting check, but it does show the (thin,
  roughly-breakeven) edge isn't being driven by one lucky/unlucky stretch.
- Per-symbol pattern is unchanged from v1: SHRIRAMFIN, ETERNAL, TRENT,
  JIOFIN, ADANIENT show the best 20%-hit-rates (7-26%); TCS, ITC, WIPRO,
  INFY, HCLTECH, HINDUNILVR show 0%. Same caveats as before (survivorship
  bias, single window) apply.
- Max drawdown figures assume each trade consumes a fixed ~2% slice of
  capital compounding sequentially (roughly a 50-position diversified
  book) -- naively compounding 100% of capital into one trade at a time
  produces a meaningless near-total-wipeout number over thousands of
  trades regardless of the real edge, so that naive version is
  deliberately not used (see `backtest.py`'s `PORTFOLIO_ALLOCATION_PER_TRADE`).

**Practical takeaway used in this project:** live daily picks are NOT
filtered by any specific target-return threshold -- they're the
highest-scoring, regime/sector-adjusted setups per category that also
clear the RR/no-chase/no-hostile-regime gates in `analyzer.py`. Treat
Score as "how many weighted rules line up," Confidence as "how much the
evidence agrees," and neither as a calibrated probability of profit --
the numbers above are the actual, measured reason why.

Re-run it yourself periodically (methodology and CLI flags are documented
in the module docstring):
```powershell
.venv\Scripts\python.exe backtest.py --min-scores 0,40,60 --history 3y
```
Full trade-by-trade logs and summaries land in `backtest_results/`.

Unit tests for the critical calculations (indicators, regime
classification, RR/grading math, position sizing, chase detection, data
quality, and the point-in-time lookahead-safety guarantee itself) live in
`tests/test_engine.py`:
```powershell
.venv\Scripts\python.exe -m pytest tests/ -v
```

## One-time setup

### 1. Create a virtual environment and install dependencies

```powershell
cd "C:\Users\Shivam Pandey\Documents\Python_scripts\nifty_sensex_daily_agent"

# NOTE: if plain `python` on your PATH opens the Microsoft Store instead of
# running Python, that's the Windows "App execution alias" stub, not a real
# interpreter. Point venv at a real Python install instead, e.g. the conda
# env this project's venv was originally built from:
# & "C:\Users\Shivam Pandey\miniconda3\envs\ml_ai\python.exe" -m venv .venv
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

> If PowerShell blocks the activation script, run this once (in an admin
> PowerShell) then retry: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`

### 2. Generate a Gmail App Password (for sending the email)

App Passwords let a script send mail through your Gmail account without
using (or exposing) your real password, and only work once 2-Step
Verification is on.

1. Go to https://myaccount.google.com/security
2. Turn on **2-Step Verification** if it isn't already on.
3. Go to https://myaccount.google.com/apppasswords
4. Create a new app password (name it e.g. "nifty-agent"), and copy the
   16-character code it gives you.

You can use `nexora11.data@gmail.com` itself as the sending account (it
emails itself), or a separate Gmail account -- either works.

### 3. Configure your secrets

```powershell
copy .env.example .env
notepad .env
```

Fill in `EMAIL_SENDER`, `EMAIL_APP_PASSWORD` (the 16-char code from step 2,
no spaces), and confirm `EMAIL_RECIPIENT` (defaults to
`nexora11.data@gmail.com`). `ANTHROPIC_API_KEY` is optional -- leave it
blank to use the built-in template rationale text, or set it to have
Claude write a slightly more polished explanation for each pick.

### 4. Test it manually

```powershell
python main.py
```

This scans the full universe (takes a few minutes), archives the HTML
report to `reports_archive/`, and emails it. Check `logs/` if anything
fails -- every step logs clearly, and a failed email still leaves the
report saved locally so nothing is lost.

### 5. Schedule it to run automatically every weekday morning

```powershell
.\register_task.ps1
```

This registers a Windows Task Scheduler job (`NiftySensexDailyAgent`) that
runs `run_daily.bat` every Mon-Fri at 10:30 (deliberately ~75 min after the
09:15 market open, not before it -- see the comment in `register_task.ps1`
for why: Intraday's opening-range/gap/VWAP logic needs the market to
actually be open to have real same-day data), using the exact venv you set
up in step 1. Requires this PC to be on at that time.

- Test the scheduled task immediately: `Start-ScheduledTask -TaskName 'NiftySensexDailyAgent'`
- Change the run time: edit `$TaskTime` in `register_task.ps1` and re-run it
- View run history: open Task Scheduler (`taskschd.msc`) → find the task → History tab

**Hard limit of this approach:** Task Scheduler can only run when the PC is
genuinely on. `-StartWhenAvailable` (already set) makes it catch up as soon
as you next log in if a run was missed, but a PC that's fully shut down
cannot be started by software -- see "Cloud deployment" below for a fix
that removes this dependency entirely.

### 6. (Optional, recommended) Cloud deployment via GitHub Actions

Removes the "your PC must be on" dependency completely by running the
script on GitHub's own servers on a schedule, independent of this machine.
Free for a job this small. What's already prepared for you:
- `.github/workflows/daily_report.yml` -- the scheduled workflow (Mon-Fri,
  same 10:30 IST time), plus a manual "Run workflow" button for testing
- `.gitignore` -- excludes `.env`, `.venv/`, logs, and archived reports;
  deliberately keeps `state/open_positions.json` tracked, since that's the
  one thing that needs to survive between runs when there's no persistent
  local disk (GitHub Actions checks out a fresh copy every run) -- the
  workflow commits updates to just that file back to the repo each time.

What you need to do (one-time, needs your own GitHub account -- this part
can't be done on your behalf):
1. Install Git for Windows (https://git-scm.com/download/win) if you don't
   have it, and create a free GitHub account if you don't have one.
2. Create a new **private** repository on GitHub (don't initialize it with
   a README -- this folder already has one).
3. In that repo: **Settings → Actions → General → Workflow permissions** →
   select "Read and write permissions" → Save. (Required for the workflow
   to be able to commit the state file back.)
4. In that repo: **Settings → Secrets and variables → Actions → New
   repository secret** -- add `EMAIL_SENDER`, `EMAIL_APP_PASSWORD`,
   `EMAIL_RECIPIENT` (and optionally `ANTHROPIC_API_KEY`) with the same
   values as your local `.env`. Secrets are encrypted and never shown in
   logs, safe even in a public repo -- but keep this one private anyway
   since the code itself is personal.
5. From this folder in PowerShell (after installing Git):
   ```powershell
   git init
   git add .
   git commit -m "Initial commit"
   git branch -M main
   git remote add origin https://github.com/<your-username>/<your-repo>.git
   git push -u origin main
   ```
6. On GitHub, open the **Actions** tab → "Daily NIFTY/SENSEX Watchlist" →
   **Run workflow** to fire a manual test without waiting for the schedule.
7. Once that test email arrives successfully, disable the local Task
   Scheduler job (`Unregister-ScheduledTask -TaskName 'NiftySensexDailyAgent' -Confirm:$false`)
   so you don't get two emails a day.

### 7. (Optional) Google Sheets export -- for accuracy tracking over time

Logs every day's suggestions to one tab and every resolved outcome (target
hit / stopped out / timed out, with the real return) to another, so they
accumulate into clean, aggregatable data -- what you'd actually need before
trusting any accuracy claim, or before training a real model on the same
features someday instead of hand-tuned rule weights. Entirely optional and
degrades to a no-op if not configured; never affects the email if it fails.

One-time setup (needs your own Google account):
1. Create a Google Sheet (sheets.google.com) -- any name. Copy its **Sheet
   ID** from the URL: `docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`
2. Go to **console.cloud.google.com** → create a project (or use an
   existing one) → **APIs & Services → Library** → search "Google Sheets
   API" → **Enable**
3. **APIs & Services → Credentials → Create Credentials → Service
   Account** → give it any name → Create and continue → Done
4. Click into the new service account → **Keys** tab → **Add Key → Create
   new key → JSON** → this downloads a `.json` file. Keep it private, it's
   a credential.
5. Open that JSON file, copy the `"client_email"` value (looks like
   `xxxx@xxxx.iam.gserviceaccount.com`) → go back to your Google Sheet →
   **Share** → paste that email → give it **Editor** access → Send
6. Add two GitHub Secrets (Settings → Secrets and variables → Actions):
   - `GOOGLE_SHEET_ID` -- the ID from step 1
   - `GOOGLE_SERVICE_ACCOUNT_JSON` -- the ENTIRE content of the downloaded
     `.json` file, pasted as-is
7. Run the workflow (manual trigger or wait for the schedule) -- it'll
   auto-create two tabs, "Daily Suggestions" and "Resolutions", the first
   time it successfully writes.

**Known scope limit:** only Short-Term/Long-Term picks get a matching
"Resolutions" row (Intraday isn't position-tracked across days at all --
see `positions.py`). Intraday suggestions still get logged for the record,
but you won't get an accuracy readout on them from this data alone.

## Project layout

| File | Purpose |
|---|---|
| `symbols.py` | NIFTY 50 / SENSEX ticker universe |
| `data_sources.py` | Yahoo Finance + NSE India fetching, cross-checking |
| `indicators.py` | RSI, MACD, SMA/EMA, Bollinger Bands, ATR, VWAP, etc. |
| `config.py` | Every scoring weight/threshold/multiplier, named and centralized |
| `market_regime.py` | NIFTY 50 trend/momentum/volatility classification (live + point-in-time backtest bundle) |
| `sector.py` | Sector index mapping, sector trend, relative strength vs NIFTY |
| `position_sizing.py` | Risk-based, grade-scaled position sizing |
| `analyzer.py` | v2 weighted scoring (regime/sector/momentum/RR-quality/etc.), entry structure + chase detection, grading |
| `positions.py` | Tracks open Short-Term/Long-Term picks across days; closes them out on target/stop/timeout |
| `sheets_export.py` | Logs daily suggestions + resolved outcomes to a Google Sheet (optional) |
| `narrative.py` | Per-pick rationale text (Claude if configured, else template) -- explains the engine's decision, never overrides it |
| `report.py` | HTML email layout: signal/grade/confidence, score breakdown, market snapshot, position sizing |
| `emailer.py` | Gmail SMTP sending |
| `main.py` | Orchestrates the full daily pipeline |
| `backtest.py` | Replays the live scoring rules against history, with expectancy/profit-factor/drawdown/Sharpe-Sortino/train-OOS metrics -- see "Backtested performance" above |
| `tests/test_engine.py` | Unit tests for the critical calculations |
| `register_task.ps1` / `run_daily.bat` | Windows Task Scheduler wiring (local option) |
| `.github/workflows/daily_report.yml` | GitHub Actions wiring (cloud option, recommended) |

## Tuning

Edit values in `.env`:
- `PICKS_PER_CATEGORY` -- how many stocks to show per horizon (default 3)
- `MIN_SCORE` -- minimum score (0-100) to qualify for the email at all (default 40)
- `MAX_WORKERS` -- parallel fetch threads (default 8; lower if you hit rate limits)

Edit `analyzer.py` directly to change the scoring rules or ATR multipliers
used for entry/target/stop-loss -- every rule is commented and self-contained.

## Known limitations

- **Intraday signals use 15-minute data**, not tick data, and Yahoo's feed
  for NSE can lag by up to ~15 minutes. Treat intraday picks as directional
  bias, not a precise timing signal -- for real intraday trading, a broker
  API feed would be materially better.
- **Index constituent lists drift** over time; `symbols.py` notes where to
  verify them periodically.
- This is a **heuristic, not a backtested strategy** -- scores reflect how
  many textbook conditions line up today, not a historically validated
  win rate. Consider paper-trading the picks for a while before risking
  real capital, and never risk more than you can afford to lose.
