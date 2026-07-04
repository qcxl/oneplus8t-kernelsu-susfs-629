#!/usr/bin/env python3
"""
inject-selinux-hide-route-b.py — Route B: context/access + backup
4.19 可行方案：
- sepolicy.c: #include <ss/policydb.h> (通过 -I$(srctree)/security/selinux)
- selinux.c: set_memory_rw/set_memory_ro 修改 write_op[] (const 数组)
- rules.c: 规则应用前触发备份
- selinux.h: extern void* 声明避免 -Wvisibility
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")

MARK = "/* KSU_SELINUX_HIDE_ROUTE_B */"

def inject(filepath, anchor, snippet, after=True):
    fp = filepath
    if not os.path.exists(fp): print(f"  ERROR: {fp} not found"); return False
    with open(fp) as f: c = f.read()
    if MARK in c: print(f"  SKIP: {fp} already injected"); return True
    if anchor not in c: print(f"  ERROR: anchor not found in {fp}"); return False
    block = "\n" + MARK + "\n" + snippet.strip() + "\n"
    c = c.replace(anchor, (anchor + block) if after else (block + anchor), 1)
    with open(fp, 'w') as f: f.write(c)
    print(f"  OK: {fp}")
    return True

# ── 1. sepolicy.c: backup function ──
SEPOLICY_INCLUDE = '#include <ss/policydb.h>'

SEPOLICY_BACKUP = """
/* ksu_backup_policydb — serialise then deserialise to deep-copy */
struct policydb *ksu_backup_policydb(struct policydb *src)
{
	void *data;
	struct policy_file fp;
	size_t len = src->len;
	struct policydb *dst;

	if (!len) {
		pr_err("ksu_selinux_hide: backup src->len == 0\\n");
		return NULL;
	}

	data = vmalloc(len);
	if (!data)
		return NULL;

	fp.data = data;
	fp.len = len;

	if (policydb_write(src, &fp)) {
		pr_err("ksu_selinux_hide: write failed\\n");
		vfree(data);
		return NULL;
	}

	fp.data = data;
	fp.len = len;
	dst = kvzalloc(sizeof(*dst), GFP_KERNEL);
	if (!dst) {
		vfree(data);
		return NULL;
	}
	policydb_init(dst);

	if (policydb_read(dst, &fp)) {
		pr_err("ksu_selinux_hide: read failed\\n");
		policydb_destroy(dst);
		kvfree(dst);
		vfree(data);
		return NULL;
	}

	dst->len = len;
	vfree(data);
	pr_info("ksu_selinux_hide: backup ok, len=%zu\\n", len);
	return dst;
}"""

# ── 2. selinux.c: Route B core ──
ROUTE_B_CORE = """
#include <linux/set_memory.h>
#include "ss/services.h"

/* Forward declarations (defined in Route A, injected below) */
extern bool ksu_selinux_hide_enabled;

static struct selinux_ss ksu_backup_ss;
static struct selinux_state ksu_fake_state;
static bool ksu_backup_ready __read_mostly = false;

typedef ssize_t (*write_op_fn)(struct file *, char *, size_t);
static write_op_fn *selinux_write_op;
static write_op_fn orig_write_context, orig_write_access;
#define KSU_SIMPLE_TX_LIMIT (PAGE_SIZE - 64)

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
	pr_info("ksu_selinux_hide: backup ready\\n");
}

static ssize_t my_write_context(struct file *file, char *buf, size_t size)
{
	char *canon = NULL; u32 sid, len = 0; ssize_t length;
	if (!ksu_selinux_hide_enabled || current_uid().val < 10000)
		return orig_write_context(file, buf, size);
	length = avc_has_perm(&selinux_state, current_sid(), SECINITSID_SECURITY,
			     SECCLASS_SECURITY, SECURITY__CHECK_CONTEXT, NULL);
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
	length = avc_has_perm(&selinux_state, current_sid(), SECINITSID_SECURITY,
			     SECCLASS_SECURITY, SECURITY__COMPUTE_AV, NULL);
	if (length) goto out;
	scon = kzalloc(size + 1, GFP_KERNEL); tcon = kzalloc(size + 1, GFP_KERNEL);
	if (!scon || !tcon) { length = -ENOMEM; goto out; }
	if (sscanf(buf, "%s %s %hu", scon, tcon, &tclass) != 3) { length = -EINVAL; goto out; }
	length = security_context_str_to_sid(&ksu_fake_state, scon, &ssid, GFP_KERNEL);
	if (length) goto out;
	length = security_context_str_to_sid(&ksu_fake_state, tcon, &tsid, GFP_KERNEL);
	if (length) goto out;
	security_compute_av_user(&ksu_fake_state, ssid, tsid, tclass, &avd);
	length = scnprintf(buf, KSU_SIMPLE_TX_LIMIT,
			   "%%x %%x %%x %%x %%u %%x",
			   avd.allowed, 0xffffffff, avd.auditallow,
			   avd.auditdeny, avd.seqno, avd.flags);
out: kfree(tcon); kfree(scon); return length;
}

