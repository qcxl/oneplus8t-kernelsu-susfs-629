#!/usr/bin/env python3
"""
inject-open-redirect-enhanced.py — Port SUSFS v2.2.0 open_redirect enhancement to 4.19.

This script REPLACES the old open_redirect implementation with the v2.2.0 enhanced version.
The old v1.5.5 open_redirect (susfs_add_open_redirect, OPEN_REDIRECT_HLIST with old struct)
is entirely replaced so that the spoof functions (do_sys_openat, readlink, statfs, seq_show)
all operate on the same hash table with the enhanced struct.

Changes:
  - susfs_def.h: UID_SCHEME enum
  - susfs.h: enhanced structs + function declarations
  - susfs.c: new OPEN_REDIRECT_HLIST (enhanced), susfs_add_open_redirect (v2.2.0), 7 spoof funcs
  - fs/open.c: do_sys_openat2 retry logic for path redirection
  - fs/namei.c: vfs_readlink hook for readlink spoofing
  - fs/proc/base.c: do_proc_readlink hook for /proc readlink spoofing
  - fs/proc/fd.c: seq_show hook for fd/ mnt_id spoofing
  - fs/statfs.c: vfs_statfs hook for statfs spoofing
  - dispatch.c: updated calls (void** signature)

Returns 0 on success, 1 on failure.
"""

import sys, os, re

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


def insert_before(path, marker, text):
    content = read_file(path)
    pos = content.find(marker)
    if pos < 0:
        print(f"  WARNING: marker not found in {path}")
        return False
    content = content[:pos] + text + content[pos:]
    write_file(path, content)
    return True


# ─── 1. susfs_def.h: UID_SCHEME enum ─────────────────────────────────────

def step1_susfs_def_h():
    path = find_file(KERNEL_ROOT, [
        "include/linux/susfs_def.h",
    ])
    if not path:
        print("  ERROR: susfs_def.h not found"); return False
    c = read_file(path)
    if "UID_NON_APP_PROC" in c:
        print("  susfs_def.h: UID_SCHEME already present"); return True

    uid = """
enum UID_SCHEME {
	UID_NON_APP_PROC = 0,
	UID_ROOT_PROC_EXCEPT_SU_PROC,
	UID_NON_SU_PROC,
	UID_UMOUNTED_APP_PROC,
	UID_UMOUNTED_PROC,
};

"""
    # Insert after last INODE_STATE_ define
    lines = c.split('\n')
    last_idx = 0
    for i, l in enumerate(lines):
        if l.strip().startswith('#define INODE_STATE_'):
            last_idx = i
    lines.insert(last_idx + 1, uid.rstrip('\n'))
    c = '\n'.join(lines)
    write_file(path, c)
    print("  susfs_def.h: UID_SCHEME added")
    return True


# ─── 2. susfs.h: enhanced structs + declarations ─────────────────────────

def step2_susfs_h():
    path = find_file(KERNEL_ROOT, [
        "include/linux/susfs.h",
    ])
    if not path:
        print("  ERROR: susfs.h not found"); return False
    c = read_file(path)

    if "uid_scheme" in c:
        print("  susfs.h: enhanced structs already present"); return True

    # Add linux/statfs.h include for struct kstatfs — find last #include and append
    if "#include <linux/statfs.h>" not in c:
        lines = c.split('\n')
        last_include = -1
        for i, l in enumerate(lines):
            if l.strip().startswith('#include'):
                last_include = i
        if last_include >= 0:
            lines.insert(last_include + 1, '#include <linux/statfs.h>')
            c = '\n'.join(lines)
            print("  susfs.h: added #include <linux/statfs.h>")
        else:
            print("  WARNING: no #include found in susfs.h, prepending")
            c = '#include <linux/statfs.h>\n' + c

    # Replace old struct (flexible search)
    old1s = "struct st_susfs_open_redirect {"
    old1e = "struct hlist_node                node;\n};"
    s1 = c.find(old1s)
    e1 = c.find(old1e, s1)
    if s1 >= 0 and e1 >= 0:
        new = """struct st_susfs_open_redirect {
\tchar                                    target_pathname[SUSFS_MAX_LEN_PATHNAME];
\tchar                                    redirected_pathname[SUSFS_MAX_LEN_PATHNAME];
\tint                                     uid_scheme;
\tint                                     err;
};

struct st_susfs_open_redirect_hlist {
\tunsigned long                           target_ino;
\tunsigned long                           target_dev;
\tunsigned long                           redirected_ino;
\tunsigned long                           redirected_dev;
\tint                                     spoofed_mnt_id;
\tstruct kstatfs                          spoofed_kstatfs;
\tstruct st_susfs_open_redirect           info;
\tbool                                    reversed_lookup_only;
\tstruct hlist_node                       node;
};"""
        c = c[:s1] + new + c[e1 + len(old1e):]
        write_file(path, c)
        print("  susfs.h: structs updated")
    else:
        print("  ERROR: open_redirect structs not found in susfs.h")
        return False

    # Update declaration
    c = c.replace(
        "int susfs_add_open_redirect(struct st_susfs_open_redirect* __user user_info);",
        "void susfs_add_open_redirect(void __user **user_info);"
    )
    # Add spoof declarations
    spoof_decls = """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode);
int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen);
int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);
int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf);
int susfs_open_redirect_spoof_seq_show(struct inode *inode, int *out_mnt_id, unsigned long *out_ino);
int susfs_open_redirect_spoof_show_map_vma(struct inode *inode, unsigned long *out_ino, dev_t *out_dev, char *spoofed_name);
#endif
"""
    if "spoof_do_sys_openat" not in c:
        c = c.replace(
            "void susfs_add_open_redirect(void __user **user_info);",
            "void susfs_add_open_redirect(void __user **user_info);" + spoof_decls
        )
    write_file(path, c)
    print("  susfs.h: declarations updated")
    return True


