@echo off
chcp 65001 >nul
cd /d "%~dp0"
rem 用通配符读取 spec，避免 cmd 在 UTF-8 代码页下截断中文文件名。
for %%f in (*.spec) do python -m PyInstaller --noconfirm --clean "%%~ff"
if errorlevel 1 (
  echo.
  echo 打包失败，请检查上方错误信息。
  pause
  exit /b 1
)
echo.
echo 打包完成：dist\造梦西游4活动工具箱\
pause
