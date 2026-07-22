# 内核级 SUSFS 规则自动恢复方案

> 版本: 1.0
> 目标: 冷启动/工厂重置后自动恢复 SUSFS 规则和属性伪装，零依赖用户态

---

## 1. 问题概述

### 1.1 当前架构缺陷

```
init.rc exec → /data/adb/ksud post-fs-data  ← 由于 init.rc 注入被解析器忽略而失败
                    ↓
            restore_if_needed()  ← 从未执行
                    ↓
            SUSFS 规则未应用 → Momo 检测出 su/挂载/属性异常
```

### 1.2 根因

KSU-Next 的 `read_iter_proxy` 注入的 375 字节 KERNEL_SU_RC 被 Android 13 LineageOS init 解析器忽略。4 个注入的 `on <trigger>` 段均未被执行。

### 1.3 解决思路

从内核的 `on_post_fs_data()`（zygote exec 钩子触发）直接调用 SUSFS 内部函数操作内核数据结构，同时直接操作 Android 属性共享内存。完全跳过用户态。

---

## 2. 架构总览

### 2.1 触发时序

```
系统启动
  │
  ├─ kernelsu_init() ← SUSFS + KSU 内核模块加载
  │
  ├─ init second_stage → apply_kernelsu_rules(), setup_ksu_cred()
  │
  ├─ /data 挂载完成 → post-fs-data 触发
  │     └─ init.rc exec → /data/adb/ksud ← 损坏路径，忽略
  │
  ├─ app_process -Xzygote ← 新增：★ SUSFS 内核恢复在此触发
  │     └─ on_post_fs_data()
  │           ├─ apply_kernelsu_rules()      ← 原有
  │           ├─ ksu_load_allow_list()        ← 原有
  │           └─ susfs_restore_boot()         ← 新增
  │                 ├─ susfs_add_path("/system/bin/su")
  │                 ├─ susfs_add_path("/odm/bin/su")
  │                 ├─ susfs_add_mount("/vendor")
  │                 ├─ susfs_hide_mnts(true)
  │                 ├─ susfs_avc_spoof(true)
  │                 └─ susfs_restore_properties()
  │                       ├─ 找到属性共享内存
  │                       ├─ ro.build.type="user"
  │                       ├─ ro.debuggable="0"
  │                       └─ ro.lineage.version ← 删除
  │
  └─ 系统启动完成 → Momo 检测 → ✅ 全部通过
```

### 2.2 修改清单

| 文件 | 操作 | 行数 |
|------|------|:----:|
| `kernel-patches/fs/susfs.c` | 新增内核安全 SUSFS 调用函数 | +35 |
| `kernel-patches/include/linux/susfs.h` | 声明新函数 | +12 |
| `kernel/runtime/boot_event.c` | `on_post_fs_data()` 末尾追加调用 | +5 |
| **`kernel/runtime/properties.c` (新)** | 属性共享内存直接操作 | +90 |
| `kernel/runtime/Kbuild` (或主 Kbuild) | 添加 `properties.o` | +1 |
| CI 工作流 | 无修改（不需 ramdisk 二进制注入） | 0 |

**总计：约 143 行内核 C 代码**，零用户态修改。

---

### 2.3 Kbuild 修改

在 `kernelsu-next-src/kernel/Kbuild` 末尾追加：

```makefile
kernelsu-objs += properties.o
```

---

## 3. 详细实现

### 3.1 `susfs.c` — 新增内核安全函数  

新增函数绕过 `copy_from_user` 直接操作内核数据结构。

#### 3.1.1 修改受保护的 static 函数

将 `susfs_update_sus_path_inode()` 从 `static` 改为非 `static`，使其可被 boot_event.c 调用（或其他文件在编译期引用）：

```c
// 修改前: 第 38 行
static int susfs_update_sus_path_inode(char *target_pathname, unsigned long *target_ino_out) {

// 修改后:
int susfs_update_sus_path_inode(char *target_pathname, unsigned long *target_ino_out) {
```

类似地，`susfs_update_sus_mount_inode()` 也从 `static` 改为非 `static`：

