@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

title FunPlus Auth 一键刷新
echo ============================================
echo   FunPlus Zone 登录态一键刷新
echo   1) 打开浏览器，请完成邮箱验证码登录
echo   2) 自动导出并更新 GitHub Secret
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 python，请先安装 Python 并加入 PATH。
  goto :fail
)

where gh >nul 2>nul
if errorlevel 1 (
  echo [错误] 未找到 gh。请安装 GitHub CLI 并执行: gh auth login
  goto :fail
)

gh auth status >nul 2>nul
if errorlevel 1 (
  echo [错误] gh 未登录。请先执行: gh auth login
  goto :fail
)

echo [1/3] 检查依赖...
python -c "import playwright,requests" >nul 2>nul
if errorlevel 1 (
  echo 正在安装依赖 requirements.txt ...
  python -m pip install -r requirements.txt
  if errorlevel 1 goto :fail
  python -m playwright install chromium
  if errorlevel 1 goto :fail
)

echo [2/3] 打开登录页，请在弹出的 Chromium 中完成登录...
echo.
set PYTHONUNBUFFERED=1
set PYTHONIOENCODING=utf-8
python -u export_auth.py --push-secret
set ERR=%ERRORLEVEL%
echo.
if not "%ERR%"=="0" (
  echo [失败] 导出或上传 Secret 未成功，错误码: %ERR%
  goto :fail
)

echo [3/3] 可选：立刻手动跑一次 GitHub Actions 验证
choice /C YN /M "是否现在触发一次 FunPlus 每日签到 workflow"
if errorlevel 2 goto :done
if errorlevel 1 (
  gh workflow run "FunPlus 每日签到"
  if errorlevel 1 (
    echo 触发失败，可稍后在 GitHub Actions 页面手动 Run workflow。
  ) else (
    echo 已触发。请到仓库 Actions 查看结果。
  )
)

:done
echo.
echo 全部完成。可关闭本窗口。
pause
exit /b 0

:fail
echo.
echo 处理失败。常见原因：
echo  - 浏览器里没有登录成功 / 超时
echo  - gh 未登录或没有仓库权限
echo 请修好后重新双击本文件。
pause
exit /b 1