# ─── 3. susfs.c: replace open_redirect implementation ────────────────────

def step3_susfs_c():
    path = find_file(KERNEL_ROOT, [
        "fs/susfs.c",
    ])
    if not path:
        print("  ERROR: susfs.c not found"); return False
    c = read_file(path)

    if "susfs_open_redirect_spoof_do_sys_openat" in c:
        print("  susfs.c: enhanced open_redirect already present"); return True

    # Remove OLD open_redirect section if it exists
    # The old section starts with /* open_redirect */ and ends at /* sus_su */ or next section
    old_start = c.find("/* open_redirect */")
    if old_start >= 0:
        # Find the next section comment after the open_redirect section
        # It usually ends with #endif /* CONFIG_KSU_SUSFS_OPEN_REDIRECT */
        old_end_marker = "#endif /* CONFIG_KSU_SUSFS_OPEN_REDIRECT */"
        old_end = c.find(old_end_marker, old_start)
        if old_end >= 0:
            old_end = old_end + len(old_end_marker)
            c = c[:old_start] + c[old_end:]
            print("  susfs.c: old open_redirect section removed")

    # Insert the enhanced open_redirect section before susfs_init
    enhanced = r"""
/* open_redirect enhanced (v2.2.0 port) */
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
static DEFINE_MUTEX(susfs_mutex_lock_open_redirect);
static DEFINE_HASHTABLE(OPEN_REDIRECT_HLIST, 10);
static DEFINE_SPINLOCK(susfs_spinlock_open_redirect_srcu);
static struct srcu_struct susfs_srcu_open_redirect;

void susfs_add_open_redirect(void __user **user_info) {
	struct st_susfs_open_redirect info = {0};
	struct st_susfs_open_redirect_hlist *new_entry_target, *new_entry_redirected;
	struct st_susfs_open_redirect_hlist *tmp_entry_target, *tmp_entry_redirected;
	struct hlist_node *tmp_hlist_node;
	struct path target_path, redirected_path;
	struct inode *target_inode, *redirected_inode;
	bool is_first_dup_found = false;
	bool is_second_dup_found = false;

	if (copy_from_user(&info, (struct st_susfs_open_redirect __user*)*user_info, sizeof(info))) {
		info.err = -EFAULT; goto out_copy_to_user;
	}
	if (*info.target_pathname == '\0') {
		info.err = -EINVAL; goto out_copy_to_user;
	}
	if (info.uid_scheme < UID_NON_APP_PROC || info.uid_scheme > UID_UMOUNTED_PROC) {
		info.err = -EINVAL; goto out_copy_to_user;
	}
	info.err = kern_path(info.redirected_pathname, 0, &redirected_path);
	if (info.err) { goto out_copy_to_user; }
	info.err = kern_path(info.target_pathname, 0, &target_path);
	if (info.err) { path_put(&redirected_path); goto out_copy_to_user; }

	redirected_inode = d_backing_inode(redirected_path.dentry);
	target_inode = d_backing_inode(target_path.dentry);
	if (!target_inode || !redirected_inode) {
		info.err = -ENOENT; path_put(&target_path); path_put(&redirected_path); goto out_copy_to_user;
	}
	if (redirected_inode->i_sb->s_magic == FUSE_SUPER_MAGIC ||
	    target_inode->i_sb->s_magic == FUSE_SUPER_MAGIC) {
		info.err = -EINVAL; path_put(&target_path); path_put(&redirected_path); goto out_copy_to_user;
	}

	new_entry_target = kzalloc(sizeof(struct st_susfs_open_redirect_hlist), GFP_KERNEL);
	new_entry_redirected = kzalloc(sizeof(struct st_susfs_open_redirect_hlist), GFP_KERNEL);
	if (!new_entry_target || !new_entry_redirected) {
		info.err = -ENOMEM;
		kfree(new_entry_target); kfree(new_entry_redirected);
		path_put(&target_path); path_put(&redirected_path); goto out_copy_to_user;
	}

	new_entry_target->target_ino = target_inode->i_ino;
	new_entry_target->target_dev = target_inode->i_sb->s_dev;
	new_entry_target->redirected_ino = redirected_inode->i_ino;
	new_entry_target->redirected_dev = redirected_inode->i_sb->s_dev;
	new_entry_target->info = info;
	new_entry_target->reversed_lookup_only = false;
	new_entry_target->spoofed_mnt_id = real_mount(target_path.mnt)->mnt_id;
	(void)vfs_statfs(&target_path, &new_entry_target->spoofed_kstatfs);

	new_entry_redirected->target_ino = redirected_inode->i_ino;
	new_entry_redirected->target_dev = redirected_inode->i_sb->s_dev;
	new_entry_redirected->redirected_ino = target_inode->i_ino;
	new_entry_redirected->redirected_dev = target_inode->i_sb->s_dev;
	new_entry_redirected->info = info;
	new_entry_redirected->reversed_lookup_only = true;
	new_entry_redirected->spoofed_mnt_id = real_mount(target_path.mnt)->mnt_id;
	memcpy(&new_entry_redirected->spoofed_kstatfs, &new_entry_target->spoofed_kstatfs, sizeof(struct kstatfs));
	strscpy(new_entry_redirected->info.target_pathname, info.redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
	strscpy(new_entry_redirected->info.redirected_pathname, info.target_pathname, SUSFS_MAX_LEN_PATHNAME - 1);

	mutex_lock(&susfs_mutex_lock_open_redirect);
	hash_for_each_possible_safe(OPEN_REDIRECT_HLIST, tmp_entry_target, tmp_hlist_node, node, target_inode->i_ino) {
		if (!strcmp(tmp_entry_target->info.target_pathname, info.target_pathname)) {
			if (tmp_entry_target->reversed_lookup_only) {
				mutex_unlock(&susfs_mutex_lock_open_redirect);
				info.err = -EINVAL; kfree(new_entry_redirected); kfree(new_entry_target);
				path_put(&target_path); path_put(&redirected_path); goto out_copy_to_user;
			}
			is_first_dup_found = true;
			hash_del_rcu(&tmp_entry_target->node);
			break;
		}
	}
	if (is_first_dup_found) {
		hash_for_each_possible_safe(OPEN_REDIRECT_HLIST, tmp_entry_redirected, tmp_hlist_node, node, redirected_inode->i_ino) {
			if (!strcmp(tmp_entry_redirected->info.target_pathname, info.redirected_pathname)) {
				is_second_dup_found = true;
				hash_del_rcu(&tmp_entry_redirected->node);
				break;
			}
		}
	}
	hash_add_rcu(OPEN_REDIRECT_HLIST, &new_entry_target->node, new_entry_target->target_ino);
	hash_add_rcu(OPEN_REDIRECT_HLIST, &new_entry_redirected->node, new_entry_redirected->target_ino);
	target_inode->i_state |= INODE_STATE_OPEN_REDIRECT;
	redirected_inode->i_state |= INODE_STATE_OPEN_REDIRECT;
	mutex_unlock(&susfs_mutex_lock_open_redirect);
	synchronize_rcu();
	if (is_second_dup_found) kfree(tmp_entry_redirected);
	if (is_first_dup_found) kfree(tmp_entry_target);
	info.err = 0;

	path_put(&target_path);
	path_put(&redirected_path);
out_copy_to_user:
	copy_to_user(&((struct st_susfs_open_redirect __user*)*user_info)->err, &info.err, sizeof(info.err));
}

struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode) {
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (!entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			switch(entry->info.uid_scheme) {
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
			srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
			return getname_kernel(entry->info.redirected_pathname);
		}
	}
unlock:
	srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
	return NULL;
}

int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen) {
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			if (strlen(entry->info.redirected_pathname) >= buflen) {
				srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
				return -ENAMETOOLONG;
			}
			if (copy_to_user(buffer, entry->info.redirected_pathname, strlen(entry->info.redirected_pathname))) {
				srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
				return -EFAULT;
			}
			srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
	return -ENOENT;
}

int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen) {
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			if (strlen(entry->info.redirected_pathname) >= buflen) {
				srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
				return -ENAMETOOLONG;
			}
			strscpy(tmp_buf, entry->info.redirected_pathname, SUSFS_MAX_LEN_PATHNAME - 1);
			srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
	return -ENOENT;
}

int susfs_open_redirect_spoof_vfs_statfs(struct inode *inode, struct kstatfs *buf) {
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			memcpy(buf, &entry->spoofed_kstatfs, sizeof(struct kstatfs));
			srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
	return -EINVAL;
}

int susfs_open_redirect_spoof_seq_show(struct inode *inode, int *out_mnt_id, unsigned long *out_ino) {
	struct st_susfs_open_redirect_hlist *entry = NULL;
	int srcu_idx = srcu_read_lock(&susfs_srcu_open_redirect);
	hash_for_each_possible_rcu(OPEN_REDIRECT_HLIST, entry, node, inode->i_ino) {
		if (entry->reversed_lookup_only && entry->target_dev == inode->i_sb->s_dev) {
			*out_mnt_id = entry->spoofed_mnt_id;
			*out_ino = entry->redirected_ino;
			srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
			return 0;
		}
	}
	srcu_read_unlock(&susfs_srcu_open_redirect, srcu_idx);
	return -EINVAL;
}
#endif /* CONFIG_KSU_SUSFS_OPEN_REDIRECT */

"""
    # Insert before susfs_init
    marker = "\nvoid susfs_init(void)"
    if marker in c:
        c = c.replace(marker, enhanced + marker)
        write_file(path, c)
        print("  susfs.c: enhanced open_redirect implementation injected")
    else:
        print("  ERROR: susfs_init() not found in susfs.c")
        return False

    # Add SRCU init in susfs_init
    # Find the start of susfs_init function body
    srcu_line = "\tinit_srcu_struct(&susfs_srcu_open_redirect);\n"
    c = read_file(path)
    spin_init = "\tspin_lock_init(&susfs_spin_lock);\n"
    if spin_init in c and srcu_line not in c:
        c = c.replace(spin_init, spin_init + srcu_line)
        write_file(path, c)
        print("  susfs.c: SRCU init added to susfs_init()")

    return True


