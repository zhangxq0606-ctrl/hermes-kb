# Hermes KB 自动同步脚本 — 定时 pull + push
$env:GIT_SSH_COMMAND = "ssh -o StrictHostKeyChecking=no -i $env:USERPROFILE\.ssh\id_ed25519"
cd D:\hermes-kb

# Pull
git pull --ff-only 2>&1 | Out-File -Append D:\hermes-kb\auto_pull.log

# Check for uncommitted changes, auto commit + push
$status = git status --porcelain
if ($status) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    git add -A 2>&1 | Out-File -Append D:\hermes-kb\auto_pull.log
    git commit -m "auto: sync $timestamp" 2>&1 | Out-File -Append D:\hermes-kb\auto_pull.log
    git push origin main 2>&1 | Out-File -Append D:\hermes-kb\auto_pull.log
}
