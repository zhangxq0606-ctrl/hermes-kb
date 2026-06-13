$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-WindowStyle Hidden -NoProfile -File D:\hermes-kb\auto_sync.ps1" -WorkingDirectory "D:\hermes-kb"
Set-ScheduledTask -TaskName HermesAutoSync -Action $action
Write-Host "Done"
Remove-Item -Path "D:\hermes-kb\_fix_task.ps1" -Force
