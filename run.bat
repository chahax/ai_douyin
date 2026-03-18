@echo off
setlocal

:: Set PYTHONPATH to current directory
set PYTHONPATH=%~dp0

:: Set HuggingFace Mirror (for China mainland users)
set HF_ENDPOINT=https://hf-mirror.com

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Error: Python is not installed or not in PATH.
    pause
    exit /b 1
)

:: Run the generator
:: Usage: run.bat [count] [voice]
:: Example: run.bat 1 zh-CN-YunyangNeural

set COUNT=1
if not "%1"=="" set COUNT=%1

set VOICE=zh-CN-YunyangNeural
if not "%2"=="" set VOICE=%2

echo Starting WisdomAI Generator...
echo Generating %COUNT% video(s) using voice %VOICE%...

python main.py generate --count %COUNT% --voice %VOICE%

if %errorlevel% neq 0 (
    echo Generation failed.
    pause
    exit /b 1
)

echo Generation completed successfully.
pause
