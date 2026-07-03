#!/usr/bin/env python3
"""
inject-selinux-hide.py — 基于 GLM 5.2 MAX 方案的 selinux_hide 移植
4.19 特有：使用 fake selinux_ss 替代 dev 的 selinux_policy
不依赖 patch_memory/lsm_hook/symbol_resolver

文件路径相对于 kernel 根目录。
KSU 文件在 drivers/kernelsu/selinux/ 和 drivers/kernelsu/include/uapi/ 下。
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

SCRIPT_MARK = "/* KSU_SELINUX_HIDE_INJECTED */"

def resolve(path):
    """Try multiple candidates (symlink or direct path)."""
    for base in [KSU, KERNEL_ROOT]:
        p = os.path.join(base, path)
        if os.path.exists(p):
            return p
    return os.path.join(KSU, path)

def inject(filepath, anchor, snippet, after=True):
    fp = resolve(filepath)
    if not os.path.exists(fp): print(f"  ERROR: {fp} not found"); return False
    with open(fp) as f: c = f.read()
    if SCRIPT_MARK in c: print(f"  SKIP: {fp} already injected"); return True
    if anchor not in c: print(f"  ERROR: anchor not found in {fp}"); return False
    block = "\n" + SCRIPT_MARK + "\n" + snippet.strip() + "\n"
    c = c.replace(anchor, (anchor + block) if after else (block + anchor), 1)
    with open(fp, 'w') as f: f.write(c)
    print(f"  OK: {fp}")
    return True

# ── Code snippets ──

BACKUP_SEPOLICY = """
#include <linux/vmalloc.h>
static struct policydb *ksu_backup_policydb(struct policydb *src)
{
	void *data; struct policy_file fp; size_t len = src->len; struct policydb *dst;
	if (!len) { pr_err("ksu_selinux_hide: backup src->len == 0\\n"); return NULL; }
	data = vmalloc(len); if (!data) return NULL;
	fp.data = data; fp.len = len;
	if (policydb_write(src, &fp)) { pr_err("ksu_selinux_hide: write failed\\n"); vfree(data); return NULL; }
	dst = kvzalloc(sizeof(*dst), GFP_KERNEL); if (!dst) { vfree(data); return NULL; }
	policydb_init(dst); fp.data = data; fp.len = len;
	if (policydb_read(dst, &fp)) { policydb_destroy(dst); kvfree(dst); vfree(data); return NULL; }
	dst->len = len; vfree(data);
	pr_info("ksu_selinux_hide: backup ok, len=%zu\\n", len); return dst;
}"""

SELINUX_HIDE_CORE = """
#include <linux/rwlock.h>
#include "ss/services.h"
#include <linux/lsm_hooks.h>
#include "policy/feature.h"

static struct selinux_ss  ksu_backup_ss;
static struct selinux_state ksu_fake_state;
static bool ksu_backup_ready __read_mostly = false;
static DEFINE_MUTEX(ksu_selinux_hide_mutex);
static bool ksu_selinux_hide_enabled __read_mostly = false;
static bool ksu_selinux_hide_running __read_mostly = false;

void ksu_selinux_save_backup(void *src_db_v)
{
	struct policydb *src_db = src_db_v;
	struct policydb *bak;
	if (ksu_backup_ready) return;
	bak = ksu_backup_policydb(src_db);
	if (!bak) { pr_err("ksu_selinux_hide: save backup failed\\n"); return; }
	ksu_backup_ss = *selinux_state.ss;
	rwlock_init(&ksu_backup_ss.policy_rwlock);
	ksu_backup_ss.policydb = *bak; kvfree(bak);
	ksu_fake_state = selinux_state; ksu_fake_state.ss = &ksu_backup_ss;
	ksu_backup_ready = true;
	pr_info("ksu_selinux_hide: backup policy ready\\n");
}

typedef int (*setprocattr_fn)(const char *, void *, size_t);
static setprocattr_fn orig_setprocattr;
static struct security_hook_list *setprocattr_entry;

