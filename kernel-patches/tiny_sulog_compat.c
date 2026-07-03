/*
 * tiny_sulog.c — compat wrapper mapping legacy API to new sulog subsystem
 * 
 * Old API: sulog_init_heap(), write_sulog(sym), send_sulog_dump(uptr)
 * New API: ksu_compat_sulog(sym), ksu_sulog_handle_compat_dump(uptr)
 * 
 * Heap init is a no-op (new system uses dynamic allocation).
 */

#include <linux/types.h>
#include <linux/uaccess.h>

#include "tiny_sulog.h"
#include "sulog/event.h"

void sulog_init_heap(void)
{
	/* no-op: new sulog uses event_queue + kmalloc */
}

void write_sulog(uint8_t sym)
{
	ksu_compat_sulog(sym);
}

int send_sulog_dump(void __user *uptr)
{
	return ksu_sulog_handle_compat_dump(uptr);
}
