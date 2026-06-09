#!/bin/bash
set -e

REPO=/var/www/hermes-kb
LOG=/var/log/hermes-sync.log
cd $REPO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync start" >> $LOG

# 1) stash any local changes (Claude Code writes)
git add -A 2>>$LOG
if ! git diff --cached --quiet; then
  git stash 2>>$LOG
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] stashed local changes" >> $LOG
  touch .last_sync
fi

# 2) fetch + hard reset to match GitHub exactly
git fetch origin 2>>$LOG
git reset --hard origin/main >>$LOG 2>&1

# 3) restore local changes on top
if git stash list 2>/dev/null | grep -q .; then
  git stash pop 2>>$LOG || echo "[$(date '+%Y-%m-%d %H:%M:%S')] stash pop conflict, files preserved" >> $LOG
fi

# 4) build static website
cd kb/scripts
python3 build_static.py >>$LOG 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync done" >> $LOG
