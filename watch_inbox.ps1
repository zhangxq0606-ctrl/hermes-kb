# Hermes KB - Inbox 监控脚本
# 监听 inbox 目录，有新文件时自动跑 pipeline + push
# 无新文件时安静等待，不空跑

$scriptDir = "D:\hermes-kb"
$inboxDir = "$scriptDir\kb\inbox"
$python = "C:\Users\qqmin06\python-sdk\python3.13.2\python.exe"

Write-Host "[watch] 开始监控 inbox: $inboxDir"
Write-Host "[watch] 有新文件会自动处理，Ctrl+C 停止"

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $inboxDir
$watcher.Filter = "*.md"
$watcher.IncludeSubdirectories = $false
$watcher.EnableRaisingEvents = $true

$lastRun = [DateTime]::MinValue
$cooldown = 30  # 30秒冷却，避免同一批文件重复触发

$action = {
    $now = Get-Date
    $global:lastRun = $now
    
    Write-Host ""
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 检测到新文件，开始处理..."
    
    Set-Location $scriptDir
    
    # 0) 先从服务器拉取变更
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 拉取服务器变更..."
    $env:GIT_SSH_COMMAND = "ssh -i C:/Users/qqmin06/.ssh/trae_deploy_key -o StrictHostKeyChecking=no"
    git fetch server main 2>&1
    if (git rev-parse --verify --quiet server/main) {
        git merge -Xtheirs --no-edit server/main 2>&1
    }
    
    # 1) 再从 GitHub 拉取远程更新
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 拉取 GitHub 更新..."
    git pull origin main --rebase=false 2>&1
    
    # 1) 跑 Pipeline
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 执行 Pipeline..."
    & $python "$scriptDir\kb\main.py" 2>&1 | ForEach-Object { Write-Host $_ }
    
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Pipeline 异常，跳过 push"
        return
    }
    
    # git push
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 推送至 GitHub..."
    git add -A 2>&1 | Out-Null
    git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
    git push origin main 2>&1 | ForEach-Object { Write-Host $_ }
    
    if ($LASTEXITCODE -eq 0) {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 完成！服务器将在 1 分钟内更新。"
    }
}

$onCreated = Register-ObjectEvent $watcher "Created" -Action $action
$onRenamed = Register-ObjectEvent $watcher "Renamed" -Action $action

Write-Host "[watch] 就绪，等待新笔记..."

try {
    while ($true) {
        Start-Sleep -Seconds 5
    }
} finally {
    Unregister-Event $onCreated.Id
    Unregister-Event $onRenamed.Id
    $watcher.Dispose()
}
