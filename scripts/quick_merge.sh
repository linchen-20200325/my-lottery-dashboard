#!/usr/bin/env bash
# scripts/quick_merge.sh — 跳 PR 直推主分支（限 CLAUDE.md §4「跳 PR 直推例外」白名單）.
#
# 用法：
#   ./scripts/quick_merge.sh "commit message"
#
# 流程：
#   1. 偵測主分支（main 或 master）
#   2. 確認目前不在主分支 + working tree 乾淨
#   3. 切主分支、`git pull --ff-only`
#   4. `git merge --squash` 來源分支 → `git commit -m "$MSG"`
#   5. `git push origin <主分支>`
#   6. 刪除來源分支（本地 + 遠端）
#
# 限定白名單：STATE.md / CLAUDE.md / 註解 / typo / 版本 bump / 純文件改動。
# 任何 .py 邏輯變動請走標準 PR 流程。

set -euo pipefail

if [ $# -lt 1 ] || [ -z "${1:-}" ]; then
    echo "❌ 用法：$0 \"commit message\"" >&2
    exit 1
fi

MSG="$1"

# --- 偵測主分支（main / master）---------------------------------------------
DEFAULT_BRANCH=""
if git symbolic-ref --quiet refs/remotes/origin/HEAD >/dev/null 2>&1; then
    DEFAULT_BRANCH="$(git symbolic-ref --short refs/remotes/origin/HEAD | sed 's|^origin/||')"
fi
if [ -z "$DEFAULT_BRANCH" ]; then
    if git show-ref --verify --quiet refs/remotes/origin/main; then
        DEFAULT_BRANCH="main"
    elif git show-ref --verify --quiet refs/remotes/origin/master; then
        DEFAULT_BRANCH="master"
    else
        echo "❌ 偵測不到 origin/main 或 origin/master" >&2
        exit 1
    fi
fi

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"

# --- 前置檢查 ----------------------------------------------------------------
if [ "$CURRENT_BRANCH" = "$DEFAULT_BRANCH" ]; then
    echo "❌ 已在 $DEFAULT_BRANCH 分支上 — 本腳本用於將*其他分支*合併到 $DEFAULT_BRANCH" >&2
    exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
    echo "❌ Working tree 不乾淨，請先 commit 或 stash" >&2
    git status --short >&2
    exit 1
fi

echo "📦 Source : $CURRENT_BRANCH"
echo "🎯 Target : $DEFAULT_BRANCH"
echo "💬 Message: $MSG"
echo ""

# --- Squash merge → push -----------------------------------------------------
git checkout "$DEFAULT_BRANCH"
git pull --ff-only origin "$DEFAULT_BRANCH"
git merge --squash "$CURRENT_BRANCH"
git commit -m "$MSG"
git push origin "$DEFAULT_BRANCH"

# --- 清分支 ------------------------------------------------------------------
git branch -D "$CURRENT_BRANCH"
if ! git push origin --delete "$CURRENT_BRANCH" 2>/dev/null; then
    echo "⚠️  遠端 $CURRENT_BRANCH 已不存在或無刪除權限（不致命）"
fi

echo ""
echo "✅ 已 squash-merge $CURRENT_BRANCH → $DEFAULT_BRANCH 並清除分支"
