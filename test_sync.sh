#!/bin/bash
REPO=/var/www/hermes-kb
cd $REPO
git reset --hard origin/main
git stash clear
rm -f kb/writing/test_*
echo '.last_sync' >> .gitignore 2>/dev/null || true
rm -f .last_sync; touch .last_sync

echo "=== 测试C: 连续8次空跑 ==="
for i in 1 2 3 4 5 6 7 8; do
  bash /root/sync.sh 2>/dev/null
  DIV=$(git rev-list --left-right --count origin/main...HEAD)
  STASH=$(git stash list 2>/dev/null | wc -l)
  echo "  r$i: div=$DIV stash=$STASH"
done

echo ""
echo "=== 测试D: Claude Code写新文件 ==="
echo 'hello_world' > kb/writing/test_new_file.md
echo "  created"
bash /root/sync.sh 2>/dev/null
CONTENT=$(cat kb/writing/test_new_file.md 2>/dev/null || echo LOST)
DIV=$(git rev-list --left-right --count origin/main...HEAD)
echo "  content: $CONTENT"
echo "  div: $DIV"

echo ""
echo "=== 测试D2: 再跑5次不丢 ==="
for i in 1 2 3 4 5; do
  bash /root/sync.sh 2>/dev/null
  EX=$(test -f kb/writing/test_new_file.md && echo OK || echo LOST)
  DIV=$(git rev-list --left-right --count origin/main...HEAD)
  echo "  r$i: file=$EX div=$DIV"
done

echo ""
echo "=== 测试D3: 修改文件内容 ==="
echo 'updated_v2' > kb/writing/test_new_file.md
bash /root/sync.sh 2>/dev/null
CONTENT=$(cat kb/writing/test_new_file.md 2>/dev/null || echo LOST)
echo "  content after modify: $CONTENT"

echo ""
echo "=== 最终 ==="
echo "div: $(git rev-list --left-right --count origin/main...HEAD)"
echo "stash: $(git stash list 2>/dev/null | wc -l)"
echo "status: $(git status --short | head -3)"

# cleanup
git reset --hard origin/main
git stash clear
rm -f kb/writing/test_new_file.md .last_sync
touch .last_sync
echo "cleaned"
