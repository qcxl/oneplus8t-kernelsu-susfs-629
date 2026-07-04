#!/usr/bin/env python3
"""
inject-remove-avtab.py — 移植 dev 分支的 remove_avtab_node + is_redundant_avtab_node 到 legacy

功能：
  1. 在 legacy sepolicy.c 中添加 is_redundant_avtab_node() 函数
  2. 在 legacy sepolicy.c 中添加 remove_avtab_node() 函数
  3. 在 add_rule_raw() 末尾插入"冗余节点自动清理"调用

技术细节：
  - dev 的 remove_avtab_node 通过 avtab_alloc + avtab_destroy 间接释放节点
  - 该函数纯自包含，无外部依赖（除了 avtab.h 已被 sepolicy.c 包含）
  - 4.19 内核的 avtab.h 接口与 dev 完全一致（avtab_alloc/avtab_destroy/avtab_node 都存在）

风险点：
  - 极低。函数纯本地操作，不影响其他逻辑
  - 唯一行为变化：add_rule_raw 在 invert 模式下若结果为 0/~0U 会自动删除该节点
    （这是优化，不是 bug 修复，对功能无影响）

参考：dev 分支 kernel/selinux/sepolicy.c L150-L215
"""

import sys
import os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_REMOVE_AVTAB_INJECTED */"

# is_redundant_avtab_node + remove_avtab_node 函数体（来自 dev 分支）
# 注：4.19 的 ARRAY_SIZE 宏可用，avtab_alloc/avtab_destroy 接口一致
AVTAB_FUNCTIONS = r"""
%s

static bool is_redundant_avtab_node(struct avtab_node *node)
{
    if (node->key.specified & AVTAB_XPERMS)
        return node->datum.u.xperms == NULL;
    if (!(node->key.specified & AVTAB_AV))
        return false;
    if (node->key.specified & AVTAB_AUDITDENY)
        return node->datum.u.data == ~0U;
    return node->datum.u.data == 0U;
}

static bool remove_avtab_node(struct policydb *db, struct avtab_node *node)
{
    int i;
    int ret;
    int shrink_size = sizeof(struct avtab_key) + sizeof(struct avtab_datum);
    struct avtab removed = {};
    struct avtab_node *n;
    struct avtab_node *prev;

    ret = avtab_alloc(&removed, 1);
    if (ret < 0)
        return false;

    for (i = 0; i < db->te_avtab.nslot; i++) {
        prev = NULL;
        for (n = (struct avtab_node *)flex_array_get(db->te_avtab.htable, i); n; prev = n, n = n->next) {
            if (n != node)
                continue;

            if (prev)
                prev->next = n->next;
            else
                db->te_avtab.htable[i] = n->next;

            if (db->te_avtab.nel > 0)
                db->te_avtab.nel--;

            if ((n->key.specified & AVTAB_XPERMS) && n->datum.u.xperms) {
                shrink_size += sizeof(u8) + sizeof(u8) + sizeof(u32) * ARRAY_SIZE(n->datum.u.xperms->perms.p);
            }
            n->next = NULL;
            removed.htable[0] = n;
            removed.nel = 1;
            avtab_destroy(&removed);
            if (db->len >= shrink_size)
                db->len -= shrink_size;
            return true;
        }
    }

    avtab_destroy(&removed);
    return false;
}
""".strip() % SCRIPT_MARK

# 在 add_rule_raw 末尾插入"冗余清理"调用
# legacy 的 add_rule_raw 末尾结构：
#   } else {
#       ...
#       node->datum.u.data = ~0U;
#   }
# }  <- 这里是函数结束
# 插入点：在最后的 } 之前
ADD_RULE_RAW_HOOK = r"""
%s
        if (is_redundant_avtab_node(node))
            remove_avtab_node(db, node);
""".strip() % SCRIPT_MARK


def main():
    sepolicy_c = os.path.join(KSU, "selinux/sepolicy.c")
    if not os.path.exists(sepolicy_c):
        print(f"ERROR: {sepolicy_c} not found")
        sys.exit(1)

    with open(sepolicy_c) as f:
        content = f.read()

    if SCRIPT_MARK in content:
        print("SKIP: sepolicy.c already injected")
        return

    # Step 1: 在 add_rule_raw 函数定义之前插入两个新函数
    # 锚点：legacy 中 "static void add_rule_raw" 的前一行
    # 用 "static bool add_rule(" (旧版的前向声明) 作为锚点更稳定
    anchor_decl = "static bool add_rule(struct policydb *db,"
    if anchor_decl not in content:
        print("ERROR: anchor 'static bool add_rule(struct policydb *db,' not found")
        sys.exit(1)

    # 在 add_rule 前向声明之前插入新函数
    content = content.replace(
        anchor_decl,
        AVTAB_FUNCTIONS + "\n\n" + anchor_decl,
        1
    )
    print("OK: inserted is_redundant_avtab_node + remove_avtab_node")

    # Step 2: 在 add_rule_raw 末尾的 invert 分支插入冗余清理调用
    # 锚点（legacy 的 add_rule_raw 末尾精确结构）：
    #   } else {
    #       if (perm)
    #           node->datum.u.data |= 1U << (perm->value - 1);
    #       else
    #           node->datum.u.data = ~0U;
    #   }
    # }
    anchor_tail = """        } else {
            if (perm)
                node->datum.u.data |= 1U << (perm->value - 1);
            else
                node->datum.u.data = ~0U;
        }
    }
}"""

    inject_tail = """        } else {
            if (perm)
                node->datum.u.data |= 1U << (perm->value - 1);
            else
                node->datum.u.data = ~0U;
        }
%s
    }
}""" % ADD_RULE_RAW_HOOK

    if anchor_tail in content:
        content = content.replace(anchor_tail, inject_tail, 1)
        print("OK: inserted redundancy cleanup call in add_rule_raw")
    else:
        print("WARN: add_rule_raw tail anchor not found exactly, skipping cleanup call")
        print("      (functions still injected, manual integration needed for the call site)")

    with open(sepolicy_c, 'w') as f:
        f.write(content)

    print("RESULT: injection complete")


if __name__ == '__main__':
    main()
