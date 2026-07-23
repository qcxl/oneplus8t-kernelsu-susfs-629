/* ksu_handle_execveat wrapper - bridges fs/exec.c to ksu_handle_execveat_ksud */
void ksu_handle_execveat(int *fd, const char __user **filename,
                          void *argv, void *envp, int *flags)
{
        struct filename f;
        struct filename *fp;
        char path[32];
        long len;

        if (!filename || !*filename)
                return;

        len = strncpy_from_user_nofault(path, *filename, sizeof(path));
        if (len <= 0)
                return;
        path[sizeof(path) - 1] = '\0';

        f.name = path;
        fp = &f;

        pr_info("ksu: execve hook path='%s' pid=%d\n", path, current->pid);

        ksu_handle_execveat_ksud(fd, &fp,
                (struct user_arg_ptr *)argv,
                (struct user_arg_ptr *)envp,
                flags);
}