```c
// 修改前: 第 149 行
static void susfs_update_sus_mount_inode(char *target_pathname) {
```

#### 3.1.2 新增 `susfs_add_sus_path_kernel()`

```c
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
/* 内核安全版：参数为内核空间字符串，跳过 copy_from_user */
int susfs_add_sus_path_kernel(const char *path)
{
    struct st_susfs_sus_path_hlist *new_entry, *tmp_entry;
    struct hlist_node *tmp_node;
    int bkt;

    new_entry = kmalloc(sizeof(struct st_susfs_sus_path_hlist), GFP_KERNEL);
    if (!new_entry)
        return -ENOMEM;

    strncpy(new_entry->target_pathname, path, SUSFS_MAX_LEN_PATHNAME - 1);
    new_entry->target_pathname[SUSFS_MAX_LEN_PATHNAME - 1] = '\0';

    if (susfs_update_sus_path_inode(new_entry->target_pathname, &new_entry->target_ino)) {
        kfree(new_entry);
        return -ENOENT;
    }

    spin_lock(&susfs_spin_lock);
    hash_for_each_safe(SUS_PATH_HLIST, bkt, tmp_node, tmp_entry, node) {
        if (!strcmp(tmp_entry->target_pathname, new_entry->target_pathname)) {
            hash_del(&tmp_entry->node);
            kfree(tmp_entry);
            break;
        }
    }
    hash_add(SUS_PATH_HLIST, &new_entry->node, new_entry->target_ino);
    spin_unlock(&susfs_spin_lock);

    SUSFS_LOGI("boot restore: added sus_path '%s' (ino=%lu)\n",
               new_entry->target_pathname, new_entry->target_ino);
    return 0;
}
#endif
```

#### 3.1.3 新增 `susfs_add_sus_mount_kernel()`

```c
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
int susfs_add_sus_mount_kernel(const char *path)
{
    struct st_susfs_sus_mount_list *cursor, *temp;
    struct st_susfs_sus_mount_list *new_list;

    list_for_each_entry_safe(cursor, temp, &LH_SUS_MOUNT, list) {
        if (!strcmp(cursor->info.target_pathname, path))
            return 0; /* already exists */
    }

    new_list = kmalloc(sizeof(struct st_susfs_sus_mount_list), GFP_KERNEL);
    if (!new_list)
        return -ENOMEM;

    strncpy(new_list->info.target_pathname, path, SUSFS_MAX_LEN_PATHNAME - 1);
    new_list->info.target_pathname[SUSFS_MAX_LEN_PATHNAME - 1] = '\0';
    new_list->info.target_dev = 0;
    susfs_update_sus_mount_inode(new_list->info.target_pathname);

    INIT_LIST_HEAD(&new_list->list);
    spin_lock(&susfs_spin_lock);
    list_add_tail(&new_list->list, &LH_SUS_MOUNT);
    spin_unlock(&susfs_spin_lock);

    SUSFS_LOGI("boot restore: added sus_mount '%s'\n", path);
    return 0;
}
#endif
```

#### 3.1.4 新增 `susfs_add_sus_map_kernel()`

```c
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
int susfs_add_sus_map_kernel(const char *path)
{
    struct path p;
    struct inode *inode;
    int err;

    err = kern_path(path, 0, &p);
    if (err) {
        SUSFS_LOGE("boot restore: sus_map path '%s' not found\n", path);
        return err;
    }

    inode = d_inode(p.dentry);
    spin_lock(&inode->i_lock);
    inode->i_state |= INODE_STATE_SUS_MAP;
    spin_unlock(&inode->i_lock);
    path_put(&p);

    SUSFS_LOGI("boot restore: added sus_map '%s'\n", path);
    return 0;
}
#endif
```

#### 3.1.5 新增 `susfs_set_uname_kernel()`

