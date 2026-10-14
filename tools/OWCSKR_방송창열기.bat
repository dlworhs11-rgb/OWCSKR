@echo off
rem OWCSKR broadcast window: separate Chrome profile that keeps rendering video when covered or on another desktop.
rem usage: double-click (opens the Week 2 Day 3 VOD), or drag a SOOP URL onto this file.
set "URL=%~1"
if "%URL%"=="" set "URL=https://vod.sooplive.com/player/209539901"
set "CHROME=C:\Program Files\Google\Chrome\Application\chrome.exe"
set "PROFILE=%LOCALAPPDATA%\OWCSKR\broadcast-profile"
start "" "%CHROME%" --user-data-dir="%PROFILE%" --new-window --window-size=1920,1080 --mute-audio --disable-features=CalculateNativeWinOcclusion --disable-backgrounding-occluded-windows --disable-renderer-backgrounding --disable-background-timer-throttling --autoplay-policy=no-user-gesture-required "%URL%"
