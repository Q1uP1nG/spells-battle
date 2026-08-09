@echo off
setlocal
cd /d "%~dp0"

set TOOL=tools\retrain_gesture_templates.py
set REVIEWED=models\gesture_reviewed_samples.jsonl
set OUTPUT=models\gesture_templates.json
set BANK=models\gesture_template_bank.json

echo Retraining gesture templates...
echo Template bank: %BANK%
echo Reviewed samples: %REVIEWED%
echo Output model: %OUTPUT%
echo.

python --version >nul 2>nul
if %errorlevel%==0 (
    python %TOOL% --bank %BANK% --reviewed %REVIEWED% --output %OUTPUT% --slot-count 30 --k 7 --min-samples 8
    goto done
)

py -3 --version >nul 2>nul
if %errorlevel%==0 (
    py -3 %TOOL% --bank %BANK% --reviewed %REVIEWED% --output %OUTPUT% --slot-count 30 --k 7 --min-samples 8
    goto done
)

echo Python was not found. Please install Python or add it to PATH.

:done
echo.
pause