```c
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
int susfs_set_uname_kernel(const char *release, const char *version)
{
    spin_lock(&susfs_uname_spin_lock);
    strncpy(my_uname.release, release, __NEW_UTS_LEN);
    strncpy(my_uname.version, version, __NEW_UTS_LEN);
    spin_unlock(&susfs_uname_spin_lock);

    SUSFS_LOGI("boot restore: uname release='%s' version='%s'\n", release, version);
    return 0;
}
#endif
```

#### 3.1.6 `susfs.h` — 新增声明

在 `susfs.h` 末尾（或在对应 `#ifdef` 块中添加）：

```c
/* Kernel-safe boot restore functions (no __user pointers) */
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
int susfs_add_sus_path_kernel(const char *path);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
int susfs_add_sus_mount_kernel(const char *path);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
int susfs_add_sus_map_kernel(const char *path);
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
int susfs_set_uname_kernel(const char *release, const char *version);
#endif
/* Hide mount toggle backing variable (defined in susfs.c) */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
extern bool susfs_hide_sus_mnts_for_all_procs __read_mostly;
#endif
/* AVC log spoofing toggle backing variable (defined in susfs.c) */
#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING
extern bool susfs_is_avc_log_spoofing_enabled __read_mostly;
#endif
```

#### 3.1.7 修改 static → 非 static

```c
// susfs.c 第 38 行: static int susfs_update_sus_path_inode(...)
// 改为:
int susfs_update_sus_path_inode(char *target_pathname, unsigned long *target_ino_out);

// susfs.c 第 149 行: static void susfs_update_sus_mount_inode(...)
// 改为:
void susfs_update_sus_mount_inode(char *target_pathname);
```

同时在 `susfs.h` 中添加：

```c
/* Internal helpers (used by kernel boot restore) */
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
int susfs_update_sus_path_inode(char *target_pathname, unsigned long *target_ino_out);
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
void susfs_update_sus_mount_inode(char *target_pathname);
#endif
```

### 3.2 `properties.c` — 属性共享内存操作（新文件）

#### 3.2.1 数据结构定义

源于 AOSP `bionic/libc/system_properties/`（自 Android 8 起稳定，KSU-Next 的 `prop-rs-android` crates 已验证）：

