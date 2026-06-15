# Hermes KB - Inbox Watcher
# Monitors inbox/ for new .md files, auto-runs pipeline + build + git push
# Also triggers full pipeline (Weekly Scan + Compiler) once per week

$scriptDir = "D:\hermes-kb"
$inboxDir = "$scriptDir\kb\inbox"
$python = "C:\Users\qqmin06\python-sdk\python3.13.2\python.exe"
$logFile = "$scriptDir\kb\logs\watch_inbox.log"
$scanStateFile = "$scriptDir\kb\logs\.last_full_scan.txt"

function logMsg($msg) {
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$ts $msg" | Out-File -FilePath $logFile -Encoding utf8 -Append
}

function runPipeline {
    git pull origin main --rebase=false 2>&1 | Out-Null
    & $py "$dir\kb\main.py" 2>&1 | Out-Null
    & $py "$dir\kb\scripts\build_static.py" 2>&1 | Out-Null
    git add -A 2>&1 | Out-Null
    git diff --cached --quiet 2>&1
    if ($LASTEXITCODE -ne 0) {
        git commit -m "auto: sync $(Get-Date -Format 'yyyy-MM-dd HH:mm')" 2>&1 | Out-Null
        git push origin main 2>&1 | Out-Null
    }
    # Record last full scan time
    Get-Date -Format "yyyy-MM-dd" | Out-File $scanStateFile -Encoding utf8
}

# Mutex lock
$lockFile = "$scriptDir\.sync.lock"
if (Test-Path $lockFile) {
    $lockPid = Get-Content $lockFile -ErrorAction SilentlyContinue
    $proc = Get-Process -Id $lockPid -ErrorAction SilentlyContinue
    if ($proc) { logMsg "SKIP: another watcher running (PID:$lockPid)"; exit 0 }
}
$PID | Set-Content $lockFile -ErrorAction SilentlyContinue

# Catch-up on startup
logMsg "START: catching up from GitHub..."
Set-Location $scriptDir
git pull origin main --rebase=false 2>&1 | Out-Null
logMsg "START: catch-up done, watching inbox..."

$py = $python
$dir = $scriptDir

# Filesystem watcher for inbox
$watcher = New-Object System.IO.FileSystemWatcher
$watcher.Path = $inboxDir
$watcher.Filter = "*.md"
$watcher.IncludeSubdirectories = $false
$watcher.EnableRaisingEvents = $true

$global:lastRun = [DateTime]::MinValue
$global:lastWeeklyCheck = (Get-Date).AddDays(-7)  # force first weekly check on startup

# Register inbox event handlers
$action = {
    $now = Get-Date
    if (($now - $global:lastRun).TotalSeconds -lt 60) { return }
    $global:lastRun = $now
    Set-Location $dir
    runPipeline
}

$null = Register-ObjectEvent $watcher "Created" -Action $action
$null = Register-ObjectEvent $watcher "Renamed" -Action $action

logMsg "Ready. Watching inbox + weekly scan check every 30s..."

# Main loop: wait for events AND check weekly scan
try {
    while ($true) {
        Start-Sleep -Seconds 30

        # Weekly scan check: has it been 7+ days?
        $today = Get-Date
        $lastScan = if (Test-Path $scanStateFile) {
            Get-Date (Get-Content $scanStateFile -Raw).Trim()
        } else {
            $today.AddDays(-8)
        }
        if (($today - $lastScan).TotalDays -ge 7) {
            logMsg "WEEKLY: 7+ days since last full scan, triggering pipeline..."
            Set-Location $dir
            runPipeline
            logMsg "WEEKLY: full scan done"
        }
    }
}
finally {
    Remove-Item $lockFile -ErrorAction SilentlyContinue
}