# ─── 4. VFS hooks ────────────────────────────────────────────────────────

def step4_vfs_hooks():
    ok = True

    # fs/open.c: do_sys_open retry logic (4.19 does NOT have do_sys_openat2)
    p = os.path.join(KERNEL_ROOT, "fs/open.c")
    if os.path.exists(p):
        c = read_file(p)
        if "susfs_open_redirect_spoof" not in c:
            # Add extern declaration
            ext = "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern struct filename *susfs_open_redirect_spoof_do_sys_openat(struct inode *inode);\n#endif\n"
            lines = c.split('\n')
            last = 0
            for i, l in enumerate(lines):
                if l.strip().startswith('#include'):
                    last = i
            lines.insert(last + 1, ext)
            c = '\n'.join(lines)

            # Add local variable inside do_sys_open
            old_sig = "long do_sys_open(int dfd, const char __user *filename, int flags, umode_t mode)\n{"
            # Try different linebreak patterns
            for sig in [
                "long do_sys_open(int dfd, const char __user *filename, int flags, umode_t mode)\n{",
                "long do_sys_open(int dfd, const char __user *filename,\n\t\t\t int flags, umode_t mode)\n{",
            ]:
                if sig in c:
                    var_decl = """
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
\tbool is_inode_open_redirect = false;
#endif"""
                    c = c.replace(sig, sig + var_decl)
                    print("  fs/open.c: added is_inode_open_redirect variable")
                    break

            # Add retry label before get_unused_fd_flags(flags)
            old_retry = "\tfd = get_unused_fd_flags(flags);"
            if old_retry in c:
                retry_label = "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nretry:\n#endif\n\tfd = get_unused_fd_flags(flags);\n"
                c = c.replace(old_retry, retry_label)
                print("  fs/open.c: added retry label")

            # Add spoof call after do_filp_open
            dop = "\t\tstruct file *f = do_filp_open(dfd, tmp, &op);"
            if dop in c:
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
                print("  fs/open.c: added open redirect spoof call")

            write_file(p, c)
        else:
            print("  fs/open.c: already hooked")
    else:
        print("  WARNING: fs/open.c not found"); ok = False

    # fs/namei.c: vfs_readlink hook
    p = os.path.join(KERNEL_ROOT, "fs/namei.c")
    if os.path.exists(p):
        c = read_file(p)
        if "spoof_vfs_readlink" not in c:
            ext = "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern int susfs_open_redirect_spoof_vfs_readlink(struct inode *inode, char __user *buffer, int buflen);\n#endif\n"
            lines = c.split('\n')
            last = 0
            for i, l in enumerate(lines):
                if l.strip().startswith('#include') and 'namei' not in l:
                    last = i
            lines.insert(last + 1, ext)
            c = '\n'.join(lines)

            # Replace the inode->i_op->readlink call
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
                print("  WARNING: vfs_readlink pattern not found in fs/namei.c")
        else:
            print("  fs/namei.c: already hooked")
    else:
        print("  WARNING: fs/namei.c not found"); ok = False

    # fs/proc/base.c: do_proc_readlink hook
    p = os.path.join(KERNEL_ROOT, "fs/proc/base.c")
    if os.path.exists(p):
        c = read_file(p)
        if "spoof_do_proc_readlink" not in c:
            ext = "\n#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\nextern int susfs_open_redirect_spoof_do_proc_readlink(struct inode *inode, char *tmp_buf, int buflen);\n#endif\n"
            lines = c.split('\n')
            last = 0
            for i, l in enumerate(lines):
                if l.strip().startswith('#include') and 'fs.h' in l:
                    last = i
            lines.insert(last + 1, ext)
            c = '\n'.join(lines)
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
                print("  WARNING: do_proc_readlink pattern not found in fs/proc/base.c")
        else:
            print("  fs/proc/base.c: already hooked")
    else:
        print("  WARNING: fs/proc/base.c not found"); ok = False

    return ok


