@echo off
setlocal
cd /d "%~dp0"

set PORT=8791
set URL=http://127.0.0.1:%PORT%/
set TOOL=tools\review_gesture_samples.py

echo Starting Gesture Review
echo Browser URL: %URL%
echo Keep this window open while reviewing samples.
echo Close this window to stop the review server.
echo Tip: label choices stay pending until you click Retrain.
echo.

python --version >nul 2>nul
if %errorlevel%==0 (
    python "%TOOL%" --port %PORT%
    goto done
)

py -3 --version >nul 2>nul
if %errorlevel%==0 (
    py -3 "%TOOL%" --port %PORT%
    goto done
)

echo Python was not found. Please install Python or add it to PATH.

:done
echo.
pause
