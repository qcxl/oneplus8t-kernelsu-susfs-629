#!/usr/bin/env python3
"""
inject-initrc.py — 移植 init.rc 模块 RC 注入支持（dev d3e454f → legacy）

在 init 读取 /system/etc/init/hw/init.rc 时，EOF 后追加：
  1. 内置 KERNEL_SU_RC（已有）
  2. 模块自定义 RC 来自 /metadata[/watchdog]/ksu/modules.rc（新增）

可移植的改动：
  1. module_rc 路径常量 + 全局变量
  2. open_module_rc() / load_module_rc_once() / free_module_rc()
  3. read_proxy/read_iter_proxy 增强（追加模块 RC 后释放缓冲区）
  4. ksu_apply_init_rc_proxy 中调用 load_module_rc_once()
  5. fstat handler 报告合并后的大小（static + module）
  6. init.c 添加 ksu_no_custom_rc module_param

所有 API（filp_open, kernel_read, kvmalloc, copy_to_user, copy_to_iter）
在 4.19 均可用。load_module_rc_once 使用 ksu_cred override creds。
/metadata 不存在时静默跳过，不影响现有功能。

参考：dev 分支 kernel/runtime/ksud_integration.c（commit d3e454f）
"""

import sys
import os
import re

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_INITRC_MODULE_INJECTED */"


def inject_file(path, content, desc):
    """Helper: write content to file only if changed."""
    if os.path.exists(path):
        with open(path) as f:
            old = f.read()
        if old == content:
            print(f"SKIP: {desc} — no change")
            return True
    with open(path, 'w') as f:
        f.write(content)
    print(f"OK: {desc}")
    return True


