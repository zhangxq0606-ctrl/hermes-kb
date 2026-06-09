#!/bin/bash
set -e

REPO=/var/www/hermes-kb
LOG=/var/log/hermes-sync.log
cd $REPO

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync start" >> $LOG

# fetch + reset to match GitHub exactly
# (untracked files like Claude Code writes survive --hard)
git fetch origin >>$LOG 2>&1
git reset --hard origin/main >>$LOG 2>&1

# build static website
cd kb/scripts
python3 build_static.py >>$LOG 2>&1

echo "[$(date '+%Y-%m-%d %H:%M:%S')] sync done" >> $LOG
