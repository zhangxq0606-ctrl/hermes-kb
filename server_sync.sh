#!/bin/bash
set -e

REPO=/var/www/hermes-kb
LOG=/var/log/hermes-sync.log
cd $REPO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync start" >> $LOG

# 1) detect if there are untracked files (Claude Code wrote something new)
BEFORE=$(git ls-files --others --exclude-standard | wc -l)

# 2) fetch + reset to match GitHub exactly
#    Note: --hard does NOT delete untracked files, so Claude Code writes survive
git fetch origin >>$LOG 2>&1
git reset --hard origin/main >>$LOG 2>&1

# 3) if new files were present, mark for scp sync
AFTER=$(git ls-files --others --exclude-standard | wc -l)
if [ "$BEFORE" -gt 0 ] || [ "$AFTER" -gt 0 ]; then
  touch .last_sync
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] local files present" >> $LOG
fi

# 4) build static website
cd kb/scripts
python3 build_static.py >>$LOG 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync done" >> $LOG
