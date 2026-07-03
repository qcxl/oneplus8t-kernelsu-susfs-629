// SPDX-License-Identifier: GPL-2.0-only
#ifndef __KSU_SYMBOL_RESOLVER_STUB_H
#define __KSU_SYMBOL_RESOLVER_STUB_H

unsigned long find_kernel_symbol_exact(const char *symbol_name);
void *ksu_resolve_symbol_for_functable_hook(const char *symbol_name);
void ksu_init_symbol_resolver(void);

#endif
