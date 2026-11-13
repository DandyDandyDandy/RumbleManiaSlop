// BR_HEAPDBG=1 (with the player argument -systemallocator): a debug heap under the engine, to find heap corruption
// inside UnityPlayer.dll (which has no instrumentation of its own in the release player).
//
// With -systemallocator the engine allocates through the C runtime, i.e. kernel32 HeapAlloc / HeapFree / HeapReAlloc /
// HeapSize. Those four import slots of UnityPlayer.dll are redirected here. Every block gets a header (size, the
// call stack that allocated it) and guard bytes before and after the user memory. The guards are checked when the
// block is freed, by a sweep over all live blocks twice a second, and when the process crashes; freed blocks are
// filled with a pattern and held back for a while so that writes after free show up too. A damaged guard is reported
// in port.log with the stack that allocated the block (resolve the UnityPlayer.dll offsets with
// port\tools\sym_unity.py): for an overrun that block is the culprit's own buffer.
// Blocks the engine allocated before the redirection are recognised (the real heap validates them) and passed through.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define MAGIC 0x48454150444247ull          // "HEAPDBG"
#define FREED 0x46524545444247ull
#define TAIL 32
#define NFRAMES 10
#define QUARANTINE_BYTES (256u << 20)
typedef struct Blk {
    struct Blk *prev, *next;
    uint64_t size;
    HANDLE heap;
    uint32_t tid, serial;
    void *stack[NFRAMES];
    uint64_t pad;
    uint64_t magic;                         // directly before the user memory
} Blk;                                      // 144 bytes: user memory stays 16-byte aligned

static CRITICAL_SECTION g_lock;
static Blk g_live = {&g_live, &g_live}, g_dead = {&g_dead, &g_dead};
static uint64_t g_dead_bytes, g_allocs, g_reports;
static uint32_t g_serial;
static int g_on;

static void where(void *p, char *out, size_t n) {
    HMODULE m = NULL;
    char path[MAX_PATH];
    if (GetModuleHandleExA(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS | GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT, p, &m) && m &&
        GetModuleFileNameA(m, path, sizeof path)) {
        const char *b = strrchr(path, '\\');
        snprintf(out, n, "%s+0x%llx", b ? b + 1 : path, (unsigned long long)((uintptr_t)p - (uintptr_t)m));
    } else snprintf(out, n, "%p", p);
}
static void report(Blk *b, const char *what, int at) {
    char line[1200];
    int n = 0;
    if (g_reports++ > 40) return;
    n += snprintf(line, sizeof line, "HEAPDBG: %s: block #%u, %llu bytes at %p, allocated by thread %u from", what, b->serial,
                  (unsigned long long)b->size, (void *)(b + 1), b->tid);
    for (int i = 0; i < NFRAMES && b->stack[i] && n < 1100; i++) {
        char w[300];
        where(b->stack[i], w, sizeof w);
        n += snprintf(line + n, sizeof line - (size_t)n, " %s", w);
    }
    rt_log("%s", line);
    if (at >= 0) {
        const uint8_t *u = (const uint8_t *)(b + 1) + b->size;
        char hex[TAIL * 3 + 4];
        for (int i = 0; i < TAIL; i++) snprintf(hex + i * 3, 4, "%02x ", u[i]);
        rt_log("HEAPDBG:   bytes after the block (guard is fd): %s", hex);
    }
    void *cur[NFRAMES] = {0};
    n = snprintf(line, sizeof line, "HEAPDBG:   noticed by thread %lu at", GetCurrentThreadId());
    RtlCaptureStackBackTrace(2, NFRAMES, cur, NULL);
    for (int i = 0; i < NFRAMES && cur[i] && n < 1100; i++) {
        char w[300];
        where(cur[i], w, sizeof w);
        n += snprintf(line + n, sizeof line - (size_t)n, " %s", w);
    }
    rt_log("%s", line);
}
// 0 = intact
static int damaged(Blk *b, uint64_t magic) {
    const uint8_t *t = (const uint8_t *)(b + 1) + b->size;
    if (b->magic != magic) return 1;
    for (int i = 0; i < TAIL; i++)
        if (t[i] != 0xfd) return 2;
    return 0;
}
static void check_live(Blk *b) {
    int d = damaged(b, MAGIC);
    if (d && b->pad != 1) {                                         // report each block once
        b->pad = 1;
        report(b, d == 1 ? "WRITE BEFORE THE START of a block (underrun)" : "WRITE PAST THE END of a block (overrun)", d == 2 ? 0 : -1);
    }
}
static void check_dead(Blk *b) {
    const uint8_t *u = (const uint8_t *)(b + 1);
    for (uint64_t i = 0; i < b->size; i++)
        if (u[i] != 0xdd) { report(b, "WRITE AFTER FREE into a block", -1); return; }
}
void heapdbg_sweep(const char *why) {
    if (!g_on) return;
    EnterCriticalSection(&g_lock);
    uint64_t n = 0;
    for (Blk *b = g_live.next; b != &g_live; b = b->next) { check_live(b); n++; }
    if (why) {
        for (Blk *b = g_dead.next; b != &g_dead; b = b->next) check_dead(b);
        rt_log("HEAPDBG: sweep (%s): %llu live blocks, %llu allocations so far, %llu reports", why, (unsigned long long)n,
               (unsigned long long)g_allocs, (unsigned long long)g_reports);
    }
    LeaveCriticalSection(&g_lock);
}
static DWORD WINAPI sweeper(LPVOID p) {
    (void)p;
    for (int k = 0;; k++) {
        Sleep(500);
        heapdbg_sweep(k % 60 == 59 ? "periodic" : NULL);
    }
}

