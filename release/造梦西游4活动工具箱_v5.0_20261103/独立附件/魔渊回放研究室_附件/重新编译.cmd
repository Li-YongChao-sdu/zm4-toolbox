@echo off
chcp 65001 >nul
cd /d "%~dp0"
if "%~1"=="" goto usage
if not exist build mkdir build
call "%~1" -importScript "original\v5870.swf" "build\v5870.json_lab_rebuilt.swf" "patched_as"
if errorlevel 1 goto failed
call "%~1" -selectclass controllers.battle.qc2.SimulateServerFrame,controllers.battle.qc2.PlayPvpVideoCmd,controllers.battle.qc2.PlayVideoServerFrame,controllers.battle.qc2.maplogic.MapZhuXie,org.idream.pomelo.Pomelo,controllers.battle.qc2.gameovers.GameOverZhuXie -export script "build\readback_rebuilt" "build\v5870.json_lab_rebuilt.swf"
if errorlevel 1 goto failed
echo 编译和导出完成，仍需核对读回代码与游戏内运行。
goto end
:usage
echo 用法：重新编译.cmd "本机FFDec目录\ffdec.bat"
goto end
:failed
echo 编译或导出失败。
:end
pause
