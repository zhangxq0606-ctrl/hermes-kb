$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-WindowStyle Hidden -NoProfile -File D:\hermes-kb\auto_sync.ps1" -WorkingDirectory "D:\hermes-kb"
Set-ScheduledTask -TaskName HermesAutoSync -Action $action
schtasks /delete /tn HermesElevatedFix /f > $null 2>&1
Remove-Item "D:\hermes-kb\_elevated_fix.ps1" -Force
Remove-Item "D:\hermes-kb\_fix_hidden.bat" -Force