```c
// SPDX-License-Identifier: GPL-2.0-only
/*
 * properties.c - Direct property shared memory manipulation for boot restore
 *
 * Reads the Android property trie from init's shared memory and sets
 * ro.* properties that cannot be set via setprop (once-only restriction).
 */

#include <linux/fs.h>
#include <linux/fdtable.h>
#include <linux/file.h>
#include <linux/mm.h>
#include <linux/string.h>
#include <linux/sched.h>
#include <linux/atomic.h>
#include <linux/printk.h>

/* ---------- Property Area Structures (bionic ABI stable since Android 8) ---------- */

#define PROP_AREA_MAGIC     0x504F5250   /* "PROP" in little-endian */
#define PROP_AREA_VERSION   0xFC6ED0AB
#define PROP_NAME_MAX       32
#define PROP_VALUE_MAX      92
#define PROP_AREA_HEADER_SZ 128
#define PROP_TRIE_NODE_SZ   20

/* prop_area header: 128 bytes at file offset 0 */
struct prop_area {
    uint32_t bytes_used;
    uint32_t serial;
    uint32_t magic;        /* must be PROP_AREA_MAGIC */
    uint32_t version;      /* must be PROP_AREA_VERSION */
    uint32_t reserved[28];
    /* uint8_t data[] follows */
};

/* Trie node header: 20 bytes + variable-length name */
struct prop_trie_node {
    uint32_t namelen;
    uint32_t prop;         /* offset to prop_info, or 0 if no property */
    uint32_t left;
    uint32_t right;
    uint32_t children;
    /* char name[] follows (namelen bytes, no NUL, 4-byte aligned) */
};

/* Property info: 96 bytes + variable-length name */
struct prop_info {
    uint32_t serial;
    char     value[PROP_VALUE_MAX];
    /* char name[] follows */
};

/* ---------- Property Trie Walker (taken from prop-rs-android) ---------- */

/*
 * Property name comparison: LENGTH FIRST, then byte comparison.
 * This matches bionic's cmp_prop_name().
 */
static int prop_name_cmp(const char *key, int key_len,
                         const char *node_name, int node_len)
{
    if (key_len < node_len) return -1;
    if (key_len > node_len) return  1;
    return memcmp(key, node_name, key_len);
}

/*
 * Walk the binary trie to find a property.
 * @data: pointer to prop_area->data (after 128-byte header)
 * @key: property name (e.g. "ro.build.type")
 * @out_info: (output) pointer to prop_info if found
 * Returns 0 on success, -ENOENT if not found.
 */
static int prop_trie_find(uint8_t *data, const char *key,
                          struct prop_info **out_info)
{
    char buf[PROP_NAME_MAX];
    int key_len = strlen(key);
    int seg_start = 0, seg_end;
    uint32_t offset = 0; /* start at root node */

    while (offset > 0 || seg_start == 0) {
        if (seg_start >= key_len)
            return -ENOENT; /* consumed all segments, no property */

        /* Find next '.' separator */
        seg_end = seg_start;
        while (seg_end < key_len && key[seg_end] != '.')
            seg_end++;

        int seg_len = seg_end - seg_start;
        memcpy(buf, key + seg_start, seg_len);
        buf[seg_len] = '\0';

        /* Navigate to children (offset relative to data) */
        if (offset == 0) {
            /* Root node is always at data[0] */
            offset = 0;
        } else {
            /* Move to children of current node */
            struct prop_trie_node *node = (struct prop_trie_node *)(data + offset);
            offset = node->children;
            if (offset == 0)
                return -ENOENT;
        }

        /* Binary search among siblings (BST sorted by length+bytes) */
        while (offset) {
            struct prop_trie_node *node = (struct prop_trie_node *)(data + offset);
            int node_name_len = node->namelen;
            /* Name is stored after the 20-byte header, 4-byte aligned */
            uint8_t *node_name = data + offset + PROP_TRIE_NODE_SZ;
            int cmp = prop_name_cmp(buf, seg_len,
                                    (const char *)node_name, node_name_len);

            if (cmp == 0) {
                /* Found matching segment */
                if (seg_end >= key_len) {
                    /* This is the final segment — check for property */
                    if (node->prop) {
                        *out_info = (struct prop_info *)(data + node->prop);
                        return 0;
                    }
                    return -ENOENT; /* node exists but no property value */
                }
                /* More segments remain — go to children next iteration */
                break;
            } else if (cmp < 0) {
                offset = node->left;
            } else {
                offset = node->right;
            }
        }

        seg_start = seg_end + 1; /* skip '.' */
    }

    return -ENOENT;
}

/* ---------- Property Area Discovery ---------- */

/*
 * Find init's property area shared memory file.
 * Scans PID 1's fd table for files with "__properties__" in their name.
 * Returns the file object (with refcount held) or NULL.
 *
 * In modern Android (10+), init creates a memfd named "__properties__"
 * that is mmap'd for the property trie. Each process carries this fd
 * through inheritance.
 */
static struct file *find_property_area_file(void)
{
    struct task_struct *tsk;
    struct file *result = NULL;
    int fd;

    tsk = get_pid_task(find_get_pid(1), PIDTYPE_PID);
    if (!tsk)
        return NULL;

    task_lock(tsk);
    if (!tsk->files)
        goto out_unlock_task;

    spin_lock(&tsk->files->file_lock);
    for (fd = 0; fd < files_fdtable(tsk->files)->max_fds; fd++) {
        struct file *f = files_fdtable(tsk->files)->fd[fd];
        if (!f) continue;

        /* Check backing path for "__properties__" (d_path needs buffer) */
        char path_buf[256];
        char *path = d_path(&f->f_path, path_buf, sizeof(path_buf));
        if (!IS_ERR(path) && strstr(path, "__properties__")) {
            get_file(f);
            result = f;
            spin_unlock(&tsk->files->file_lock);
            goto out_unlock_task;
        }
    }
    spin_unlock(&tsk->files->file_lock);

out_unlock_task:
    task_unlock(tsk);
    put_task_struct(tsk);
    return result;
}

/* ---------- Property Manipulation ---------- */

/*
 * Set a property value by directly writing to the shared memory trie.
 * Supports ro.* properties (bypasses init's once-only restriction).
 */
int prop_set(const char *key, const char *value)
{
    struct file *fp;
    struct prop_area header;
    loff_t pos = 0;
    uint8_t *page = NULL;
    struct prop_info *info;
    int ret = -ENOENT;
    size_t page_size;

    /* Find the property area file from init's fd table */
    fp = find_property_area_file();
    if (!fp) {
        pr_err("susfs: property area not found\n");
        return -ENOENT;
    }

    /* Read header (128 bytes at offset 0) */
    pos = 0;
    kernel_read(fp, &header, sizeof(header), &pos);

    if (header.magic != PROP_AREA_MAGIC) {
        pr_err("susfs: property area magic mismatch (got 0x%x)\n", header.magic);
        fput(fp);
        return -EINVAL;
    }

    /* Read entire property area into kernel memory for trie walking */
    page_size = header.bytes_used + PROP_AREA_HEADER_SZ;
    page = kzalloc(page_size, GFP_KERNEL);
    if (!page) {
        fput(fp);
        return -ENOMEM;
    }

    pos = 0;
    kernel_read(fp, page, page_size, &pos);

    /* Walk trie to find the property */
    ret = prop_trie_find(page + PROP_AREA_HEADER_SZ, key, &info);
    if (ret) {
        pr_warn("susfs: property '%s' not found in trie\n", key);
        goto out;
    }

    /* Overwrite the value directly in shared memory */
    {
        loff_t info_off = (uint8_t *)info - page;
        int vlen = strlen(value);
        if (vlen >= PROP_VALUE_MAX)
            vlen = PROP_VALUE_MAX - 1;

        /* Write the new value */
        pos = info_off + offsetof(struct prop_info, value);
        kernel_write(fp, value, vlen, &pos);

        /* Write NUL terminator */
        pos = info_off + offsetof(struct prop_info, value) + vlen;
        kernel_write(fp, "\0", 1, &pos);

        /* Bump serial number to notify readers */
        {
            uint32_t new_serial = info->serial + 1;
            pos = info_off + offsetof(struct prop_info, serial);
            kernel_write(fp, &new_serial, sizeof(new_serial), &pos);
        }

        pr_info("susfs: boot restore property '%s' = '%s'\n", key, value);
        ret = 0;
    }

out:
    kfree(page);
    fput(fp);
    return ret;
}

/*
 * Delete a property by setting its value to empty and clearing name.
 * After this, __system_property_find() will not return this entry
 * (name[0] = '\0' acts as sentinel for "deleted" in bionic).
 *
 * Equivalent to: resetprop -d <key>
 */
int prop_delete(const char *key)
{
    struct file *fp;
    struct prop_area header;
    loff_t pos = 0;
    uint8_t *page = NULL;
    struct prop_info *info;
    int ret = -ENOENT;
    size_t page_size;

    fp = find_property_area_file();
    if (!fp)
        return -ENOENT;

    kernel_read(fp, &header, sizeof(header), &pos);

    if (header.magic != PROP_AREA_MAGIC) {
        fput(fp);
        return -EINVAL;
    }

    page_size = header.bytes_used + PROP_AREA_HEADER_SZ;
    page = kzalloc(page_size, GFP_KERNEL);
    if (!page) {
        fput(fp);
        return -ENOMEM;
    }

    pos = 0;
    kernel_read(fp, page, page_size, &pos);

    ret = prop_trie_find(page + PROP_AREA_HEADER_SZ, key, &info);
    if (ret)
        goto out;

    loff_t info_off = (uint8_t *)info - page;

    /* Zero out name's first byte → marks deleted in bionic lookup */
    pos = info_off + sizeof(struct prop_info); /* name comes after 96-byte header */
    {
        char nul = '\0';
        kernel_write(fp, &nul, 1, &pos);
    }

    /* Also zero the value to clear residual data */
    pos = info_off + offsetof(struct prop_info, value);
    {
        char nul = '\0';
        kernel_write(fp, &nul, 1, &pos);
    }

    /* Bump serial to notify readers of change */
    pos = info_off + offsetof(struct prop_info, serial);
    {
        uint32_t new_serial = (info->serial & ~1U) + 2; /* skip dirty bit */
        kernel_write(fp, &new_serial, sizeof(new_serial), &pos);
    }

    pr_info("susfs: boot restore deleted property '%s'\n", key);
    ret = 0;

out:
    kfree(page);
    fput(fp);
    return ret;
}

void susfs_restore_properties(void)
{
    const char *props[][2] = {
        { "ro.build.type",        "user" },
        { "ro.build.flavor",      "OnePlus8T-user" },
        { "ro.build.display.id",  "RKQ1.211119.001" },
        { "ro.debuggable",        "0" },
        { "ro.build.user",        "jenkins" },
        { "ro.build.host",        "rd-build-193" },
        { NULL, NULL },
    };
    const char *del_props[] = {
        "ro.lineage.version",
        "ro.lineage.build.version",
        "ro.lineage.build.version.plat.rev",
        "ro.lineage.build.version.plat.sdk",
        "ro.lineage.device",
        "ro.lineage.display.version",
        "ro.lineage.releasetype",
        "ro.lineagelegal.url",
        "ro.modversion",
        NULL,
    };

    for (int i = 0; props[i][0]; i++)
        prop_set(props[i][0], props[i][1]);

    for (int i = 0; del_props[i]; i++)
        prop_delete(del_props[i]);
}
```

