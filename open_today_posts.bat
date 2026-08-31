@echo off
REM ============================================================
REM  open_today_posts.bat
REM  Opens today's generated posts/*.md files (single tweets and
REM  threads) in Notepad, one window per file, so they can be
REM  copy-pasted straight into X without going through GitHub's
REM  web UI.
REM
REM  Double-click this file to run it.
REM ============================================================

setlocal enabledelayedexpansion

cd /d "C:\Users\makot\Desktop\RakutenAI-Affiliate"

REM --- Get today's date as YYYY-MM-DD regardless of locale/date format ---
for /f "usebackq delims=" %%D in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd'"`) do set "TODAY=%%D"

REM --- Pull the latest drafts from GitHub before searching, so posts pushed
REM     by another machine/session (e.g. the 4am scheduled task) show up
REM     here too. If the pull fails (no network, conflict, etc.), warn and
REM     keep going with whatever is already on disk instead of giving up. ---
echo Pulling latest changes from GitHub...
git pull origin main
if errorlevel 1 (
    echo.
    echo WARNING: git pull failed ^(network error, merge conflict, etc.^).
    echo Continuing with the posts already on disk.
    echo.
)

echo Looking for posts dated %TODAY% in posts\ ...

set "FOUND=0"
for %%F in ("posts\%TODAY%_*.md") do (
    set "FOUND=1"
    echo Opening: %%~nxF
    start "" notepad "%%F"
)

if "!FOUND!"=="0" (
    echo.
    echo No posts found for %TODAY% in posts\.
    echo ^(daily_research.bat may not have run yet today, or generation
    echo  is still in progress.^)
    pause
)

endlocal
