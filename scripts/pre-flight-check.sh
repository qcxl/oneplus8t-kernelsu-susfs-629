#!/bin/bash
# pre-flight-check.sh - 提交前强制检查
# 用法: ./scripts/pre-flight-check.sh
# 返回 0 = 通过，1 = 有阻断项未通过

set -e

FAIL_BLOCKING=0
FAIL_WARN=0
PASS=0

check_blocking() {
    local name="$1" cmd="$2"
    if eval "$cmd" 2>/dev/null; then
        echo "  ✅ $name"
        PASS=$((PASS + 1))
    else
        echo "  ❌ $name [阻断]"
        FAIL_BLOCKING=$((FAIL_BLOCKING + 1))
    fi
}

check_warn() {
    local name="$1" cmd="$2"
    if eval "$cmd" 2>/dev/null; then
        echo "  ✅ $name"
        PASS=$((PASS + 1))
    else
        echo "  ⚠️  $name [警告]"
        FAIL_WARN=$((FAIL_WARN + 1))
    fi
}

# Detect latest E00N number dynamically
LATEST_E=$(grep "^### E00" ERRORS.md 2>/dev/null | tail -1 | grep -o 'E00[0-9]' || echo "E000")
echo ""
echo "═══════════════════════════════════════════"
echo "  提交前强制检查（最新错误: $LATEST_E）"
echo "═══════════════════════════════════════════"
echo ""

# === 1. 路径检查：无本地硬编码绝对路径（阻断） ===
echo "--- 1. 路径检查（阻断）---"
for f in scripts/inject-*.py; do
    check_blocking "$(basename $f): 无 /Users/ 绝对路径" "! grep -q '/Users/' '$f'"
    check_blocking "$(basename $f): 无 /home/ 绝对路径" "! grep -q '/home/' '$f'"
done
check_blocking "inject-susfs-dispatch.py: 无 /Users/ 路径" "! grep -q '/Users/' scripts/inject-susfs-dispatch.py"

# === 2. Python 语法检查（阻断） ===
echo ""
echo "--- 2. Python 语法检查（阻断）---"
for f in scripts/inject-*.py; do
    check_blocking "$(basename $f): Python 语法正确" \
        "python3 -c \"import py_compile; py_compile.compile('$f', doraise=True)\""
done

# === 3. 注入脚本完整性 ===
echo ""
echo "--- 3. 注入脚本完整性 ---"
for f in scripts/inject-*.py; do
    check_warn "$(basename $f): 文件存在" "test -f '$f'"
done

# === 4. 修复后复盘检查（阻断） ===
echo ""
echo "--- 4. 修复后复盘检查（阻断）---"
INJECT_CHANGED=$(git diff --cached --name-only -- scripts/inject-*.py 2>/dev/null || true)
ERRORS_CHANGED=$(git diff --cached --name-only -- ERRORS.md 2>/dev/null || true)
if [ -n "$INJECT_CHANGED" ] && [ -z "$ERRORS_CHANGED" ]; then
    check_blocking "注入脚本已修改，但 ERRORS.md 未更新！必须先写错误经验" \
        "false"
else
    echo "  ✅ 注入脚本修改 + ERRORS.md 已同步"
fi

# === 5a. 流程文档完整性 ===
echo ""
echo "--- 5a. 流程文档完整性（阻断）---"
check_blocking "TEST_PROCEDURE.md 存在" "test -f TEST_PROCEDURE.md"
check_blocking "FLASH_PROCEDURE.md 存在" "test -f FLASH_PROCEDURE.md"
check_blocking "ERRORS.md 存在" "test -f ERRORS.md"
check_blocking "pre-flight-check.sh 存在" "test -f scripts/pre-flight-check.sh"
check_blocking "错误经验库有内容" 'grep -c "### E00" ERRORS.md 2>/dev/null | grep -q .'
# Dynamic check: latest E00N entry has all 4 required fields
check_blocking "最新条目有【现象】字段" "grep -A8 '### $LATEST_E' ERRORS.md | grep -q '现象'"
check_blocking "最新条目有【根因】字段" "grep -A8 '### $LATEST_E' ERRORS.md | grep -q '根因'"
check_blocking "最新条目有【教训】字段" "grep -A8 '### $LATEST_E' ERRORS.md | grep -q '教训'"
check_blocking "最新条目有【检查清单锚点】字段" "grep -A8 '### $LATEST_E' ERRORS.md | grep -q '检查清单锚点'"