### 3.3 `boot_event.c` — 入口函数

在 `on_post_fs_data()` 末尾追加 `susfs_restore_boot()` 调用：

```c
#include <linux/susfs.h>  /* for SUSFS kernel-safe functions */

/* Forward declarations for property manipulation */
extern void susfs_restore_properties(void);

void on_post_fs_data(void)
{
    static bool done = false;
    if (done) return;
    done = true;

    /* --- 原有逻辑 -- */
    apply_kernelsu_rules();
    cache_sid();
    setup_ksu_cred();
    ksu_load_allow_list();
    ksu_observer_init();
    ksu_stop_input_hook_runtime();
    ksu_selinux_hide_handle_post_fs_data();

    /* --- 新增: SUSFS 启动恢复 --- */
    susfs_restore_boot();
}

/* 新增: 统一入口，集中定义所有需要恢复的规则 */
static void susfs_restore_boot(void)
{
    /* === SUSFS 路径隐藏 (直接操作哈希表) === */
    const char *sus_paths[] = {
        "/system/bin/su",
        "/odm/bin/su",
        "/data/adb/ksu/su",
        "/system/addon.d",
        "/system/build.prop",
        NULL,
    };
    for (int i = 0; sus_paths[i]; i++)
        susfs_add_sus_path_kernel(sus_paths[i]);

    /* === SUSFS 映射隐藏 (标记 inode) === */
    const char *sus_maps[] = {
        "/data/adb/",
        NULL,
    };
    for (int i = 0; sus_maps[i]; i++)
        susfs_add_sus_map_kernel(sus_maps[i]);

    /* === SUSFS 挂载点隐藏 (直接操作链表) === */
    const char *sus_mounts[] = {
        "/vendor",
        "/odm",
        NULL,
    };
    for (int i = 0; sus_mounts[i]; i++)
        susfs_add_sus_mount_kernel(sus_mounts[i]);

    /* === UNAME 伪装 === */
    susfs_set_uname_kernel("4.19.304", "Default/4.19");

    /* === 开关 === */
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
    WRITE_ONCE(susfs_hide_sus_mnts_for_all_procs, true);
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_AVC_LOG_SPOOFING
    WRITE_ONCE(susfs_is_avc_log_spoofing_enabled, true);
#endif

    /* === Android 属性伪装 (直接写共享内存) === */
    susfs_restore_properties();

    pr_info("susfs: boot restore complete\n");
}
```

