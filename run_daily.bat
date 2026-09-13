@echo off
REM Wrapper used by Windows Task Scheduler to run the daily agent.
REM Activates the project's virtual environment and runs main.py, with
REM the working directory forced to this folder so relative paths
REM (.env, logs/, reports_archive/) resolve correctly regardless of what
REM directory Task Scheduler starts in.

cd /d "%~dp0"
call ".venv\Scripts\activate.bat"
python main.py
