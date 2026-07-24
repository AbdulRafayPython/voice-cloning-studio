@echo off
echo =========================================
echo Setting up Zenvyrolabs Voice Studio (local)
echo =========================================

REM Python 3.11 is REQUIRED (3.12+ breaks the AI libraries).
echo Creating virtual environment with Python 3.11...
py -3.11 -m venv venv
if not exist "venv\Scripts\python.exe" (
    echo.
    echo ERROR: Could not create the venv. Install Python 3.11 first:
    echo     winget install --id Python.Python.3.11 -e
    exit /b 1
)

echo Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip

echo Installing PyTorch (CPU build - portable, no NVIDIA required)...
REM For an NVIDIA GPU instead, use: --index-url https://download.pytorch.org/whl/cu121
venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu

echo Installing other dependencies...
venv\Scripts\python.exe -m pip install -r requirements.txt

echo =========================================
echo Setup Complete!  You also need FFmpeg on PATH:
echo     winget install --id Gyan.FFmpeg -e
echo Run the app with:  run.bat
echo =========================================
