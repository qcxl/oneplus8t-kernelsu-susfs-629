#!/usr/bin/env python3
"""
inject-open-redirect-enhanced.py — Port SUSFS v2.2.0 open_redirect enhancement to 4.19.
Backward-compatible: keeps old struct field names, adds new fields at end.
Old dispatch signature preserved (int, struct*), no dispatch/supercall.c changes needed.

Changes:
  - susfs_def.h: UID_SCHEME enum
  - susfs.h: enhanced structs (old fields kept + new fields added)
  - susfs.c: OLD open_redirect block removed + NEW block injected with spoof functions
  - fs/susfs.c: add #include <linux/fuse.h>
  - fs/open.c: do_sys_open retry for path redirection
  - fs/namei.c: vfs_readlink hook
  - fs/proc/base.c: do_proc_readlink hook
  - fs/statfs.c: vfs_statfs hook
  - All VFS files: #include <linux/susfs_def.h> for INODE_STATE_OPEN_REDIRECT

Returns 0 on success, 1 on failure.
"""

import sys, os

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."

def find_file(root, candidates):
    for c in candidates:
        p = os.path.join(root, c)
        if os.path.exists(p):
            return p
    return None

def read_file(path):
    with open(path) as f:
        return f.read()

def write_file(path, content):
    with open(path, 'w') as f:
        f.write(content)

# ─── 1. susfs_def.h: UID_SCHEME enum ────────────────────────────────────

def step1_susfs_def_h():
    p = find_file(KERNEL_ROOT, ["include/linux/susfs_def.h"])
    if not p:
        print("  ERROR: susfs_def.h not found"); return False
    c = read_file(p)
    if "UID_NON_APP_PROC" in c:
        print("  susfs_def.h: UID_SCHEME already present"); return True
    uid = "\n\nenum UID_SCHEME {\n\tUID_NON_APP_PROC = 0,\n\tUID_ROOT_PROC_EXCEPT_SU_PROC,\n\tUID_NON_SU_PROC,\n\tUID_UMOUNTED_APP_PROC,\n\tUID_UMOUNTED_PROC,\n};"
    lines = c.split('\n')
    last = 0
    for i, l in enumerate(lines):
        if l.strip().startswith('#define INODE_STATE_'):
            last = i
    lines.insert(last + 1, uid)
    write_file(p, '\n'.join(lines))
    print("  susfs_def.h: UID_SCHEME added"); return True

# ─── 2. susfs.h: backward-compatible struct ──────────────────────────────

def step2_susfs_h():
    p = find_file(KERNEL_ROOT, ["include/linux/susfs.h"])
    if not p:
        print("  ERROR: susfs.h not found"); return False
    c = read_file(p)
    if "uid_scheme" in c and "target_dev" in c:
        print("  susfs.h: already enhanced"); return True

    # Add linux/statfs.h include
    if "#include <linux/statfs.h>" not in c:
        lines = c.split('\n')
        last = 0
        for i, l in enumerate(lines):
            if l.strip().startswith('#include'):
                last = i
        lines.insert(last + 1, '#include <linux/statfs.h>')
        c = '\n'.join(lines)

    # Replace user-space struct: keep old fields, add uid_scheme + err
    old_usr = "struct st_susfs_open_redirect {\n\tunsigned long                    target_ino;\n\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tchar                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];\n};"
    new_usr = "struct st_susfs_open_redirect {\n\tunsigned long                    target_ino;\n\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tchar                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tint                              uid_scheme;\n\tint                              err;\n};"
    if old_usr in c:
        c = c.replace(old_usr, new_usr)
    else:
        print("  WARNING: old user struct not found"); return False

    # Replace hlist struct: keep old fields, add new ones at end
    old_hlist = "struct st_susfs_open_redirect_hlist {\n\tunsigned long                    target_ino;\n\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tchar                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tstruct hlist_node                node;\n};"
    new_hlist = "struct st_susfs_open_redirect_hlist {\n\tunsigned long                    target_ino;\n\tchar                             target_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tchar                             redirected_pathname[SUSFS_MAX_LEN_PATHNAME];\n\tunsigned long                    target_dev;\n\tunsigned long                    redirected_ino;\n\tunsigned long                    redirected_dev;\n\tint                              spoofed_mnt_id;\n\tstruct kstatfs                   spoofed_kstatfs;\n\tint                              uid_scheme;\n\tbool                             reversed_lookup_only;\n\tstruct hlist_node                node;\n};"
    if old_hlist in c:
        c = c.replace(old_hlist, new_hlist)
    else:
        print("  WARNING: old hlist struct not found"); return False

    # Add spoof function declarations
    spoof_decls = """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode);
int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen);
int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);
int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf);
int susfs_open_redirect_spoof_seq_show(struct inode *inode, int *out_mnt_id, unsigned long *out_ino);
#endif
"""
    marker = "int susfs_add_open_redirect(struct st_susfs_open_redirect* __user user_info);"
    if marker in c and "spoof_do_sys_openat" not in c:
        c = c.replace(marker, marker + spoof_decls)

    write_file(p, c)
    print("  susfs.h: backward-compatible structs updated"); return True

