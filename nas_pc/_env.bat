@echo off
REM 공통 환경: Python 경로, UTF-8 출력. 다른 bat 가 call 로 불러 쓴다.
REM NAS 루트는 config.py 가 C-H 드라이브 중 dataset\NO2-Proxy-XCO2 가 있는 곳을 자동 탐지한다.
REM 자동 탐지가 틀리면 아래 CAP_NAS_MOUNT 줄의 REM 을 지우고 드라이브를 고친다 (예: E:\).
chcp 65001 >nul
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
set "PY=python"
if exist "C:\nas_fetch_win\venv\Scripts\python.exe" set "PY=C:\nas_fetch_win\venv\Scripts\python.exe"
if exist "%USERPROFILE%\nas_fetch_win\venv\Scripts\python.exe" set "PY=%USERPROFILE%\nas_fetch_win\venv\Scripts\python.exe"
REM set "CAP_NAS_MOUNT=E:\"
echo Python: %PY%
