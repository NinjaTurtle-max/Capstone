@echo off
REM 2020-2024 한반도 슬라이스 전체를 순차 실행. 로그 logs\run_all.log, 결과 data\_manifest\INVENTORY.md
REM 재개형: 중간에 멈추면 같은 bat 를 다시 실행한다 (끝난 달은 건너뜀). 메모리가 부족하면 --workers 4 를 2 로 낮춘다.
cd /d %~dp0
call _env.bat
if not exist logs mkdir logs
set "LOG=logs\run_all.log"
echo ===== %DATE% %TIME% 시작 >> "%LOG%"
"%PY%" -u scripts\selftest.py >> "%LOG%" 2>&1 || goto fail
"%PY%" -u scripts\slice_tropomi.py --months 202001-202312 --workers 4 >> "%LOG%" 2>&1 || goto fail
"%PY%" -u scripts\slice_tropomi.py --months 202401-202412 --workers 4 >> "%LOG%" 2>&1 || goto fail
"%PY%" -u scripts\slice_era5.py --months 202001-202412 --kinds sl,pbl,oro,pl >> "%LOG%" 2>&1 || goto fail
"%PY%" -u scripts\inventory.py --ref pilot_mac_manifest >> "%LOG%" 2>&1 || goto fail
echo ===== %DATE% %TIME% 완료 >> "%LOG%"
echo 완료 - data\_manifest\INVENTORY.md 확인
pause
exit /b 0

:fail
echo ===== %DATE% %TIME% 실패 >> "%LOG%"
echo 실패 - %LOG% 끝부분 확인. 같은 bat 를 다시 실행하면 이어서 진행한다.
pause
exit /b 1