static int my_setprocattr(const char *name, void *value, size_t size)
{
	if (ksu_selinux_hide_enabled && current_uid().val >= 10000) {
		int error; u32 mysid = current_sid(), sid; char *str = value;
		error = avc_has_perm(&selinux_state, mysid, mysid, SECCLASS_PROCESS, PROCESS__SETCURRENT, NULL);
		if (error) return error;
		if (size && str[0] && str[0] != '\\n') {
			if (str[size - 1] == '\\n') { str[size - 1] = 0; size--; }
			error = security_context_to_sid(&ksu_fake_state, str, size, &sid, GFP_KERNEL);
			if (error) return error;
		}
	}
	return orig_setprocattr(name, value, size);
}

static void hook_selinux_setprocattr(void)
{
	struct security_hook_heads *heads; struct security_hook_list *hp; setprocattr_fn target;
	if (setprocattr_entry) return;
	heads = (struct security_hook_heads *)kallsyms_lookup_name("security_hook_heads");
	target = (setprocattr_fn)kallsyms_lookup_name("selinux_setprocattr");
	if (!heads || !target) { pr_err("ksu_selinux_hide: symbols not found\\n"); return; }
	hlist_for_each_entry(hp, &heads->setprocattr, list) {
		if ((setprocattr_fn)hp->hook.setprocattr == target) {
			orig_setprocattr = target; setprocattr_entry = hp;
			hp->hook.setprocattr = (void *)my_setprocattr;
			pr_info("ksu_selinux_hide: selinux_setprocattr hooked\\n"); return;
		}
	}
	pr_err("ksu_selinux_hide: setprocattr entry not found\\n");
}

static void unhook_selinux_setprocattr(void)
{
	if (setprocattr_entry && orig_setprocattr) {
		setprocattr_entry->hook.setprocattr = (void *)orig_setprocattr;
		setprocattr_entry = NULL; orig_setprocattr = NULL;
	}
}

typedef ssize_t (*write_op_fn)(struct file *, char *, size_t);
static write_op_fn *selinux_write_op;
static write_op_fn orig_write_context, orig_write_access;
#define KSU_SIMPLE_TX_LIMIT (PAGE_SIZE - 64)

static ssize_t my_write_context(struct file *file, char *buf, size_t size)
{
	char *canon = NULL; u32 sid, len = 0; ssize_t length;
	if (!ksu_selinux_hide_enabled || current_uid().val < 10000)
		return orig_write_context(file, buf, size);
	length = avc_has_perm(&selinux_state, current_sid(), SECINITSID_SECURITY, SECCLASS_SECURITY, SECURITY__CHECK_CONTEXT, NULL);
	if (length) goto out;
	length = security_context_to_sid(&ksu_fake_state, buf, size, &sid, GFP_KERNEL);
	if (length) goto out;
	length = security_sid_to_context(&ksu_fake_state, sid, &canon, &len);
	if (length) goto out;
	if (len > KSU_SIMPLE_TX_LIMIT) { length = -ERANGE; goto out; }
	memcpy(buf, canon, len); length = len;
out: kfree(canon); return length;
}

static ssize_t my_write_access(struct file *file, char *buf, size_t size)
{
	char *scon = NULL, *tcon = NULL; u16 tclass; u32 ssid, tsid;
	struct av_decision avd; ssize_t length;
	if (!ksu_selinux_hide_enabled || current_uid().val < 10000)
		return orig_write_access(file, buf, size);
	length = avc_has_perm(&selinux_state, current_sid(), SECINITSID_SECURITY, SECCLASS_SECURITY, SECURITY__COMPUTE_AV, NULL);
	if (length) goto out;
	scon = kzalloc(size + 1, GFP_KERNEL); tcon = kzalloc(size + 1, GFP_KERNEL);
	if (!scon || !tcon) { length = -ENOMEM; goto out; }
	if (sscanf(buf, "%s %s %hu", scon, tcon, &tclass) != 3) { length = -EINVAL; goto out; }
	length = security_context_str_to_sid(&ksu_fake_state, scon, &ssid, GFP_KERNEL);
	if (length) goto out;
	length = security_context_str_to_sid(&ksu_fake_state, tcon, &tsid, GFP_KERNEL);
	if (length) goto out;
	security_compute_av_user(&ksu_fake_state, ssid, tsid, tclass, &avd);
	length = scnprintf(buf, KSU_SIMPLE_TX_LIMIT, "%%x %%x %%x %%x %%u %%x", avd.allowed, 0xffffffff, avd.auditallow, avd.auditdeny, avd.seqno, avd.flags);
out: kfree(tcon); kfree(scon); return length;
}