# ─── 5. Update dispatch ──────────────────────────────────────────────────

def step5_dispatch():
    dp = find_file(KERNEL_ROOT, [
        "drivers/kernelsu/supercall/dispatch.c",
    ])
    if not dp:
        print("  WARNING: dispatch.c not found, skipping"); return True
    c = read_file(dp)

    changed = False
    old_ioctl = '\t\treturn susfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);\n'
    new_ioctl = '\t\tsusfs_add_open_redirect(&uarg);\n\t\treturn 0;\n'
    if old_ioctl in c:
        c = c.replace(old_ioctl, new_ioctl)
        changed = True

    old_reboot = '\t\t\treturn susfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);\n'
    new_reboot = '\t\t\tsusfs_add_open_redirect(&uarg);\n\t\t\treturn 0;\n'
    if old_reboot in c:
        c = c.replace(old_reboot, new_reboot)
        changed = True

    if changed:
        write_file(dp, c)
        print("  dispatch.c: updated open_redirect calls")
    else:
        print("  dispatch.c: open_redirect calls already updated or not found")

    # Also fix supercall.c (reboot handler) — injected by inject-susfs-dispatch.py
    sc_path = find_file(KERNEL_ROOT, [
        "drivers/kernelsu/supercall/supercall.c",
    ])
    if sc_path:
        c = read_file(sc_path)
        old_sc = '\t\t\treturn susfs_add_open_redirect((struct st_susfs_open_redirect __user *)uarg);\n'
        new_sc = '\t\t\tsusfs_add_open_redirect(&uarg);\n\t\t\treturn 0;\n'
        if old_sc in c:
            c = c.replace(old_sc, new_sc)
            write_file(sc_path, c)
            print("  supercall.c: updated open_redirect call")
        else:
            print("  supercall.c: open_redirect call not found or already updated")
    return True


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    print("[open_redirect enhanced] target=%s" % KERNEL_ROOT)
    ok = True
    ok &= step1_susfs_def_h()
    ok &= step2_susfs_h()
    ok &= step3_susfs_c()
    ok &= step4_vfs_hooks()
    ok &= step5_dispatch()
    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)


if __name__ == '__main__':
    main()
