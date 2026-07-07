#!/usr/bin/env python3
"""
inject-adb-root.py — 移植 adb_root 到 legacy 4.19
"""

import sys, os, shutil

KERNEL_ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
KSU = os.path.join(KERNEL_ROOT, "drivers/kernelsu")
KBUILD = os.path.join(KSU, "Kbuild")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
PATCH_DIR = os.path.join(REPO_ROOT, "kernel-patches")

SCRIPT_MARK = "/* KSU_ADB_ROOT_INJECTED */"

FILES = [
    ("feature/adb_root.h", "feature/adb_root.h"),
    ("feature/adb_root.c", "feature/adb_root.c"),
]

ESCAPE_TO_ROOT = """
/* KSU_ADB_ROOT_INJECTED */
void escape_to_root_for_adb_root(void)
{
\tstruct cred *cred = prepare_creds();
\tif (!cred) {
\t\tpr_err("Failed to prepare adbd's creds!\\n");
\t\treturn;
\t}
\t/* Note: 4.19 legacy transive_to_domain now takes 3 args (commit 430a739) */
\tif (transive_to_domain(KERNEL_SU_CONTEXT, cred, true)) {
\t\tpr_err("transive domain failed.\\n");
\t\tabort_creds(cred);
\t\treturn;
\t}
\tcommit_creds(cred);
}
"""

def inject(filepath, anchor, snippet, after=True):
    if not os.path.exists(filepath):
        print(f"  ERROR: {filepath} not found"); return False
    with open(filepath) as f: c = f.read()
    if SCRIPT_MARK in c: print(f"  SKIP: {filepath} already injected"); return True
    if anchor not in c: print(f"  ERROR: anchor not found in {filepath}"); return False
    block = "\n" + snippet.strip() + "\n"
    c = c.replace(anchor, (anchor + block) if after else (block + anchor), 1)
    with open(filepath, 'w') as f: f.write(c)
    print(f"  OK: {filepath}")
    return True

def main():
    ok = True
    print("[adb_root] target=%s" % KERNEL_ROOT)

    # 1. Copy source files
    for src_rel, dst_rel in FILES:
        src = os.path.join(PATCH_DIR, src_rel)
        dst = os.path.join(KSU, dst_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        print(f"  COPY: {dst_rel}")

    # 2. Add escape_to_root_for_adb_root() to selinux.c (uses static transive_to_domain)
    #    Note: commit 430a739 already added this function to legacy, check first
    selinux_c = os.path.join(KSU, "selinux/selinux.c")
    with open(selinux_c) as f:
        sc = f.read()
    if SCRIPT_MARK in sc:
        print(f"  SKIP: {selinux_c} already injected")
    elif "escape_to_root_for_adb_root" in sc:
        print(f"  SKIP: {selinux_c} already has escape_to_root_for_adb_root (legacy 430a739)")
        # Add mark for idempotency
        sc = sc.replace("void escape_to_root_for_adb_root(void)", SCRIPT_MARK + "\nvoid escape_to_root_for_adb_root(void)", 1)
        with open(selinux_c, 'w') as f:
            f.write(sc)
    else:
        # Find a unique insertion point: after setup_selinux function
        # Use the closing brace + blank line before setup_ksu_cred as anchor
        anchor = "\n\nvoid setup_ksu_cred(void)"
        if anchor in sc:
            block = "\n" + ESCAPE_TO_ROOT.strip() + "\n"
            sc = sc.replace(anchor, block + anchor, 1)
            with open(selinux_c, 'w') as f:
                f.write(sc)
            print(f"  OK: {selinux_c}")
        else:
            print(f"  ERROR: anchor not found in {selinux_c}")
            ok = False

    # 3. Add declaration to selinux.h for cross-file visibility
    selinux_h = os.path.join(KSU, "selinux/selinux.h")
    adb_decl = "void escape_to_root_for_adb_root(void);"
    if os.path.exists(selinux_h):
        with open(selinux_h) as f:
            sh = f.read()
        if adb_decl not in sh:
            # Find a good insertion point
            for anchor_h in ["void setup_ksu_cred(void);", "bool is_zygote", "int ksu_sid"]:
                if anchor_h in sh:
                    sh = sh.replace(anchor_h, adb_decl + "\n" + anchor_h, 1)
                    with open(selinux_h, 'w') as f:
                        f.write(sh)
                    print(f"  DECL: {selinux_h}")
                    break
        else:
            print(f"  SKIP: {selinux_h} already has declaration")

    # 3. Add hook call in ksud_integration.c sys_execve_handler_pre
    ksud_int = os.path.join(KSU, "runtime/ksud_integration.c")
    anchor = "\treturn ksu_handle_execveat_ksud(AT_FDCWD, &filename_p, &argv, NULL, NULL);"
    adb_hook = "\t/* KSU_ADB_ROOT_INJECTED */\n\tksu_adb_root_handle_execve(real_regs);"
    ok &= inject(ksud_int, anchor, adb_hook, after=False)

    # 4. Ensure feature/adb_root.o in Kbuild
    if os.path.exists(KBUILD):
        with open(KBUILD) as f:
            kb = f.read()
        if "feature/adb_root.o" not in kb:
            kb = kb.replace(
                "kernelsu-objs += feature/sulog.o",
                "kernelsu-objs += feature/sulog.o\n"
                "kernelsu-objs += feature/adb_root.o"
            )
            with open(KBUILD, 'w') as f:
                f.write(kb)
            print("  KBUILD: added feature/adb_root.o")
        else:
            print("  KBUILD: feature/adb_root.o already present")

    # 5. 4.19 compat: user_stack_pointer → PT_REGS_SP
    adb_c = os.path.join(KSU, "feature/adb_root.c")
    if os.path.exists(adb_c):
        with open(adb_c) as f:
            ac = f.read()
        ac = ac.replace("user_stack_pointer(regs)", "PT_REGS_SP(regs)")
        with open(adb_c, 'w') as f:
            f.write(ac)
        print("  COMPAT: user_stack_pointer → PT_REGS_SP")

    print("  Result: %s" % ("ALL OK" if ok else "SOME FAILURES"))
    sys.exit(0 if ok else 1)

if __name__ == '__main__':
    main()