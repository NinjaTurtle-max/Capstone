@echo off
REM 자체 시험 (수 분). 마지막에 SELFTEST OK 와 종료 코드 0 이 나와야 본 실행을 한다. 로그 logs\selftest.log
cd /d %~dp0
call _env.bat
if not exist logs mkdir logs
"%PY%" -u scripts\selftest.py > logs\selftest.log 2>&1
set RC=%ERRORLEVEL%
type logs\selftest.log
echo 종료 코드 %RC% (0 이면 통과)
pause
