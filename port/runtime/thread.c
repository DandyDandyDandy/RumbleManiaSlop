// Per-host-thread guest context: Cpu, guest stack, thread-local region, nn::os::ThreadType stand-in.
#include <windows.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define GUEST_STACK_SIZE (16u << 20)
#define TLR_SIZE 0x1000
#define THREAD_TYPE_SIZE 0x400

static DWORD g_fls = FLS_OUT_OF_INDEXES;
static CRITICAL_SECTION g_threads_cs;
static INIT_ONCE g_once = INIT_ONCE_STATIC_INIT;
RtThread *rt_threads;

void rt_threads_lock(void) { EnterCriticalSection(&g_threads_cs); }
void rt_threads_unlock(void) { LeaveCriticalSection(&g_threads_cs); }
int rt_threads_trylock(void) { return TryEnterCriticalSection(&g_threads_cs) != 0; }

void rt_thread_exit(RtThread *t) {
    if (!t) return;
    rt_threads_lock();
    for (RtThread **p = &rt_threads; *p; p = &(*p)->next)
        if (*p == t) { *p = t->next; break; }
    rt_threads_unlock();
    if (t->host_thread) CloseHandle(t->host_thread);
    if (t->own_stack) VirtualFree((void *)(uintptr_t)t->stack_lo, 0, MEM_RELEASE);
    _aligned_free(t->tlr);
    // The ThreadType block stays allocated: guest code may still hold the pointer (GetCurrentThread).
    _aligned_free(t);
}

static void WINAPI fls_dtor(void *p) { rt_thread_exit(p); }

static BOOL CALLBACK init_once(PINIT_ONCE o, PVOID p, PVOID *ctx) {
    (void)o; (void)p; (void)ctx;
    InitializeCriticalSection(&g_threads_cs);
    g_fls = FlsAlloc(fls_dtor);
    return TRUE;
}

// The fields of nn::os::ThreadType that lifted code reads directly: the stack (+0x50 base, +0x58 size) and the
// thread id at +0x1b0. The lifted collector keys its table of registered threads on that id and treats 0 as a
// free slot, so every thread needs a distinct non-zero one.
void rt_thread_type_init(uint64_t thread_type, uint64_t stack, uint64_t stack_size) {
    static volatile LONG next_id = 0x40;
    ST64(thread_type + 0x50, stack);
    ST64(thread_type + 0x58, stack_size);
    ST32(thread_type + 0x1b0, (uint32_t)InterlockedIncrement(&next_id));
}

RtThread *rt_thread_create(uint64_t stack, uint64_t stack_size) {
    InitOnceExecuteOnce(&g_once, init_once, NULL, NULL);
    RtThread *t = _aligned_malloc(sizeof *t, 64);
    memset(t, 0, sizeof *t);
    if (!stack) {
        stack_size = GUEST_STACK_SIZE;
        stack = (uint64_t)(uintptr_t)VirtualAlloc(NULL, stack_size, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        if (!stack) rt_fatal("cannot allocate a guest stack");
        t->own_stack = 1;
    }
    t->stack_lo = stack;
    t->stack_hi = stack + stack_size;
    t->cpu.sp = (t->stack_hi - 0x100) & ~15ull;
    t->tlr = _aligned_malloc(TLR_SIZE, 64);
    memset(t->tlr, 0, TLR_SIZE);
    t->thread_type = _aligned_malloc(THREAD_TYPE_SIZE, 64);
    memset(t->thread_type, 0, THREAD_TYPE_SIZE);
    rt_thread_type_init((uint64_t)(uintptr_t)t->thread_type, t->stack_lo, stack_size);
    t->cpu.tpidrro = (uint64_t)(uintptr_t)t->tlr;
    t->cpu.thread = t;
    return t;
}

void rt_thread_bind(RtThread *t) {
    InitOnceExecuteOnce(&g_once, init_once, NULL, NULL);
    DuplicateHandle(GetCurrentProcess(), GetCurrentThread(), GetCurrentProcess(), (HANDLE *)&t->host_thread, 0, FALSE, DUPLICATE_SAME_ACCESS);
    t->host_tid = GetCurrentThreadId();
    ULONG_PTR lo, hi;
    GetCurrentThreadStackLimits(&lo, &hi);
    t->host_stack_hi = hi;
    // The thread-local region's last slot holds the thread pointer on Horizon (ThreadType at +0x1f8).
    memcpy(t->tlr + 0x1f8, &t->thread_type, 8);
    FlsSetValue(g_fls, t);
    rt_threads_lock();
    t->next = rt_threads;
    rt_threads = t;
    rt_threads_unlock();
}

RtThread *rt_thread(void) {
    RtThread *t = g_fls != FLS_OUT_OF_INDEXES ? FlsGetValue(g_fls) : NULL;
    if (__builtin_expect(t != NULL, 1)) return t;
    t = rt_thread_create(0, 0);
    rt_thread_bind(t);
    if (rt_trace & 16) rt_log("thread: new guest context %p for host thread %lu, guest stack %#llx-%#llx", (void *)t, (unsigned long)t->host_tid,
                              (unsigned long long)t->stack_lo, (unsigned long long)t->stack_hi);
    return t;
}