---

## 4. 边界条件分析

### 4.1 重复执行保护

`on_post_fs_data()` 内有 `static bool done` 保护，确保 `susfs_restore_boot()` 在每次冷启动中只执行一次。

### 4.2 路径不存在

`susfs_add_sus_path_kernel()` 内 `kern_path()` 返回错误 → 函数返回负 errno 但不 panic。其他路径继续执行。

### 4.3 SUSFS 功能未编译

所有调用在 `#ifdef CONFIG_KSU_SUSFS_*` 保护内。若对应功能未启用，函数为空 stub（由 `susfs_stubs.c` 提供），调用无效果。

### 4.4 属性共享内存未就绪

- `find_property_area_file()` 返回 NULL → `prop_set()` 返回 `-ENOENT`
- 内核日志记录警告，系统正常启动
- 此时属性系统尚未初始化（极少可能，因为 zygote 在 post-fs-data 后启动）

### 4.5 属性名不存在于 trie 中

`prop_trie_find()` 返回 `-ENOENT` → 跳过该属性，不影响其他

### 4.6 内存分配失败

- `kzalloc(page_size, ...)` 返回 NULL → 跳过属性恢复
- `kmalloc(sizeof(struct st_susfs_sus_path_hlist), ...)` 返回 NULL → 跳过该路径
- 内核日志记录 OOM

