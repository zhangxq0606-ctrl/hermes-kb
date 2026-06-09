#!/bin/bash
REPO=/var/www/hermes-kb
cd $REPO

echo "============================================"
echo "  TEST C: sync.sh 连续运行 不产生git发散"
echo "============================================"
for i in 1 2 3 4 5 6 7 8; do
  bash /root/sync.sh 2>/dev/null
  DIV=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null)
  echo "  r$i: div=$DIV"
done

echo ""
echo "============================================"
echo "  TEST D: Claude Code写新文件 -> 不丢失"
echo "============================================"
echo "=== test article written by Claude Code ===" > kb/writing/claude_test.md
echo "created claude_test.md"
bash /root/sync.sh 2>/dev/null
CONTENT=$(cat kb/writing/claude_test.md 2>/dev/null || echo LOST)
DIV=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null)
echo "  content: $CONTENT"
echo "  div: $DIV"

for i in 1 2 3 4 5; do
  bash /root/sync.sh 2>/dev/null
  EX=$(test -f kb/writing/claude_test.md && echo OK || echo LOST)
  DIV=$(git rev-list --left-right --count origin/main...HEAD 2>/dev/null)
  echo "  r$i: file=$EX div=$DIV"
done

echo ""
echo "=== FINAL ==="
echo "div: $(git rev-list --left-right --count origin/main...HEAD 2>/dev/null)"
echo "stash: $(git stash list 2>/dev/null | wc -l)"
echo "test file: $(test -f kb/writing/claude_test.md && echo OK || echo LOST)"
