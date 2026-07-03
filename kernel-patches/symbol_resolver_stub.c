// SPDX-License-Identifier: GPL-2.0-only
/*
 * kernel-patches/symbol_resolver_stub.c — SUSFS/KSU symbol resolution for 4.19
 *
 * Simplified version of KernelSU-Next dev branch's infra/symbol_resolver.c.
 * 4.19 has kallsyms_lookup_name() but does NOT have kallsyms_on_each_symbol()
 * available as an exported symbol. This simplified version uses only
 * kallsyms_lookup_name() directly, which is sufficient for 4.19.
 */

#include <linux/kallsyms.h>
#include <linux/module.h>
#include <linux/string.h>
#include <linux/version.h>

#include "symbol_resolver.h"

unsigned long find_kernel_symbol_exact(const char *symbol_name)
{
	unsigned long addr = 0;
	char *module_name = NULL;
	char buf[KSYM_SYMBOL_LEN];

	addr = kallsyms_lookup_name(symbol_name);
	if (!addr)
		return 0;

	// ignore module symbols — we only want core kernel symbols
	kallsyms_lookup(addr, NULL, NULL, &module_name, buf);
	if (unlikely(module_name)) {
		pr_warn("symbol_resolver: ignore module symbol %s (%s)\n",
			symbol_name, module_name);
		return 0;
	}
	return addr;
}
EXPORT_SYMBOL(find_kernel_symbol_exact);

void *ksu_resolve_symbol_for_functable_hook(const char *symbol_name)
{
	if (!symbol_name || !symbol_name[0])
		return NULL;
	return (void *)find_kernel_symbol_exact(symbol_name);
}
EXPORT_SYMBOL(ksu_resolve_symbol_for_functable_hook);

void ksu_init_symbol_resolver(void)
{
	/* On 4.19, kallsyms_lookup_name is always available.
	 * kallsyms_on_each_symbol is NOT exported on many 4.19 kernels,
	 * so we skip the function-pointer fallback used by dev branch. */
}
EXPORT_SYMBOL(ksu_init_symbol_resolver);
