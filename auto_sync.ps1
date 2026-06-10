# Hermes KB 自动同步脚本
# 服务器->本地用 scp，本地运行管线后回推到服务器 + GitHub

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

# 互斥锁：防止 auto_sync 和 watch_inbox 并发运行
$lockFile = "$scriptDir\.sync.lock"
if (Test-Path $lockFile) {
    $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 已有同步进程(PID:$lockPid)在运行，跳过"
        exit 0
    }
}
$PID | Set-Content $lockFile -ErrorAction SilentlyContinue

try {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 开始同步..."

    # 0) 从服务器拉取 Claude Code 写的文件（检查文件更新时间）
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 拉取服务器文件..."
    $serverDirs = @('/var/www/hermes-kb/kb/writing', '/var/www/hermes-kb/kb/core/insight', '/var/www/hermes-kb/kb/core/note', '/var/www/hermes-kb/kb/manual/technical')
    $sshKey = "C:\Users\qqmin06\.ssh\trae_deploy_key"
    $sshOpts = "-i $sshKey -o StrictHostKeyChecking=no"
    $serverHost = "116.62.220.41"

    foreach ($sdir in $serverDirs) {
        $localDir = $sdir -replace '/var/www/hermes-kb/', "D:\hermes-kb\"
        $localDir = $localDir -replace '/', '\'
        if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
        $remoteList = ssh $sshOpts root@$serverHost "ls -la $sdir/*.md 2>/dev/null" 2>&1
        foreach ($rf in $remoteList) {
            $rf = ($rf.ToString()).Trim()
            if ($rf -eq '' -or $rf -match '^ssh:|^Warning:|^Pseudo|^#|^total') { continue }
            # 解析 ls -la 输出: -rw-r--r-- 1 root 1234 Jun  9 12:00 filename.md
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
                scp $sshOpts "root@${serverHost}:${fullPath}" $dest 2>&1 | Out-Null
                Write-Host "  + $fname (updated)"
            }
        }
    }

    # 1) 从 GitHub 拉取远程更新
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 拉取 GitHub 更新..."
    git pull origin main --rebase=false 2>&1 | Out-Null

    # 2) 跑 Pipeline（引擎 + 编译器）
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 执行 Pipeline..."
    & python "$scriptDir\kb\main.py" 2>&1 | Select-Object -Last 5

    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline done"

    # 2.5) 重建静态站
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 重建静态站..."
    & python "$scriptDir\kb\scripts\build_static.py" 2>&1 | Select-Object -Last 3

    # 3) git add + commit + push
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin main 2>&1
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pushed to GitHub"
    } else {
        Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] No changes, skip push"
    }

    # 4) 回推静态站到服务器（nginx 纯静态，只需 public/）
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 回推静态站到服务器..."
    scp -r $sshOpts "D:\hermes-kb\public\" "root@${serverHost}:/var/www/hermes-kb/public/" 2>&1 | Out-Null
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 静态站推送完成"

    # 5) 服务器端重载 nginx
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 重载服务器 nginx..."
    ssh $sshOpts root@$serverHost "nginx -s reload" 2>&1 | Out-Null
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 同步完成"
} finally {
    Remove-Item $lockFile -ErrorAction SilentlyContinue
}