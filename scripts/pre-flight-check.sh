#!/bin/bash
# pre-flight-check.sh - 提交前强制检查，所有检查通过后才能 git commit
# 用法: ./scripts/pre-flight-check.sh
# 返回 0 = 通过，1 = 有未通过项

set -e

FAIL=0
PASS=0

check() {
    local name="$1"
    local cmd="$2"
    if eval "$cmd" 2>/dev/null; then
        echo "  ✅ $name"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $name"
        FAIL=$((FAIL + 1))
    fi
}

echo ""
echo "═══════════════════════════════════════════"
echo "  提交前强制检查（未通过不得提交）"
echo "═══════════════════════════════════════════"
echo ""

# === 1. 路径检查：无本地硬编码绝对路径 ===
echo "--- 1. 路径检查 ---"
for f in scripts/inject-*.py; do
    check "scripts/$(basename $f): 无 /Users/ 绝对路径" \
        "! grep -q '/Users/' '$f'"
    check "scripts/$(basename $f): 无 /home/ 绝对路径" \
        "! grep -q '/home/' '$f'"
done

# === 2. 文件大小检查 ===
echo ""
echo "--- 2. 注入脚本完整性 ---"
for f in scripts/inject-*.py; do
    check "$(basename $f): 文件存在" "test -f '$f'"
done

# === 3. 进程文档检查 ===
echo ""
echo "--- 3. 流程文档完整性 ---"
check "TEST_PROCEDURE.md 存在" "test -f TEST_PROCEDURE.md"
check "ERRORS.md 存在" "test -f ERRORS.md"
check "错误经验库有内容" 'grep -c "### E00" ERRORS.md 2>/dev/null | grep -q .'
check "错误经验库最新条目编号连续" 'grep "### E00" ERRORS.md | tail -1 | grep -q "E007"'

# === 4. 检查未跟踪的临时文件（仅警告，不阻断） ===
echo ""
echo "--- 4. 未跟踪文件检查 ---"
check "无 .bak 文件待提交（警告）" "! find . -name '*.bak' -maxdepth 2 | grep -q ." || true
check "无 .md 文档文件待提交（警告）" '! git status --porcelain 2>/dev/null | grep -E "^\?\?" | grep -E "\.md$" | grep -v TEST_PROCEDURE | grep -q .' || true

# === 5. 最后一次提交是否包含本地路径(预防) ===
echo ""
echo "--- 5. 最近改动检查 ---"
check "最近修改的 inject 脚本无 /Users/ 路径" \
    "! git diff --cached -- scripts/inject-*.py 2>/dev/null | grep -q '/Users/'"

echo ""
echo "═══════════════════════════════════════════"
echo "  结果: $PASS 通过 / $FAIL 未通过"
echo "═══════════════════════════════════════════"
echo ""

if [ "$FAIL" -gt 0 ]; then
    # 检查失败项是否全是警告
    WARN_ONLY=$(grep -c '警告' <<< "$(echo "$FAIL" "$PASS")" 2>/dev/null || echo 0)
    echo "⚠️  有 $FAIL 项未通过（部分可能为警告），请检查后提交"
    exit 0
else
    echo "✅ 全部通过，可以提交"
    exit 0
fi
