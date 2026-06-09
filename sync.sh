#!/bin/bash
set -e

REPO=/var/www/hermes-kb
LOG=/var/log/hermes-sync.log
cd $REPO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync start" >> $LOG

# 1) stage any local changes
git add -A 2>>$LOG

# 2) if there are staged changes, commit them (local only)
if ! git diff --cached --quiet; then
  git commit -m "auto: server sync $(date '+%Y-%m-%d %H:%M')" >>$LOG 2>&1
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] committed local changes" >>$LOG
fi

# 3) pull latest
git pull origin main >>$LOG 2>&1

# 4) build static
cd kb/scripts
python3 build_static.py >>$LOG 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync done" >>$LOG