# === 5b. 提交信息检查（阻断） ===
echo ""
echo "--- 5b. 提交信息检查（阻断）---"
if [ -n "$INJECT_CHANGED" ] && [ -n "$ERRORS_CHANGED" ]; then
    # Check that the commit message references the latest E00N
    COMMIT_MSG=$(git log --format=%s -1 2>/dev/null || echo "")
    if echo "$COMMIT_MSG" | grep -q "$LATEST_E"; then
        echo "  ✅ commit message 引用了 $LATEST_E"
    else
        check_blocking "commit message 必须引用 $LATEST_E（注入脚本变更 + ERRORS.md 更新）" "false"
    fi
else
    echo "  (未同时修改注入脚本和 ERRORS.md，跳过提交信息检查)"
fi

# === 5c. 未跟踪文件检查（警告） ===
check_warn "无 .bak 文件待提交" "! find . -name '*.bak' -maxdepth 2 | grep -q ."
check_warn "无 .md 文档文件待提交" '! git status --porcelain 2>/dev/null | grep -E "^\?\?" | grep -E "\.md$" | grep -v TEST_PROCEDURE | grep -q .'

# === 6. 最近改动检查（阻断） ===
echo ""
echo "--- 6. 最近改动检查（阻断）---"
check_blocking "staged inject 脚本无 /Users/ 路径" \
    "! git diff --cached -- scripts/inject-*.py 2>/dev/null | grep -q '/Users/'"

# === 7. 常量引用完整性检查（阻断） ===
echo ""
echo "--- 7. 常量引用完整性检查（阻断）---"
# Extract all CMD_SUSFS_* constants referenced in dispatch template
# and verify each has a #define in susfs_def.h
SUSFS_DEF_H="include/linux/susfs_def.h"
if [ -f "$SUSFS_DEF_H" ]; then
  UNDEFINED=0
  for cmd in $(grep -o 'CMD_SUSFS_[A-Z_]*' scripts/inject-susfs-dispatch.py 2>/dev/null | sort -u); do
    if ! grep -q "#define $cmd " "$SUSFS_DEF_H" 2>/dev/null; then
      echo "  ❌ $cmd 在 $SUSFS_DEF_H 中未定义 [阻断]"
      UNDEFINED=$((UNDEFINED + 1))
    fi
  done
  if [ "$UNDEFINED" -gt 0 ]; then
    FAIL_BLOCKING=$((FAIL_BLOCKING + UNDEFINED))
  else
    echo "  ✅ dispatch 模板引用的所有 CMD 常量已在 susfs_def.h 中定义"
    PASS=$((PASS + 1))
  fi
else
  echo "  ⚠️  $SUSFS_DEF_H 不存在，跳过常量检查"
fi

# === 8. Kconfig 一致性检查（警告） ===
echo ""
echo "--- 8. Kconfig 一致性检查（警告）---"
for cfg in $(grep '^CONFIG_KSU_SUSFS_' kernel-patches/ksu.config 2>/dev/null | grep '=y' | cut -d= -f1); do
    short=$(echo "$cfg" | sed 's/CONFIG_//')
    check_warn "$cfg: 在 GHA workflow Kconfig 中注册" \
        "grep -q '$short' .github/workflows/build-ksu-debug.yml 2>/dev/null"
done

echo ""
echo "═══════════════════════════════════════════"
echo "  结果: $PASS 通过 / $FAIL_BLOCKING 阻断 / $FAIL_WARN 警告"
echo "═══════════════════════════════════════════"
echo ""

if [ "$FAIL_BLOCKING" -gt 0 ]; then
    echo "❌ 有 $FAIL_BLOCKING 项阻断未通过，强制修复后再提交"
    exit 1
elif [ "$FAIL_WARN" -gt 0 ]; then
    echo "⚠️  有 $FAIL_WARN 项警告，建议修复"
    exit 0
else
    echo "✅ 全部通过，可以提交"
    exit 0
fi
