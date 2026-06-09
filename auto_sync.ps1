# Hermes KB 自动同步脚本
# 用途：跑完 Pipeline 后自动 push 到 GitHub
# 服务器会自动拉取并 build，无需额外操作

$ErrorActionPreference = "Continue"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 开始同步..."

# 1) 跑 Pipeline
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 执行 Pipeline..."
$result = python "$scriptDir\kb\main.py" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline 失败，跳过 push"
    exit 1
}
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Pipeline 完成"

# 2) git add + commit + push
Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 提交到 Git..."
git add -A 2>&1 | Out-Null
git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
git push origin main 2>&1

if ($LASTEXITCODE -eq 0) {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 推送成功！服务器将在 1 分钟内自动更新。"
} else {
    Write-Host "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 推送失败，请检查网络或 Git 配置。"
}