static void hook_selinux_write_ops(void)
{
	selinux_write_op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!selinux_write_op) { pr_err("ksu_selinux_hide: write_op not found\\n"); return; }
	orig_write_context = selinux_write_op[5]; selinux_write_op[5] = my_write_context;
	orig_write_access = selinux_write_op[6]; selinux_write_op[6] = my_write_access;
	pr_info("ksu_selinux_hide: write_op[5/6] context/access hooked\\n");
}

static void unhook_selinux_write_ops(void)
{
	if (orig_write_context) selinux_write_op[5] = orig_write_context;
	if (orig_write_access) selinux_write_op[6] = orig_write_access;
	orig_write_context = orig_write_access = NULL;
}

static int selinux_hide_enable(void)
{
	pr_info("ksu_selinux_hide: enable\\n");
	if (!ksu_backup_ready) { pr_err("backup not ready\\n"); return -EAGAIN; }
	hook_selinux_setprocattr();
	hook_selinux_write_ops();
	return 0;
}

static void selinux_hide_disable(void)
{
	pr_info("ksu_selinux_hide: disable\\n");
	unhook_selinux_setprocattr();
	unhook_selinux_write_ops();
}

static int selinux_hide_get(u64 *value) { *value = ksu_selinux_hide_enabled ? 1 : 0; return 0; }
static int selinux_hide_set(u64 value)
{
	bool enable = !!value; int ret = 0;
	mutex_lock(&ksu_selinux_hide_mutex);
	ksu_selinux_hide_enabled = enable;
	if (enable) { if (!ksu_selinux_hide_running) { ret = selinux_hide_enable(); if (!ret) ksu_selinux_hide_running = true; } }
	else { if (ksu_selinux_hide_running) { selinux_hide_disable(); ksu_selinux_hide_running = false; } }
	mutex_unlock(&ksu_selinux_hide_mutex);
	return ret;
}

static const struct ksu_feature_handler selinux_hide_handler = {
	.feature_id = KSU_FEATURE_SELINUX_HIDE, .name = "selinux_hide",
	.get_handler = selinux_hide_get, .set_handler = selinux_hide_set,
};
"""

SELINUX_RULES_BACKUP = "	ksu_selinux_save_backup(db);  /* selinux_hide: snapshot */"

SELINUX_H_DECL = "void ksu_selinux_save_backup(void *db);"

UAPI_FEATURE_ENUM = "\tKSU_FEATURE_SELINUX_HIDE = 5, /* selinux_hide complete */"

# ── File-relative paths for fix_path resolution ──
FILES = {
    "sepolicy.c": "selinux/sepolicy.c",
    "selinux.c": "selinux/selinux.c",
    "rules.c": "selinux/rules.c",
    "selinux.h": "selinux/selinux.h",
    "feature.h": "include/uapi/feature.h",
}

def main():
    print("[selinux_hide] target=%s" % KERNEL_ROOT)
    ok = True

    # 1. sepolicy.c: append backup function after #endif
    ok &= inject(FILES["sepolicy.c"], "#endif // SELINUX_POLICY_INSTEAD_SELINUX_SS", BACKUP_SEPOLICY)

    # 2. selinux.c: insert core code before existing hide_status functions
    ok &= inject(FILES["selinux.c"], "void ksu_selinux_hide_status_handle_second_stage(void)", SELINUX_HIDE_CORE, after=False)

    # 3. rules.c: insert backup call in 4.19 path
    ok &= inject(FILES["rules.c"], "\tdb = get_policydb();\n", SELINUX_RULES_BACKUP)

    # 4. selinux.h: add declaration
    ok &= inject(FILES["selinux.h"], "void ksu_selinux_hide_status_init(void);", SELINUX_H_DECL)

    # 5. uapi/feature.h: add KSU_FEATURE_SELINUX_HIDE
    ok &= inject(FILES["feature.h"], "KSU_FEATURE_SELINUX_HIDE_STATUS = 4,", UAPI_FEATURE_ENUM)

    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
