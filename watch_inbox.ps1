# Hermes KB - Inbox 监控脚本
# 监听 inbox 目录，有新文件时自动跑 pipeline + build 静态站 + git push
# 依赖 GitHub 做中间人同步，不再需要 scp 直连服务器

$scriptDir = "D:\hermes-kb"
$inboxDir = "$scriptDir\kb\inbox"
$python = "C:\Users\qqmin06\python-sdk\python3.13.2\python.exe"

# 互斥锁：防止多个 watcher 实例冲突
$lockFile = "$scriptDir\.sync.lock"
if (Test-Path $lockFile) {
    $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "[watch] 已有进程(PID:$lockPid)在运行，退出"
        exit 0
    }
}
$PID | Set-Content $lockFile -ErrorAction SilentlyContinue

Write-Host "[watch] 开始监控 inbox: $inboxDir"
Write-Host "[watch] 新笔记到达后将自动处理"

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $inboxDir
$watcher.Filter = "*.md"
$watcher.IncludeSubdirectories = $false
$watcher.EnableRaisingEvents = $true

$global:lastRun = [DateTime]::MinValue

$action = {
    $now = Get-Date
    # 防抖 60 秒
    if (($now - $global:lastRun).TotalSeconds -lt 60) { return }
    $global:lastRun = $now
    $nowStr = $now.ToString('HH:mm:ss')
    Write-Host "`n[$nowStr] 检测到新文件，开始处理..."
    Set-Location $using:scriptDir
    Write-Host "[$nowStr] 拉取 GitHub 更新..."
    git pull origin main --rebase=false 2>&1 | Out-Null
    Write-Host "[$nowStr] 执行 Pipeline..."
    & $using:python "$using:scriptDir\kb\main.py" 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
    Write-Host "[$nowStr] 重建静态站..."
    & $using:python "$using:scriptDir\kb\scripts\build_static.py" 2>&1 | Select-Object -Last 1 | ForEach-Object { Write-Host $_ }
    Write-Host "[$nowStr] 推送至 GitHub..."
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin main 2>&1 | Out-Null
        Write-Host "[$nowStr] 完成"
    } else {
        Write-Host "[$nowStr] 无变更"
    }
}

$null = Register-ObjectEvent $watcher "Created" -Action $action
$null = Register-ObjectEvent $watcher "Renamed" -Action $action

Write-Host "[watch] 就绪，等待新笔记..."

try { while ($true) { Start-Sleep -Seconds 5 } }
finally {
    Remove-Item $lockFile -ErrorAction SilentlyContinue
}