static LPVOID WINAPI h_alloc(HANDLE heap, DWORD flags, SIZE_T size) {
    Blk *b = HeapAlloc(heap, flags & ~(DWORD)HEAP_ZERO_MEMORY, sizeof *b + size + TAIL);
    if (!b) return NULL;
    memset(b->stack, 0, sizeof b->stack);
    RtlCaptureStackBackTrace(1, NFRAMES, b->stack, NULL);
    b->size = size; b->heap = heap; b->tid = GetCurrentThreadId(); b->pad = 0; b->magic = MAGIC;
    uint8_t *u = (uint8_t *)(b + 1);
    if (flags & HEAP_ZERO_MEMORY) memset(u, 0, size); else memset(u, 0xcd, size);
    memset(u + size, 0xfd, TAIL);
    EnterCriticalSection(&g_lock);
    b->serial = ++g_serial;
    g_allocs++;
    b->next = &g_live; b->prev = g_live.prev; b->prev->next = b; g_live.prev = b;
    LeaveCriticalSection(&g_lock);
    return u;
}
static int ours(HANDLE heap, const void *p) {
    // a block from before the redirection is a real heap block; ours are interior pointers of real blocks
    return !HeapValidate(heap, 0, p);
}
static BOOL WINAPI h_free(HANDLE heap, DWORD flags, LPVOID p) {
    if (!p) return TRUE;
    if (!ours(heap, p)) return HeapFree(heap, flags, p);
    Blk *b = (Blk *)p - 1;
    EnterCriticalSection(&g_lock);
    if (b->magic == FREED) {
        report(b, "DOUBLE FREE of a block", -1);
        LeaveCriticalSection(&g_lock);
        return TRUE;
    }
    check_live(b);
    b->prev->next = b->next; b->next->prev = b->prev;
    b->magic = FREED;
    memset(p, 0xdd, b->size);
    b->next = &g_dead; b->prev = g_dead.prev; b->prev->next = b; g_dead.prev = b;
    g_dead_bytes += b->size + sizeof *b + TAIL;
    while (g_dead_bytes > QUARANTINE_BYTES && g_dead.next != &g_dead) {
        Blk *o = g_dead.next;
        check_dead(o);
        o->prev->next = o->next; o->next->prev = o->prev;
        g_dead_bytes -= o->size + sizeof *o + TAIL;
        HeapFree(o->heap, 0, o);
    }
    LeaveCriticalSection(&g_lock);
    return TRUE;
}
static SIZE_T WINAPI h_size(HANDLE heap, DWORD flags, LPCVOID p) {
    if (!ours(heap, p)) return HeapSize(heap, flags, p);
    return ((const Blk *)p - 1)->size;
}
static LPVOID WINAPI h_realloc(HANDLE heap, DWORD flags, LPVOID p, SIZE_T size) {
    if (!p) return h_alloc(heap, flags, size);
    if (flags & HEAP_REALLOC_IN_PLACE_ONLY) return NULL;
    SIZE_T old = h_size(heap, 0, p);
    uint8_t *n = h_alloc(heap, flags, size);
    if (!n) return NULL;
    memcpy(n, p, old < size ? old : size);
    h_free(heap, 0, p);
    return n;
}

void heapdbg_init(void) {
    static const struct { const char *name; void *fn; } hooks[] = {
        {"HeapAlloc", h_alloc}, {"HeapFree", h_free}, {"HeapReAlloc", h_realloc}, {"HeapSize", h_size}};
    const char *e = getenv("BR_HEAPDBG");
    uint8_t *base = (uint8_t *)GetModuleHandleA("UnityPlayer.dll");
    if (!e || !*e || !base || g_on) return;
    InitializeCriticalSection(&g_lock);
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(base + ((IMAGE_DOS_HEADER *)base)->e_lfanew);
    IMAGE_DATA_DIRECTORY dir = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];
    HMODULE k32 = GetModuleHandleA("kernel32.dll");
    int patched = 0;
    void *real[4];
    for (int i = 0; i < 4; i++) real[i] = (void *)GetProcAddress(k32, hooks[i].name);
    for (IMAGE_IMPORT_DESCRIPTOR *d = (IMAGE_IMPORT_DESCRIPTOR *)(base + dir.VirtualAddress); dir.Size && d->Name; d++) {
        if (_stricmp((const char *)(base + d->Name), "kernel32.dll")) continue;
        for (void **slot = (void **)(base + d->FirstThunk); *slot; slot++)
            for (int i = 0; i < 4; i++)
                if (*slot == real[i]) {
                    DWORD old;
                    VirtualProtect(slot, sizeof *slot, PAGE_READWRITE, &old);
                    *slot = hooks[i].fn;
                    VirtualProtect(slot, sizeof *slot, old, &old);
                    patched++;
                }
    }
    g_on = patched == 4;
    rt_log("HEAPDBG: %d of 4 heap imports of UnityPlayer.dll redirected%s", patched,
           g_on ? " (run the player with -systemallocator)" : ": not active");
    if (g_on) CloseHandle(CreateThread(NULL, 0, sweeper, NULL, 0, NULL));
}
