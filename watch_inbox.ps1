# Hermes KB - Inbox Watcher
# Monitors inbox/ for new .md files, auto-runs pipeline + build + git push
# Deleted old tasks: HermesAutoSync (10min), HermesKBAutoPull (10min)

$scriptDir = "D:\hermes-kb"
$inboxDir = "$scriptDir\kb\inbox"
$python = "C:\Users\qqmin06\python-sdk\python3.13.2\python.exe"
$logFile = "$scriptDir\kb\logs\watch_inbox.log"

function logMsg($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

# Mutex lock
$lockFile = "$scriptDir\.sync.lock"
if (Test-Path $lockFile) {
    $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) { logMsg "SKIP: another watcher running (PID:$lockPid)"; exit 0 }
}
$PID | Set-Content $lockFile -ErrorAction SilentlyContinue

# Catch-up on startup: sync anything from overnight
logMsg "START: catching up from GitHub..."
Set-Location $scriptDir
git pull origin main --rebase=false 2>&1 | Out-Null
logMsg "START: catch-up done, watching inbox..."

$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $inboxDir
$watcher.Filter = "*.md"
$watcher.IncludeSubdirectories = $false
$watcher.EnableRaisingEvents = $true

$global:lastRun = [DateTime]::MinValue
$py = $python
$dir = $scriptDir

$action = {
    $now = Get-Date
    if (($now - $global:lastRun).TotalSeconds -lt 60) { return }
    $global:lastRun = $now
    Set-Location $dir
    git pull origin main --rebase=false 2>&1 | Out-Null
    & $py "$dir\kb\main.py" 2>&1 | Out-Null
    & $py "$dir\kb\scripts\build_static.py" 2>&1 | Out-Null
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin main 2>&1 | Out-Null
    }
}

$null = Register-ObjectEvent $watcher "Created" -Action $action
$null = Register-ObjectEvent $watcher "Renamed" -Action $action

try { while ($true) { Start-Sleep -Seconds 30 } }
finally { Remove-Item $lockFile -ErrorAction SilentlyContinue }