# ─── 3. susfs.c: remove old open_redirect, inject new code ──────────────

def step3_susfs_c():
    p = find_file(KERNEL_ROOT, ["fs/susfs.c"])
    if not p:
        print("  ERROR: susfs.c not found"); return False
    c = read_file(p)

    if "susfs_open_redirect_spoof_do_sys_openat" in c:
        print("  susfs.c: already enhanced"); return True

    # Add FUSE_SUPER_MAGIC include
    if "#include <linux/fuse.h>" not in c:
        lines = c.split('\n')
        last = 0
        for i, l in enumerate(lines):
            if l.strip().startswith('#include'):
                last = i
        lines.insert(last + 1, '#include <linux/fuse.h>')
        c = '\n'.join(lines)

    # Remove OLD open_redirect section (starts with '/* open_redirect */', ends with '#endif // #ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT')
    start = c.find("/* open_redirect */")
    end_marker = "#endif // #ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT"
    if start >= 0:
        end = c.find(end_marker, start)
        if end >= 0:
            end = end + len(end_marker)
            old_section = c[start:end]
            c = c.replace(old_section, "")
            print("  susfs.c: old open_redirect section removed")
        else:
            print("  ERROR: end marker not found"); return False

    new_code = r"""

/* open_redirect enhanced (v2.2.0 port, backward-compatible with v1.5.5 dispatch) */
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
static DEFINE_MUTEX(susfs_mutex_lock_open_redirect);
static DEFINE_HASHTABLE(OPEN_REDIRECT_HLIST, 10);
static struct srcu_struct susfs_srcu_open_redirect;

int susfs_add_open_redirect(struct st_susfs_open_redirect * __user user_info)
{
	struct st_susfs_open_redirect info = {0};
	struct st_susfs_open_redirect_hlist *new_entry, *tmp_entry;
	struct hlist_node *tmp_node;
	struct path target_path, redirected_path;
	struct inode *target_inode, *redirected_inode;
	int bkt;
	bool dup_found = false;

	if (copy_from_user(&info, user_info, sizeof(info)))
		return -EFAULT;
	if (*info.target_pathname == '\0')
		return -EINVAL;
	if (info.uid_scheme < UID_NON_APP_PROC || info.uid_scheme > UID_UMOUNTED_PROC)
		return -EINVAL;

	info.err = kern_path(info.redirected_pathname, 0, &redirected_path);
	if (info.err) return info.err;
	info.err = kern_path(info.target_pathname, 0, &target_path);
	if (info.err) { path_put(&redirected_path); return info.err; }

	redirected_inode = d_backing_inode(redirected_path.dentry);
	target_inode = d_backing_inode(target_path.dentry);
	if (!target_inode || !redirected_inode) {
		path_put(&target_path); path_put(&redirected_path);
		return -ENOENT;
	}

	new_entry = kzalloc(sizeof(struct st_susfs_open_redirect_hlist), GFP_KERNEL);
	if (!new_entry) { path_put(&target_path); path_put(&redirected_path); return -ENOMEM; }

	new_entry->target_ino = target_inode->i_ino;
	new_entry->target_dev = target_inode->i_sb->s_dev;
	strscpy(new_entry->target_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
	strscpy(new_entry->redirected_pathname, info.redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
	new_entry->redirected_ino = redirected_inode->i_ino;
	new_entry->redirected_dev = redirected_inode->i_sb->s_dev;
	new_entry->uid_scheme = info.uid_scheme;
	new_entry->reversed_lookup_only = false;
	new_entry->spoofed_mnt_id = real_mount(target_path.mnt)->mnt_id;
	(void)vfs_statfs(&target_path, &new_entry->spoofed_kstatfs);

	mutex_lock(&susfs_mutex_lock_open_redirect);
	hash_for_each_possible_safe(OPEN_REDIRECT_HLIST, tmp_entry, tmp_node, node, target_inode->i_ino) {
		if (!strcmp(tmp_entry->target_pathname, info.target_pathname)) {
			hash_del_rcu(&tmp_entry->node);
			dup_found = true; break;
		}
	}
	hash_add_rcu(OPEN_REDIRECT_HLIST, &new_entry->node, new_entry->target_ino);
	target_inode->i_state |= INODE_STATE_OPEN_REDIRECT;
	redirected_inode->i_state |= INODE_STATE_OPEN_REDIRECT;
	mutex_unlock(&susfs_mutex_lock_open_redirect);
	synchronize_rcu();
	if (dup_found) kfree(tmp_entry);

	info.err = 0;
	path_put(&target_path); path_put(&redirected_path);
	if (copy_to_user(&user_info->err, &info.err, sizeof(info.err)))
		return -EFAULT;
	SUSFS_LOGI("CMD_SUSFS_ADD_OPEN_REDIRECT -> ret: 0, uid_scheme: %d\n", info.uid_scheme);
	return 0;
}

struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode)
{
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (!entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			switch(entry->uid_scheme) {
				case UID_NON_APP_PROC:
					if (current_uid().val % 100000 < 10000) break; else goto unlock;
				case UID_ROOT_PROC_EXCEPT_SU_PROC:
					if (current_uid().val == 0 && !susfs_is_current_ksu_domain()) break; else goto unlock;
				case UID_NON_SU_PROC:
					if (!susfs_is_current_ksu_domain()) break; else goto unlock;
				case UID_UMOUNTED_APP_PROC:
					if (susfs_is_current_proc_umounted_app()) break; else goto unlock;
				case UID_UMOUNTED_PROC:
					if (susfs_is_current_proc_umounted()) break; else goto unlock;
				default: goto unlock;
			}
			srcu_read_unlock(&susfs_srcu_open_redirect, idx);
			return getname_kernel(entry->redirected_pathname);
		}
	}
unlock:
	srcu_read_unlock(&susfs_srcu_open_redirect, idx);
	return NULL;
}

int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen)
{
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			if (strlen(entry->redirected_pathname) >= buflen) {
				srcu_read_unlock(&susfs_srcu_open_redirect, idx);
				return -ENAMETOOLONG;
			}
			if (copy_to_user(buffer, entry->redirected_pathname, strlen(entry->redirected_pathname))) {
				srcu_read_unlock(&susfs_srcu_open_redirect, idx);
				return -EFAULT;
			}
			srcu_read_unlock(&susfs_srcu_open_redirect, idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, idx);
	return -ENOENT;
}

int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen)
{
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			if (strlen(entry->redirected_pathname) >= buflen) {
				srcu_read_unlock(&susfs_srcu_open_redirect, idx);
				return -ENAMETOOLONG;
			}
			strscpy(tmp_buf, entry->redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
			srcu_read_unlock(&susfs_srcu_open_redirect, idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, idx);
	return -ENOENT;
}

int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf)
{
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			memcpy(buf, &entry->spoofed_kstatfs, sizeof(struct kstatfs));
			srcu_read_unlock(&susfs_srcu_open_redirect, idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, idx);
	return -EINVAL;
}

int susfs_open_redirect_spoof_seq_show(struct inode *inode, int *out_mnt_id, unsigned long *out_ino)
{
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			*out_mnt_id = entry->spoofed_mnt_id;
			*out_ino = entry->redirected_ino;
			srcu_read_unlock(&susfs_srcu_open_redirect, idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, idx);
	return -EINVAL;
}
#endif /* CONFIG_KSU_SUSFS_OPEN_REDIRECT */

/*
 * This extra #ifdef is necessary because the inject script removes the
 * entire old open_redirect section including its trailing #endif. The
 * new section above has its own #endif. Everything below is unharmed.
 */
"""

    # Insert new code before susfs_init
    marker = "\n/* susfs_init */"
    if marker in c:
        c = c.replace(marker, new_code + marker)
    else:
        marker = "\nvoid susfs_init(void)"
        if marker in c:
            c = c.replace(marker, new_code + marker)
        else:
            print("  ERROR: susfs_init not found"); return False

    # Add SRCU init in susfs_init
    srcu_line = "\tinit_srcu_struct(&susfs_srcu_open_redirect);\n"
    spin_init = "\tspin_lock_init(&susfs_spin_lock);\n"
    if spin_init in c and srcu_line not in c:
        c = c.replace(spin_init, spin_init + srcu_line)

    write_file(p, c)
    print("  susfs.c: enhanced open_redirect injected"); return True

