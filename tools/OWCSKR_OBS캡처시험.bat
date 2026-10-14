@echo off
chcp 65001 >nul
rem OWCSKR: start OBS (tray, dedicated scene collection) with a SOOP page and take 6 test captures.
cd /d C:\Users\dlwor\OWCSKR
set "URL=%~1"
if "%URL%"=="" set "URL=https://vod.sooplive.com/player/209539901?change_second=3440"
echo [1/2] OBS 시작 및 장면 준비...
python -I tools\obs_setup.py start "%URL%"
if errorlevel 1 goto fail
echo [2/2] 20초 기다린 뒤 10초 간격으로 6장 캡처...
timeout /t 20 >nul
python -I tools\obs_snap.py 6 10
if errorlevel 1 goto fail
echo.
echo 완료. 결과: C:\Users\dlwor\OWCSKR\data\live\snap_report.txt
pause
exit /b 0
:fail
echo 실패. 이 창의 내용을 캡처해서 알려주세요.
pause
exit /b 1
