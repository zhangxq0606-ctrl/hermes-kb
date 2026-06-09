# Hermes KB 自动同步脚本
# 服务器->本地用 scp，本地->GitHub->服务器用 git

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 开始同步..."

# 0) 从服务器拉取 Claude Code 写的文件
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 拉取服务器文件..."
$serverDirs = @('/var/www/hermes-kb/kb/writing/', '/var/www/hermes-kb/kb/core/insight/', '/var/www/hermes-kb/kb/core/note/', '/var/www/hermes-kb/kb/manual/technical/')
$sshKey = "C:\Users\qqmin06\.ssh\trae_deploy_key"
$sshOpts = "-i $sshKey -o StrictHostKeyChecking=no"
$serverHost = "116.62.220.41"
foreach ($sdir in $serverDirs) {
    $localDir = $sdir -replace '/var/www/hermes-kb/', "D:\hermes-kb\"
    $localDir = $localDir -replace '/', '\'
    if (-not (Test-Path $localDir)) { New-Item -ItemType Directory -Path $localDir -Force | Out-Null }
    $files = ssh $sshOpts root@$serverHost "find $sdir -name '*.md' -newer /var/www/hermes-kb/.last_sync 2>/dev/null" 2>&1
    foreach ($f in $files) {
        $f = $f.Trim()
        if ($f -eq '' -or $f -match '^ssh:|^Warning:') { continue }
        $fname = Split-Path $f -Leaf
        $dest = Join-Path $localDir $fname
        if (-not (Test-Path $dest)) {
            scp $sshOpts "root@${serverHost}:${f}" $dest 2>&1 | Out-Null
            Write-Host "  + $fname"
        }
    }
}
ssh $sshOpts root@$serverHost "touch /var/www/hermes-kb/.last_sync" 2>&1 | Out-Null

# 1) 从 GitHub 拉取远程更新
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 拉取 GitHub 更新..."
git pull origin main --rebase=false 2>&1

# 2) 跑 Pipeline
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 执行 Pipeline..."
& python "$scriptDir\kb\main.py" 2>&1 | ForEach-Object { Write-Host $_ }

if ($LASTEXITCODE -ne 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline failed, skip push"
}
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline done"

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