# ─── 4. VFS hooks ──────────────────────────────────────────────────────

def add_include_and_extern(fs_path, guard_name, extern_line):
    """Add #include <linux/susfs_def.h> and extern after last #include."""
    if not os.path.exists(fs_path):
        return False
    c = read_file(fs_path)
    if extern_line.split('(')[0].strip() in c:
        return True  # already hooked
    block = "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n#include <linux/susfs_def.h>\n" + extern_line + "\n#endif\n"
    lines = c.split('\n')
    last = 0
    for i, l in enumerate(lines):
        if l.strip().startswith('#include'):
            last = i
    lines.insert(last + 1, block)
    write_file(fs_path, '\n'.join(lines))
    return False  # not already hooked, needs spoof call added too

def step4_vfs_hooks():
    ok = True

    # fs/open.c: do_sys_open retry
    p = os.path.join(KERNEL_ROOT, "fs/open.c")
    if os.path.exists(p):
        already = add_include_and_extern(p, "OPEN_REDIRECT",
            "extern struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode);")
        if not already:
            c = read_file(p)
            # Variable declaration in do_sys_open
            for sig in [
                "long do_sys_open(int dfd, const char __user *filename, int flags, umode_t mode)\n{",
            ]:
                if sig in c and "is_inode_open_redirect" not in c:
                    c = c.replace(sig, sig + "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n\tbool is_inode_open_redirect = false;\n#endif")
                    break
            # retry label
            retry_marker = "\tfd = get_unused_fd_flags(flags);"
            if retry_marker in c and "retry:" not in c:
                c = c.replace(retry_marker, "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nretry:\n#endif\n\tfd = get_unused_fd_flags(flags);")
            # spoof call after do_filp_open
            dop = "\t\tstruct file *f = do_filp_open(dfd, tmp, &op);"
            if dop in c and "spoof_do_sys_openat" not in c:
                spoof = """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\t\tif (!is_inode_open_redirect && f && !IS_ERR(f)) {
\t\t\tstruct inode *inode_s = file_inode(f);
\t\t\tif (inode_s && (inode_s->i_state & INODE_STATE_OPEN_REDIRECT)) {
\t\t\t\tstruct filename *fake = susfs_open_redirect_spoof_do_sys_openat(inode_s);
\t\t\t\tif (fake && !IS_ERR(fake)) {
\t\t\t\t\tis_inode_open_redirect = true;
\t\t\t\t\tfilp_close(f, NULL);
\t\t\t\t\tputname(tmp);
\t\t\t\t\ttmp = fake;
\t\t\t\t\tgoto retry;
\t\t\t\t}
\t\t\t}
\t\t}
#endif
"""
                c = c.replace(dop, dop + spoof)
            write_file(p, c)
            print("  fs/open.c: do_sys_open hooked")
    else:
        print("  WARNING: fs/open.c not found"); ok = False

    # fs/namei.c: vfs_readlink
    p = os.path.join(KERNEL_ROOT, "fs/namei.c")
    if os.path.exists(p):
        already = add_include_and_extern(p, "OPEN_REDIRECT",
            "extern int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen);")
        if not already:
            c = read_file(p)
            old = "\t\tif (inode->i_op->readlink)\n\t\t\treturn inode->i_op->readlink(dentry, buffer, buflen);"
            new = """\t\tif (inode->i_op->readlink) {
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\t\t\tif (inode->i_state & INODE_STATE_OPEN_REDIRECT) {
\t\t\t\tint _r = susfs_open_redirect_spoof_vfs_readlink(inode, buffer, buflen);
\t\t\t\tif (!_r) return _r;
\t\t\t}
#endif
\t\t\treturn inode->i_op->readlink(dentry, buffer, buflen);
\t\t}"""
            if old in c:
                c = c.replace(old, new)
                write_file(p, c)
                print("  fs/namei.c: vfs_readlink hooked")
    else:
        print("  WARNING: fs/namei.c not found"); ok = False

    # fs/proc/base.c: do_proc_readlink
    p = os.path.join(KERNEL_ROOT, "fs/proc/base.c")
    if os.path.exists(p):
        already = add_include_and_extern(p, "OPEN_REDIRECT",
            "extern int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);")
        if not already:
            c = read_file(p)
            spoof = """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif ((path->dentry->d_inode->i_state & INODE_STATE_OPEN_REDIRECT)) {
\t\tif (!susfs_open_redirect_spoof_do_proc_readlink(path->dentry->d_inode, tmp, buflen)) {
\t\t\tint _len = strlen(tmp);
\t\t\tif (copy_to_user(buffer, tmp, _len)) _len = -EFAULT;
\t\t\tkfree(tmp);
\t\t\treturn _len;
\t\t}
\t}
#endif
"""
            marker = "\tchar *tmp = kmalloc(PATH_MAX, GFP_KERNEL);"
            if marker in c:
                c = c.replace(marker, marker + spoof)
                write_file(p, c)
                print("  fs/proc/base.c: do_proc_readlink hooked")
    else:
        print("  WARNING: fs/proc/base.c not found"); ok = False

    # fs/statfs.c: vfs_statfs
    p = os.path.join(KERNEL_ROOT, "fs/statfs.c")
    if os.path.exists(p):
        already = add_include_and_extern(p, "OPEN_REDIRECT",
            "extern int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf);")
        if not already:
            c = read_file(p)
            old = "\tstruct inode *inode = d_backing_inode(path->dentry);"
            new = """\tstruct inode *inode = d_backing_inode(path->dentry);
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tif (inode && (inode->i_state & INODE_STATE_OPEN_REDIRECT)) {
\t\tint ret = susfs_open_redirect_spoof_vfs_statfs(inode, buf);
\t\tif (!ret) return ret;
\t}
#endif"""
            if old in c:
                c = c.replace(old, new)
                write_file(p, c)
                print("  fs/statfs.c: vfs_statfs hooked")
    else:
        print("  WARNING: fs/statfs.c not found"); ok = False

    return ok

# ─── Main ──────────────────────────────────────────────────────────────

def main():
    print("[open_redirect enhanced] target=%s" % KERNEL_ROOT)
    ok = True
    ok &= step1_susfs_def_h()
    ok &= step2_susfs_h()
    ok &= step3_susfs_c()
    ok &= step4_vfs_hooks()
    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()
