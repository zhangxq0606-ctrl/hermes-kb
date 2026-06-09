# Hermes KB - Inbox 监控脚本  
# 监听 inbox 目录，有新文件时自动跑 pipeline + push
# 同时从服务器拉取 Claude Code 写的文件

$scriptDir = "D:\hermes-kb"
$inboxDir = "$scriptDir\kb\inbox"
$python = "C:\Users\qqmin06\python-sdk\python3.13.2\python.exe"
$serverHost = "116.62.220.41"
$sshKey = "C:\Users\qqmin06\.ssh\trae_deploy_key"
$sshOpts = "-i $sshKey -o StrictHostKeyChecking=no"

# 互斥锁
$lockFile = "$scriptDir\.sync.lock"
if (Test-Path $lockFile) {
    $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "[watch] 已有同步进程(PID:$lockPid)在运行，退出"
        exit 0
    }
}
$PID | Set-Content $lockFile -ErrorAction SilentlyContinue

Write-Host "[watch] 开始监控 inbox: $inboxDir"
Write-Host "[watch] 有新文件会自动处理，Ctrl+C 停止"

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $inboxDir
$watcher.Filter = "*.md"
$watcher.IncludeSubdirectories = $false
$watcher.EnableRaisingEvents = $true

$global:lastRun = [DateTime]::MinValue

$action = {
    $now = Get-Date
    if (($now - $global:lastRun).TotalSeconds -lt 30) { return }
    $global:lastRun = $now
    
    Write-Host ""
    Write-Host "[$($now.ToString('HH:mm:ss'))] 检测到新文件，开始处理..."
    
    Set-Location $using:scriptDir
    
    # 0) 从服务器拉取 Claude Code 写的文件（检查更新时间）
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 拉取服务器文件..."
    $serverDirs = @('/var/www/hermes-kb/kb/writing', '/var/www/hermes-kb/kb/core/insight', '/var/www/hermes-kb/kb/core/note', '/var/www/hermes-kb/kb/manual/technical')
    foreach ($sdir in $serverDirs) {
        $localDir = $sdir -replace '/var/www/hermes-kb/', 'D:\hermes-kb\'
        $localDir = $localDir -replace '/', '\'
        if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
        $remoteList = ssh $using:sshOpts root@$using:serverHost "ls -la $sdir/*.md 2>/dev/null" 2>&1
        foreach ($rf in $remoteList) {
            $rf = ($rf.ToString()).Trim()
            if ($rf -eq '' -or $rf -match '^ssh:|^Warning:|^Pseudo|^#|^total') { continue }
            $parts = $rf -split '\s+'
            if ($parts.Count -lt 9) { continue }
            $fname = $parts[-1]
            $remoteMtime = "$($parts[5]) $($parts[6]) $($parts[7])"
            $dest = Join-Path $localDir $fname
            $needDownload = $false
            if (-not (Test-Path $dest)) {
                $needDownload = $true
            } else {
                $localMtime = (Get-Item $dest).LastWriteTime.ToString("MMM dd HH:mm")
                if ($remoteMtime -ne $localMtime) {
                    $needDownload = $true
                }
            }
            if ($needDownload) {
                $fullPath = "$sdir/$fname"
                scp $using:sshOpts "root@$($using:serverHost):${fullPath}" $dest 2>&1 | Out-Null
                Write-Host "  + $fname (updated)"
            }
        }
    }
    
    # 1) 从 GitHub 拉取远程更新
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 拉取 GitHub 更新..."
    git pull origin main --rebase=false 2>&1 | Out-Null
    
    # 2) 跑 Pipeline
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 执行 Pipeline..."
    & $using:python "$using:scriptDir\kb\main.py" 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host $_ }
    
    # 3) git push
    Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 推送至 GitHub..."
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin main 2>&1 | Out-Null
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 完成"
    } else {
        Write-Host "[$(Get-Date -Format 'HH:mm:ss')] 无变更"
    }
}

$onCreated = Register-ObjectEvent $watcher "Created" -Action $action
$onRenamed = Register-ObjectEvent $watcher "Renamed" -Action $action

Write-Host "[watch] 就绪，等待新笔记..."

try { while ($true) { Start-Sleep -Seconds 5 } }
finally {
    Unregister-Event $onCreated.Id -ErrorAction SilentlyContinue
    Unregister-Event $onRenamed.Id -ErrorAction SilentlyContinue
    $watcher.Dispose()
    Remove-Item $lockFile -ErrorAction SilentlyContinue
}