def main():
    init_c = os.path.join(KSU, "core/init.c")
    ksud_c = os.path.join(KSU, "runtime/ksud_integration.c")

    # ============ CHECK FILES EXIST ============
    for p, name in [(init_c, "core/init.c"), (ksud_c, "runtime/ksud_integration.c")]:
        if not os.path.exists(p):
            print(f"ERROR: {name} not found at {p}")
            sys.exit(1)

    with open(init_c) as f:
        init_content = f.read()
    with open(ksud_c) as f:
        ksud_content = f.read()

    if SCRIPT_MARK in ksud_content:
        print("SKIP: initrc module injection already applied")
        return

    # ============ PART 1: init.c — ksu_no_custom_rc ============
    anchor = "bool ksu_late_loaded;"
    if anchor not in init_content:
        print("ERROR: init.c: cannot find 'bool ksu_late_loaded;'")
        sys.exit(1)

    no_custom_rc_block = """bool ksu_late_loaded;
bool ksu_no_custom_rc = false;
module_param_named(norc, ksu_no_custom_rc, bool, 0);"""
    init_content = init_content.replace(anchor, no_custom_rc_block, 1)
    print("OK: init.c — added ksu_no_custom_rc module_param")

    # ============ PART 2: ksud_integration.c — includes ============
    # Add <linux/mm.h> and <linux/uio.h> if not present
    for inc_line, inc_after in [
        ('#include <linux/mm.h>', '#include <linux/printk.h>'),
        ('#include <linux/uio.h>', '#include <linux/printk.h>'),
    ]:
        if inc_line not in ksud_content:
            ksud_content = ksud_content.replace(
                inc_after, f'{inc_after}\n{inc_line}', 1
            )
            print(f"OK: ksud_integration.c — added {inc_line}")
        else:
            print(f"SKIP: ksud_integration.c — {inc_line} already present")

    # Add extern decls for ksu_cred, ksu_no_custom_rc after the includes
    ext_decls = """
/* KSU_INITRC_MODULE_INJECTED */
extern struct cred *ksu_cred;
extern bool ksu_no_custom_rc;
"""
    # Find the last include line (with "ksu.h" or similar) and inject after
    inc_anchor = re.search(
        r'#include "[^"]*ksu[^"]*"[^\]n]*\n',
        ksud_content
    )
    if inc_anchor:
        end = inc_anchor.end()
        ksud_content = ksud_content[:end] + ext_decls + ksud_content[end:]
        print("OK: ksud_integration.c — added extern decls")
    else:
        print("ERROR: ksud_integration.c: cannot find ksu include anchor")
        sys.exit(1)

    # ============ PART 3: module RC defines + globals ============
    # Inject after `const size_t ksu_rc_len = sizeof(KERNEL_SU_RC) - 1;`
    rc_len_anchor = "const size_t ksu_rc_len = sizeof(KERNEL_SU_RC) - 1;"
    if rc_len_anchor not in ksud_content:
        print("ERROR: ksud_integration.c: cannot find ksu_rc_len anchor")
        sys.exit(1)

    module_rc_globals = """
#define MODULE_RC_PATH_WATCHDOG "/metadata/watchdog/ksu/modules.rc"
#define MODULE_RC_PATH_DEFAULT "/metadata/ksu/modules.rc"
static char *module_rc_buf;
static size_t module_rc_len;
static ssize_t module_rc_pos;

static struct file *open_module_rc(const char **chosen_path)
{
	struct file *f = filp_open(MODULE_RC_PATH_WATCHDOG, O_RDONLY, 0);
	if (!IS_ERR(f)) {
		*chosen_path = MODULE_RC_PATH_WATCHDOG;
		return f;
	}
	f = filp_open(MODULE_RC_PATH_DEFAULT, O_RDONLY, 0);
	if (!IS_ERR(f)) {
		*chosen_path = MODULE_RC_PATH_DEFAULT;
		return f;
	}
	*chosen_path = MODULE_RC_PATH_DEFAULT;
	return f;
}

static void load_module_rc_once(void)
{
	static bool loaded = false;
	struct file *f;
	const char *path = NULL;
	loff_t pos = 0;
	ssize_t r;
	size_t fsize;
	const struct cred *old_cred;

	if (ksu_rc_pos || module_rc_buf)
		return;
	if (loaded)
		return;
	loaded = true;
	if (ksu_no_custom_rc) {
		pr_info("module rc: custom rc is disabled\\n");
		return;
	}

	old_cred = override_creds(ksu_cred);

	f = open_module_rc(&path);
	if (IS_ERR(f)) {
		pr_info("module rc: open %s failed: %ld\\n", path,
			PTR_ERR(f));
		goto out_revert_creds;
	}

	if (!S_ISREG(file_inode(f)->i_mode)) {
		pr_warn("module rc: %s is not a regular file\\n", path);
		goto out_close_file;
	}

	fsize = i_size_read(file_inode(f));
	if (fsize == 0) {
		pr_warn("module rc: skip empty module rc\\n");
		goto out_close_file;
	}

	module_rc_buf = kvmalloc(fsize, GFP_KERNEL);
	if (!module_rc_buf) {
		pr_err("module rc: alloc %zu failed\\n", fsize);
		goto out_close_file;
	}

	r = kernel_read(f, module_rc_buf, fsize, &pos);
	if (r <= 0) {
		pr_err("module rc: read failed: %zd\\n", r);
		kvfree(module_rc_buf);
		module_rc_buf = NULL;
		goto out_close_file;
	}

	module_rc_len = r;
	pr_info("module rc: loaded %zu bytes from %s\\n", module_rc_len,
		path);

out_close_file:
	filp_close(f, NULL);
out_revert_creds:
	revert_creds(old_cred);
}

static void free_module_rc(void)
{
	kvfree(module_rc_buf);
	module_rc_buf = NULL;
	module_rc_len = 0;
	module_rc_pos = 0;
}
"""
    ksud_content = ksud_content.replace(
        rc_len_anchor,
        rc_len_anchor + module_rc_globals,
        1,
    )
    print("OK: ksud_integration.c — added module RC globals + load functions")

    # ============ PART 4: Modify read_proxy ============
    # 4a: Add early module RC goto check (after first goto append_ksu_rc)
    orig_goto = (
        'if (ksu_rc_pos && ksu_rc_pos < ksu_rc_len)\n'
        '\t\tgoto append_ksu_rc;\n'
        '\n'
        '\tret = orig_read(file, buf, count, pos);\n'
    )
    mod_goto = (
        'if (ksu_rc_pos && ksu_rc_pos < ksu_rc_len)\n'
        '\t\tgoto append_ksu_rc;\n'
        '\tif (ksu_rc_pos >= ksu_rc_len && module_rc_pos < module_rc_len)\n'
        '\t\tgoto append_module_rc;\n'
        '\n'
        '\tret = orig_read(file, buf, count, pos);\n'
    )
    if orig_goto not in ksud_content:
        # try tab-only variant
        orig_goto_tab = orig_goto.replace('    ', '\t')
        mod_goto_tab = mod_goto.replace('    ', '\t')
        if orig_goto_tab in ksud_content:
            ksud_content = ksud_content.replace(orig_goto_tab, mod_goto_tab, 1)
            print("OK: read_proxy — added module RC early goto (tab)")
        else:
            print("WARNING: read_proxy — module RC early goto anchor not found, skipping")
    else:
        ksud_content = ksud_content.replace(orig_goto, mod_goto, 1)
        print("OK: read_proxy — added module RC early goto")

    # 4b: Modify orig_read return check — remove || ksu_rc_pos >= ksu_rc_len
    old_return = (
        '\tif (ret != 0 || ksu_rc_pos >= ksu_rc_len) {\n'
        '\t\treturn ret;\n'
        '\t} else {\n'
        '\t\tpr_info("read_proxy: orig read finished, start append rc\\n");\n'
        '\t}\n'
    )
    new_return = (
        '\tif (ret != 0) {\n'
        '\t\treturn ret;\n'
        '\t}\n'
        '\tif (ksu_rc_pos >= ksu_rc_len && module_rc_pos >= module_rc_len) {\n'
        '\t\treturn ret;\n'
        '\t}\n'
        '\tpr_info("read_proxy: orig read finished, start append rc\\n");\n'
    )
    if old_return not in ksud_content:
        # try tab variants
        old_return_tab = old_return.replace('    ', '\t')
        new_return_tab = new_return.replace('    ', '\t')
        if old_return_tab in ksud_content:
            ksud_content = ksud_content.replace(old_return_tab, new_return_tab, 1)
            print("OK: read_proxy — modified orig_read return check (tab)")
        else:
            print("WARNING: read_proxy — return check anchor not found, skipping")
    else:
        ksud_content = ksud_content.replace(old_return, new_return, 1)
        print("OK: read_proxy — modified orig_read return check")

    # 4c: Add append_module_rc label block before `return ret;` in read_proxy
    # The read_proxy function ends with:
    #     }
    #     return ret;
    # }
    # We inject before the `return ret;` at the function's end.
    # Find the closing sequence: `\t}\n\treturn ret;\n}`
    # But we need to distinguish from read_iter_proxy which has similar ending.
    # Use the context: read_proxy is the FIRST function with this ending pattern.
    # Inject the module RC block inside read_proxy (between } and return ret;)

    # Actually, looking at the structure more carefully:
    # The append_ksu_rc block ends with:
    #     }
    #     return ret;
    # }
    # We need to add append_module_rc AFTER the append_ksu_rc block
    # and BEFORE the return ret;

    # Find: close brace of append_ksu_rc if block + indent + return ret;
    # In the proxy functions, the append_ksu_rc: block is followed by
    # the final return ret;
    # I'll inject append_module_rc: right before the final return ret;

    # Since both read_proxy and read_iter_proxy have this pattern, use the
    # unique anchor from the append_ksu_rc block's behavior.

    # In read_proxy, after the append_ksu_rc block, the function falls through to return ret;
    # The specific pattern is: the closing `\t}` of an else/if block followed by `\treturn ret;\n`
    # For read_proxy (first such function), inject before the first `\treturn ret;`
    # that comes after the append_ksu_rc: label.

    # More robust: find the LAST line of append_ksu_rc block in read_proxy
    # by finding the specific unique comment or the seq of lines just before
    # the final return.

    # Let me find the read_proxy function boundary and inject right before
    # its `return ret;`. The read_proxy function is the FIRST function in
    # the file that has:
    #     ksu_rc_pos += append_count;
    #     if (ksu_rc_pos == ksu_rc_len) {
    #         pr_info("read_proxy: append done\\n");
    #     }
    #     ret += append_count;
    #     }
    #     return ret;
    # }

    # read_proxy ends with (legacy ksud_integration.c):
    # \t\t\tpr_info("read_proxy: append done\n");
    # \t\t}
    # \t\tret += append_count;
    # \t}
    #                    ← blank line
    # \treturn ret;
    # }
    read_proxy_end = (
        '\t\t\tpr_info("read_proxy: append done\\n");\n'
        '\t\t}\n'
        '\t\tret += append_count;\n'
        '\t}\n'
        '\n'
        '\treturn ret;\n'
        '}'
    )
    read_proxy_rep = (
        '\t\t\tpr_info("read_proxy: append done\\n");\n'
        '\t\t}\n'
        '\t\tret += append_count;\n'
        '\t}\n'
        '\n'
        'append_module_rc:\n'
        '\tif (module_rc_pos < module_rc_len && (size_t)ret < count) {\n'
        '\t\tsize_t append_count = module_rc_len - module_rc_pos;\n'
        '\t\tif (append_count > count - ret)\n'
        '\t\t\tappend_count = count - ret;\n'
        '\t\tif (copy_to_user(buf + ret, module_rc_buf + module_rc_pos,\n'
        '\t\t\t    append_count)) {\n'
        '\t\t\tpr_info("read_proxy: module append error, tot %zd\\n",\n'
        '\t\t\t\tmodule_rc_pos);\n'
        '\t\t\treturn ret;\n'
        '\t\t}\n'
        '\t\tpr_info("read_proxy: append module %zu\\n", append_count);\n'
        '\t\tmodule_rc_pos += append_count;\n'
        '\t\tret += append_count;\n'
        '\t\tif (module_rc_pos == (ssize_t)module_rc_len) {\n'
        '\t\t\tpr_info("read_proxy: module append done\\n");\n'
        '\t\t\tfree_module_rc();\n'
        '\t\t}\n'
        '\t}\n'
        '\n'
        '\treturn ret;\n'
        '}'
    )
    if read_proxy_end in ksud_content:
        ksud_content = ksud_content.replace(read_proxy_end, read_proxy_rep, 1)
        print("OK: read_proxy — added append_module_rc")
    else:
        # tab after injection might differ; use flexible anchor: last \t}\n\n\treturn ret;\n}
        import re as _re
        rp_flex = _re.search(r'\t\}\n\n\treturn ret;\n\}', ksud_content)
        if rp_flex:
            ksud_content = ksud_content[:rp_flex.start()] + (
                '\t}\n'
                '\n'
                'append_module_rc:\n'
                '\tif (module_rc_pos < module_rc_len && (size_t)ret < count) {\n'
                '\t\tsize_t append_count = module_rc_len - module_rc_pos;\n'
                '\t\tif (append_count > count - ret)\n'
                '\t\t\tappend_count = count - ret;\n'
                '\t\tif (copy_to_user(buf + ret, module_rc_buf + module_rc_pos,\n'
                '\t\t\t    append_count)) {\n'
                '\t\t\tpr_info("read_proxy: module append error, tot %zd\\n",\n'
                '\t\t\t\tmodule_rc_pos);\n'
                '\t\t\treturn ret;\n'
                '\t\t}\n'
                '\t\tpr_info("read_proxy: append module %zu\\n", append_count);\n'
                '\t\tmodule_rc_pos += append_count;\n'
                '\t\tret += append_count;\n'
                '\t\tif (module_rc_pos == (ssize_t)module_rc_len) {\n'
                '\t\t\tpr_info("read_proxy: module append done\\n");\n'
                '\t\t\tfree_module_rc();\n'
                '\t\t}\n'
                '\t}\n'
                '\n'
            ) + ksud_content[rp_flex.start():]
            print("OK: read_proxy — added append_module_rc (flexible)")
        else:
            print("WARNING: read_proxy — end anchor not found, skipping")

    # ============ PART 5: Modify read_iter_proxy similarly ============
    # 5a: Add early module RC goto
    rip_goto = (
        'if (ksu_rc_pos && ksu_rc_pos < ksu_rc_len)\n'
        '\t\tgoto append_ksu_rc;\n'
        '\n'
        '\tret = orig_read_iter(iocb, to);\n'
    )
    rip_goto_mod = (
        'if (ksu_rc_pos && ksu_rc_pos < ksu_rc_len)\n'
        '\t\tgoto append_ksu_rc;\n'
        '\tif (ksu_rc_pos >= ksu_rc_len && module_rc_pos < module_rc_len)\n'
        '\t\tgoto append_module_rc;\n'
        '\n'
        '\tret = orig_read_iter(iocb, to);\n'
    )
    if rip_goto not in ksud_content:
        rip_goto_tab = rip_goto.replace('    ', '\t')
        rip_goto_mod_tab = rip_goto_mod.replace('    ', '\t')
        if rip_goto_tab in ksud_content:
            ksud_content = ksud_content.replace(rip_goto_tab, rip_goto_mod_tab, 1)
            print("OK: read_iter_proxy — added module RC early goto (tab)")
        else:
            print("WARNING: read_iter_proxy — early goto anchor not found, skipping")
    else:
        ksud_content = ksud_content.replace(rip_goto, rip_goto_mod, 1)
        print("OK: read_iter_proxy — added module RC early goto")

    # 5b: Modify read_iter_proxy return check (same pattern as read_proxy)
    rip_return = (
        '\tret = orig_read_iter(iocb, to);\n'
        '\tif (ret != 0 || ksu_rc_pos >= ksu_rc_len) {\n'
        '\t\treturn ret;\n'
        '\t} else {\n'
        '\t\tpr_info("read_iter_proxy: orig read finished, start append rc\\n");\n'
        '\t}\n'
    )
    rip_return_mod = (
        '\tret = orig_read_iter(iocb, to);\n'
        '\tif (ret != 0) {\n'
        '\t\treturn ret;\n'
        '\t}\n'
        '\tif (ksu_rc_pos >= ksu_rc_len && module_rc_pos >= module_rc_len) {\n'
        '\t\treturn ret;\n'
        '\t}\n'
        '\tpr_info("read_iter_proxy: orig read finished, start append rc\\n");\n'
    )
    if rip_return not in ksud_content:
        rip_return_tab = rip_return.replace('    ', '\t')
        rip_return_mod_tab = rip_return_mod.replace('    ', '\t')
        if rip_return_tab in ksud_content:
            ksud_content = ksud_content.replace(rip_return_tab, rip_return_mod_tab, 1)
            print("OK: read_iter_proxy — modified return check (tab)")
        else:
            print("WARNING: read_iter_proxy — return check anchor not found, skipping")
    else:
        ksud_content = ksud_content.replace(rip_return, rip_return_mod, 1)
        print("OK: read_iter_proxy — modified return check")

    # 5c: Add append_module_rc to read_iter_proxy (before its return ret;)
    # read_iter_proxy ends with (legacy ksud_integration.c):
    # \t\t\tpr_info("read_iter_proxy: append done\n");
    # \t\t}
    # \t\tret += append_count;
    # \t}
    # \treturn ret;
    # }
    rip_end = (
        '\t\t\tpr_info("read_iter_proxy: append done\\n");\n'
        '\t\t}\n'
        '\t\tret += append_count;\n'
        '\t}\n'
        '\treturn ret;\n'
        '}'
    )
    rip_end_mod = (
        '\t\t\tpr_info("read_iter_proxy: append done\\n");\n'
        '\t\t}\n'
        '\t\tret += append_count;\n'
        '\t}\n'
        '\n'
        'append_module_rc:\n'
        '\tif (module_rc_pos < module_rc_len) {\n'
        '\t\tappend_count = copy_to_iter(module_rc_buf + module_rc_pos,\n'
        '\t\t\tmodule_rc_len - module_rc_pos, to);\n'
        '\t\tif (!append_count) {\n'
        '\t\t\tpr_info("read_iter_proxy: module append error, appended %zd\\n",\n'
        '\t\t\t\tmodule_rc_pos);\n'
        '\t\t\treturn ret;\n'
        '\t\t}\n'
        '\t\tpr_info("read_iter_proxy: append module %zu\\n", append_count);\n'
        '\t\tmodule_rc_pos += append_count;\n'
        '\t\tret += append_count;\n'
        '\t\tif (module_rc_pos == (ssize_t)module_rc_len) {\n'
        '\t\t\tpr_info("read_iter_proxy: module append done\\n");\n'
        '\t\t\tfree_module_rc();\n'
        '\t\t}\n'
        '\t}\n'
        '\treturn ret;\n'
        '}'
    )
    if rip_end in ksud_content:
        ksud_content = ksud_content.replace(rip_end, rip_end_mod, 1)
        print("OK: read_iter_proxy — added append_module_rc")
    else:
        import re as _re
        rip_flex = _re.search(r'\t\}\n\treturn ret;\n\}', ksud_content)
        if rip_flex:
            ksud_content = ksud_content[:rip_flex.start()] + (
                '\t}\n'
                '\n'
                'append_module_rc:\n'
                '\tif (module_rc_pos < module_rc_len) {\n'
                '\t\tappend_count = copy_to_iter(module_rc_buf + module_rc_pos,\n'
                '\t\t\tmodule_rc_len - module_rc_pos, to);\n'
                '\t\tif (!append_count) {\n'
                '\t\t\tpr_info("read_iter_proxy: module append error, appended %zd\\n",\n'
                '\t\t\t\tmodule_rc_pos);\n'
                '\t\t\treturn ret;\n'
                '\t\t}\n'
                '\t\tpr_info("read_iter_proxy: append module %zu\\n", append_count);\n'
                '\t\tmodule_rc_pos += append_count;\n'
                '\t\tret += append_count;\n'
                '\t\tif (module_rc_pos == (ssize_t)module_rc_len) {\n'
                '\t\t\tpr_info("read_iter_proxy: module append done\\n");\n'
                '\t\t\tfree_module_rc();\n'
                '\t\t}\n'
                '\t}\n'
            ) + ksud_content[rip_flex.start():]
            print("OK: read_iter_proxy — added append_module_rc (flexible)")
        else:
            print("WARNING: read_iter_proxy — end anchor not found, skipping")

    # ============ PART 6: ksu_apply_init_rc_proxy — load_module_rc_once() ============
    # Legacy ksud_integration.c uses 4-space indentation for this function (not tabs).
    # pr_info is on TWO lines with continuation indent.
    anchor_notify = re.compile(
        r'( {4}rc_hooked = true;)\n'
        r'( {4}pr_info\("read init\.rc, comm: %s, rc_count: %zu\\n",\s*current->comm,\s*\n'
        r' {12}ksu_rc_len\);)\n'
    )
    match = anchor_notify.search(ksud_content)
    if match:
        replacement = (
            f'    rc_hooked = true;\n'
            f'    load_module_rc_once();\n'
            f'    pr_info("read init.rc, comm: %s, rc_count: %zu, module_rc: %zu\\n",\n'
            f'            current->comm, ksu_rc_len, module_rc_len);\n'
        )
        ksud_content = anchor_notify.sub(replacement, ksud_content, 1)
        print("OK: ksu_apply_init_rc_proxy — added load_module_rc_once()")
    else:
        # fallback: just find rc_hooked = true; and inject after it
        fallback_anchor = '    rc_hooked = true;'
        if fallback_anchor in ksud_content:
            idx = ksud_content.find(fallback_anchor)
            after = ksud_content[idx + len(fallback_anchor):]
            ksud_content = ksud_content[:idx + len(fallback_anchor)] + (
                '\n    load_module_rc_once();\n'
                '\n    pr_info("read init.rc, comm: %s, rc_count: %zu, module_rc: %zu\\n",\n'
                '            current->comm, ksu_rc_len, module_rc_len);'
            ) + after
            print("OK: ksu_apply_init_rc_proxy — added load_module_rc_once() (fallback)")
        else:
            print("WARNING: ksu_apply_init_rc_proxy — anchor not found, manual check needed")

    # ============ PART 7: fstat handlers — add module_rc_len ============
    # 7a: Kprobe path: sys_fstat_handler_post
    # new_size = size + ksu_rc_len;
    fstat_kprobe = re.compile(
        r'new_size = size \+ ksu_rc_len;\n'
        r'\t\tpr_info\("adding ksu_rc_len: %ld -> %ld"'
    )
    if fstat_kprobe.search(ksud_content):
        ksud_content = ksud_content.replace(
            'new_size = size + ksu_rc_len;',
            'new_size = size + ksu_rc_len + module_rc_len;',
            1  # first occurrence = kprobe path
        )
        print("OK: sys_fstat_handler_post — added module_rc_len")
    else:
        # try tab variant
        fstat_kprobe_tab = re.compile(
            r'new_size = size \+ ksu_rc_len;\n'
            r'\t\tpr_info\("adding ksu_rc_len:'
        )
        if fstat_kprobe_tab.search(ksud_content):
            ksud_content = re.sub(
                r'new_size = size \+ ksu_rc_len;(?=\n\t\tpr_info\("adding ksu_rc_len)',
                'new_size = size + ksu_rc_len + module_rc_len;',
                ksud_content,
                1
            )
            print("OK: sys_fstat_handler_post — added module_rc_len (tab)")
        else:
            print("WARNING: sys_fstat_handler_post — kprobe size anchor not found, skipping")

    # 7b: Manual hook path: ksu_common_newfstat_ret
    # Actual format (legacy HEAD): \tnew_size = size + ksu_rc_len; (ONE tab)
    fstat_manual_pat = r'new_size = size \+ ksu_rc_len;(?=\n\tpr_info\("%s: adding ksu_rc_len:)'
    if re.search(fstat_manual_pat, ksud_content, re.MULTILINE):
        ksud_content = re.sub(
            fstat_manual_pat,
            'new_size = size + ksu_rc_len + module_rc_len;',
            ksud_content,
            1
        )
        print("OK: ksu_common_newfstat_ret — added module_rc_len")
    else:
        print("WARNING: ksu_common_newfstat_ret — manual size anchor not found, skipping")

    # ============ PART 8: Handle the #ifdef KSU_KPROBES_HOOK path of fstat ============
    # The kprobe path has an additional check: 
    # `*(void **)&p->data = NULL;` occurs after kprobe path's statbuf assignment.
    # We also need to update the log message in the kprobe path
    ksud_content = ksud_content.replace(
        'pr_info("adding ksu_rc_len: %ld -> %ld", size, new_size);\n\n\t\t// Attempt to overwrite',
        'pr_info("adding size: %ld -> %ld (rc=%zu module=%zu)", size, new_size, ksu_rc_len, module_rc_len);\n\n\t\t// Attempt to overwrite',
    )
    ksud_content = ksud_content.replace(
        'pr_info("adding ksu_rc_len: %ld -> %ld", size, new_size);',
        'pr_info("adding size: %ld -> %ld (rc=%zu module=%zu)", size, new_size, ksu_rc_len, module_rc_len);',
    )
    print("OK: fstat handlers — updated log messages")

    # ============ WRITE FILES ============
    inject_file(init_c, init_content, "core/init.c (ksu_no_custom_rc)")
    inject_file(ksud_c, ksud_content, "runtime/ksud_integration.c (module RC injection)")

    print("\n=== INITRC MODULE INJECTION COMPLETE ===")
    print("Summary of changes:")
    print("  core/init.c: +ksu_no_custom_rc module_param")
    print("  ksud_integration.c:")
    print("    + module RC path defines + globals")
    print("    + open_module_rc(), load_module_rc_once(), free_module_rc()")
    print("    + read_proxy/read_iter_proxy: append module RC")
    print("    + ksu_apply_init_rc_proxy: call load_module_rc_once()")
    print("    + fstat handlers: report ksu_rc_len + module_rc_len")


if __name__ == '__main__':
    main()
