@echo off
schtasks /change /tn HermesAutoSync /tr "PowerShell.exe -WindowStyle Hidden -NoProfile -File D:\hermes-kb\auto_sync.ps1"
if %errorlevel%==0 (
    echo 成功！定时任务已设为隐藏窗口模式。
    del "%~f0"
) else (
    echo 失败，请以管理员身份运行。
    pause
)