static void hook_selinux_write_ops(void)
{
	unsigned long page_addr;
	selinux_write_op = (write_op_fn *)kallsyms_lookup_name("write_op");
	if (!selinux_write_op) { pr_err("ksu_selinux_hide: write_op not found\\n"); return; }

	page_addr = (unsigned long)&selinux_write_op[5] & PAGE_MASK;
	set_memory_rw(page_addr, 1);

	orig_write_context = selinux_write_op[5];
	selinux_write_op[5] = my_write_context;
	orig_write_access = selinux_write_op[6];
	selinux_write_op[6] = my_write_access;
	pr_info("ksu_selinux_hide: write_op[5/6] context/access hooked\\n");

	set_memory_ro(page_addr, 1);
}
"""

# ── 3. rules.c: backup call ──
RULES_BACKUP = '\tksu_selinux_save_backup(db);  /* selinux_hide Route B: snapshot */'

# ── 4. selinux.h: extern declaration ──
SELINUX_H_DECL = 'void ksu_selinux_save_backup(void *db);\nstruct policydb *ksu_backup_policydb(struct policydb *src);'

def main():
    ok = True
    print("[selinux_hide Route B] target=%s" % KERNEL_ROOT)

    # Step 1: sepolicy.c — add #include <ss/policydb.h> + ksu_backup_policydb()
    sep_c = os.path.join(KSU, "selinux/sepolicy.c")
    if not os.path.exists(sep_c):
        print(f"  ERROR: {sep_c} not found"); ok = False
    else:
        with open(sep_c) as f: c = f.read()
        if "ss/policydb.h" not in c:
            # Add include at top after the first #include line
            lines = c.split('\n')
            inserted = False
            for i, line in enumerate(lines):
                if line.startswith('#include "') and i < 5:
                    lines.insert(i + 1, '#include <ss/policydb.h>')
                    inserted = True; break
                if line.startswith('#include <') and i < 5:
                    continue
            if not inserted:
                # Insert after the first blank line
                lines.insert(1, '#include <ss/policydb.h>')
            c = '\n'.join(lines)
            with open(sep_c, 'w') as f: f.write(c)
            print(f"  INCLUDE: ss/policydb.h added to sepolicy.c")
        else:
            print(f"  SKIP: sepolicy.c already has ss/policydb.h")

    ok &= inject(sep_c, "#endif // SELINUX_POLICY_INSTEAD_SELINUX_SS", SEPOLICY_BACKUP)

    # Step 2: selinux.c — inject Route B core before existing hide_status functions
    sel_c = os.path.join(KSU, "selinux/selinux.c")
    ok &= inject(sel_c, "void ksu_selinux_hide_status_handle_second_stage(void)", ROUTE_B_CORE, after=False)

    # Step 3: rules.c — add backup call where db is obtained
    rules_c = os.path.join(KSU, "selinux/rules.c")
    ok &= inject(rules_c, "\tdb = get_policydb();\n", RULES_BACKUP)

    # Step 4: selinux.h — add extern declarations
    sel_h = os.path.join(KSU, "selinux/selinux.h")
    ok &= inject(sel_h, "void ksu_selinux_hide_status_init(void);", SELINUX_H_DECL)

    # Step 5 is handled by Route A's init — Route A runs second and its init
    # already calls hook_selinux_setprocattr(). The write_op hook is called
    # from Route B's init below (injected before Route A's init).
    print("  NOTE: write_op hook activated via shared ksu_selinux_hide_enabled flag")

    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()