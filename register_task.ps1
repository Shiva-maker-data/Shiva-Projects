<#
Registers (or re-registers) the Windows Task Scheduler job that runs the
daily NIFTY/SENSEX agent every weekday morning.

Usage (run from a normal PowerShell prompt in this folder):
    .\register_task.ps1

Change $TaskTime below if you'd like a different run time.
#>

$TaskName = "NiftySensexDailyAgent"
# 24h HH:mm, IST. 10:30 (not pre-market) is deliberate: Intraday's opening-
# range/gap/VWAP logic needs the market to have actually been open for a
# while to have real same-day data -- run before 9:15 open and it silently
# falls back to describing YESTERDAY's session as if it were today's.
# Short-Term/Long-Term don't care (driven by 20/50/200-day trends, not the
# first hour of one session) and still get the rest of the day to act on.
$TaskTime = "10:30"
$ScriptDir = $PSScriptRoot
$BatPath = Join-Path $ScriptDir "run_daily.bat"

if (-not (Test-Path $BatPath)) {
    Write-Error "run_daily.bat not found at $BatPath"
    exit 1
}

$Action = New-ScheduledTaskAction -Execute $BatPath -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $TaskTime
# StartWhenAvailable: if 10:30 is missed (laptop off/asleep), catch up and
# run as soon as you next log in, instead of skipping the day entirely.
# AllowStartIfOnBatteries / (no StopIfGoingOnBatteries): this is a laptop
# and the whole run takes ~10-15 seconds -- no real reason to gate it on
# being plugged in, or to kill it mid-run if you unplug (Task Scheduler's
# default behavior is both of those, meant for much heavier tasks).
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries
$Settings.StopIfGoingOnBatteries = $false

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Runs the personal NIFTY 50 / SENSEX daily technical-analysis email agent." | Out-Null

Write-Output "Task '$TaskName' registered: runs Mon-Fri at $TaskTime."
Write-Output "To test it immediately: Start-ScheduledTask -TaskName '$TaskName'"
Write-Output "To view status/history: open Task Scheduler (taskschd.msc) and find '$TaskName'."
