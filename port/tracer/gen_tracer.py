"""Generate a tracing GameAssembly.dll stub from the exact-version il2cpp-api-functions.h.

    python gen_tracer.py <il2cpp-api-functions.h> <out.c>

Every il2cpp_* export logs its name and first four integer arguments to il2cpp_trace.log next to the
executable and returns 0 (il2cpp_init returns 1). Purpose: learn the order in which the Windows player
calls the API and how far it gets on the Switch game's data, before any real code exists.
"""
import re, sys

src = open(sys.argv[1], encoding='utf-8', errors='replace').read()
names = []
for m in re.finditer(r'^\s*DO_API(?:_NO_RETURN)?\s*\(\s*(.+?)\s*,\s*(il2cpp_\w+)\s*,', src, re.M):
    if m.group(2) not in names:
        names.append(m.group(2))
out = ['#include <windows.h>', '#include <stdio.h>', '#include <stdint.h>', '',
       'static FILE *g_log; static CRITICAL_SECTION g_cs; static int g_n;',
       'static void tr(const char *n, void *a, void *b, void *c, void *d) {',
       '    if (!g_log) { InitializeCriticalSection(&g_cs); g_log = fopen("il2cpp_trace.log", "w"); }',
       '    if (g_n >= 400000) return;   // the player keeps running its loop on null results; cap the log',
       '    EnterCriticalSection(&g_cs);',
       '    fprintf(g_log, "%5d t%lu %s(%p, %p, %p, %p)\\n", g_n++, GetCurrentThreadId(), n, a, b, c, d);',
       '    if (n[7] == \'s\' && (!strncmp(n, "il2cpp_set_", 11) || !strcmp(n, "il2cpp_string_new")) && a && !IsBadStringPtrA(a, 512))',
       '        fprintf(g_log, "        str: %s\\n", (const char *)a);',
       '    if (!strcmp(n, "il2cpp_add_internal_call") || !strcmp(n, "il2cpp_init") || !strcmp(n, "il2cpp_resolve_icall")',
       '        || !strcmp(n, "il2cpp_class_from_name"))',
       '        if (a && !IsBadStringPtrA(a, 512)) fprintf(g_log, "        str: %s\\n", (const char *)a);',
       '    fflush(g_log); LeaveCriticalSection(&g_cs);', '}', '']
for n in names:
    ret = '(void *)1' if n in ('il2cpp_init', 'il2cpp_init_utf16') else '0'
    out.append(f'__declspec(dllexport) void *{n}(void *a, void *b, void *c, void *d) {{ tr("{n}", a, b, c, d); return {ret}; }}')
open(sys.argv[2], 'w').write('\n'.join(out) + '\n')
print(len(names), 'exports')
