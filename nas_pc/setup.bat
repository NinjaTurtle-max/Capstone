@echo off
REM 필요한 패키지 설치 후 버전 확인. 마지막 줄이 OK 로 시작하면 정상.
cd /d %~dp0
call _env.bat
"%PY%" -m pip install --quiet -r requirements.txt
"%PY%" -c "import numpy, pandas, pyarrow, netCDF4, xarray; print('OK numpy', numpy.__version__, 'pandas', pandas.__version__, 'pyarrow', pyarrow.__version__, 'netCDF4', netCDF4.__version__, 'xarray', xarray.__version__)"
pause
