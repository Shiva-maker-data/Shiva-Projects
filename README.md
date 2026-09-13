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

## Backtested performance -- read this before trusting a score

`backtest.py` replays the exact live scoring rules from `analyzer.py`
against historical data (point-in-time correct, no lookahead -- see the
docstrings in both files for the methodology). The honest finding from a
3-year / 51-symbol / 8,771-simulated-trade run:

- **A score >=40 (the live default) does NOT reliably produce >20% returns
  within 90 days.** Hit rate was ~4%, and raising the bar to score >=60
  made the average outcome *worse*, not better -- i.e. the score is not
  predictive of that specific target in this window.
- Judged by the tool's own (much more modest) target1/stop-loss levels
  instead, it's roughly a coin flip before costs: target1 hit ~44-55% of
  the time, stop-loss hit ~40-55% of the time, average return ~0%.
- A handful of higher-beta names (JIOFIN, SHRIRAMFIN, ETERNAL, TRENT,
  ADANIPORTS, BAJFINANCE) cleared a >20%/90-day move noticeably more often
  (~12-23% of signals) than defensive large-caps like TCS/INFY/HCLTECH/ITC
  (~0%) -- plausible (higher beta = fatter tails both ways, and the
  worst-case single trade in the backtest was -52%, so the downside tail is
  comparably fat), but this is three years of one market regime on today's
  index list projected backward, not a validated edge. Treat any per-stock
  tilt from this as a mild, uncertain lean -- not a filter that finds
  winners.

**Practical takeaway used in this project:** the live daily picks are NOT
filtered by any specific target-return threshold -- they're the
highest-scoring setups per category, full 51-stock universe, exactly as
`analyzer.py`'s rules rank them. Treat the score as "how many textbook
bullish conditions line up," not as a probability of hitting any specific
return target.

Re-run it yourself periodically (methodology and CLI flags are documented
in the module docstring):
```powershell
.venv\Scripts\python.exe backtest.py --min-scores 0,40,60 --history 3y
```
Full trade-by-trade logs and summaries land in `backtest_results/`.

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

## Project layout

| File | Purpose |
|---|---|
| `symbols.py` | NIFTY 50 / SENSEX ticker universe |
| `data_sources.py` | Yahoo Finance + NSE India fetching, cross-checking |
| `indicators.py` | RSI, MACD, SMA/EMA, Bollinger Bands, ATR, VWAP, etc. |
| `analyzer.py` | Scoring rules per horizon + entry/target/stop-loss (and %) calculation |
| `positions.py` | Tracks open Short-Term/Long-Term picks across days; closes them out on target/stop/timeout |
| `narrative.py` | Per-pick rationale text (Claude if configured, else template) |
| `report.py` | HTML email layout, incl. the Position Updates section |
| `emailer.py` | Gmail SMTP sending |
| `main.py` | Orchestrates the full daily pipeline |
| `backtest.py` | Replays the live scoring rules against history -- see "Backtested performance" above |
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