### 4.7 工厂重置（格式化 /data）

不涉及任何 `/data` 上的文件 → 完全不受影响 ✅

### 4.8 /ksud ramdisk 不存在或不匹配

不涉及任何可执行文件 → 完全不受影响 ✅

---

## 5. 与现有 KSU App 功能的关系

| KSU App 功能 | 影响 |
|:-------------|:-----|
| 超级用户（root 授权） | 无影响 |
| 模块管理 | 无影响 |
| 配置文件管理 | 无影响 |
| SUSFS 规则管理（ksud CLI） | ✅ **增强** — 用户通过 `ksud susfs add-sus-path` 新增规则后，重启时内核 restore 使用内置默认规则+用户规则叠加（JSON config 仍可被 ksud 后续覆盖） |

> **注意**：内核 restore 设置的是 DEFAULT 内置规则。用户通过 `ksud susfs add-sus-path` 自定义的额外规则写入 JSON 文件。在用户态的 `restore_if_needed()` 被触发后（通过 Manager App 或其他机制），用户自定义规则会叠加到内核默认规则之上。

---

## 6. 验证方法

### 6.1 编译验证

```bash
# 确认新函数编译无警告
make -j$(nproc) 2>&1 | grep -E 'error|warning' | grep -v 'unused' || echo "PASS"

# 确认符号链接
nm vmlinux | grep susfs_restore_boot   # 必须存在
nm vmlinux | grep prop_trie_find       # 必须存在
```

### 6.2 刷机后验证

```bash
# 1. 确认内核 restore 触发
adb shell dmesg | grep "susfs: boot restore"

# 2. 确认路径隐藏
adb shell test -f /system/bin/su && echo "FAIL" || echo "PASS"
adb shell test -f /odm/bin/su && echo "FAIL" || echo "PASS"

# 3. 确认挂载隐藏
adb shell cat /proc/self/mountinfo | grep overlay | wc -l
# 期望: 0

# 4. 确认属性伪装
adb shell getprop ro.build.type       # 期望: user
adb shell getprop ro.debuggable       # 期望: 0
adb shell getprop ro.build.flavor     # 期望: OnePlus8T-user

# 5. 确认属性删除
adb shell getprop ro.lineage.version  # 期望: 空（不存在）

# 6. 确认 uname 伪装
adb shell uname -r                    # 期望: 4.19.304

# 7. Momo 测试
# 所有 4 项检测应通过
```

### 6.3 工厂重置验证

```bash
# 通过 recovery 格式化 /data
fastboot format userdata
fastboot reboot

# 验证所有规则仍生效（无需手动 push ksud）
adb shell dmesg | grep "susfs: boot restore"
adb shell test -f /system/bin/su && echo "FAIL" || echo "PASS"
```
