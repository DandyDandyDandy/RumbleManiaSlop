// Guest address -> host function. Flat table for the lifted functions (after xc2-recomp runtime/dispatch.c, MIT),
// a synthetic address window for host-bound functions (imports, icall thunks, traps), a small hash for host
// implementations of non-lifted functions inside main, and raw host pointers as the last resort.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

extern const uint64_t main_fn_addrs[];
extern const GuestFn main_fn_ptrs[];
extern const uint64_t main_fn_count;
typedef struct { uint64_t addr; const char *kind; const char *name; } RtBoundaryInfo;
extern const RtBoundaryInfo rt_boundary_info[];
extern const uint64_t rt_boundary_count;

static struct __attribute__((aligned(64))) {
    const uint32_t *slot;
    uintptr_t anchor;
    uint64_t lo;
    uint64_t slots;
} D;

static SynEntry *g_syn;
static volatile LONG g_nsyn;
static SRWLOCK g_syn_lock = SRWLOCK_INIT;

#define BOUND_CAP 4096
static struct { uint64_t addr; HostFn fn; const char *name; } g_bound[BOUND_CAP];

static void ret_sentinel(Cpu *c) { rt_fatal_c(c, "guest code jumped to the host return sentinel"); }

uint64_t rt_syn_alloc(HostFn fn, const char *name, void *user) {
    AcquireSRWLockExclusive(&g_syn_lock);
    if (!g_syn) {
        g_syn = VirtualAlloc(NULL, (size_t)SYN_MAX * sizeof *g_syn, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
        VirtualAlloc((void *)SYN_BASE, (size_t)SYN_MAX * 16, MEM_RESERVE, PAGE_NOACCESS);   // keep host allocations out
        g_syn[0].fn = ret_sentinel;
        g_syn[0].name = "rt_call return";
        g_nsyn = 1;
    }
    if (g_nsyn >= (LONG)SYN_MAX) rt_fatal("out of synthetic guest addresses");
    LONG i = g_nsyn;
    g_syn[i].fn = fn;
    g_syn[i].name = name;
    g_syn[i].user = user;
    MemoryBarrier();
    g_nsyn = i + 1;
    ReleaseSRWLockExclusive(&g_syn_lock);
    return SYN_BASE + (uint64_t)i * 16;
}

SynEntry *rt_syn_entry(uint64_t addr) {
    uint64_t i = (addr - SYN_BASE) >> 4;
    if (addr < SYN_BASE || (addr & 15) || i >= (uint64_t)g_nsyn) return NULL;
    return &g_syn[i];
}

static uint32_t bound_hash(uint64_t a) { return (uint32_t)(((a >> 2) * 0x9E3779B97F4A7C15ull) >> 52); }

void rt_bind_addr(uint64_t addr, HostFn fn, const char *name) {
    uint32_t h = bound_hash(addr);
    while (g_bound[h].addr && g_bound[h].addr != addr) h = (h + 1) & (BOUND_CAP - 1);
    g_bound[h].addr = addr;
    g_bound[h].fn = fn;
    g_bound[h].name = name;
}

HostFn rt_bound_lookup(uint64_t addr, const char **name) {
    for (uint32_t h = bound_hash(addr); g_bound[h].addr; h = (h + 1) & (BOUND_CAP - 1))
        if (g_bound[h].addr == addr) {
            if (name) *name = g_bound[h].name;
            return g_bound[h].fn;
        }
    return NULL;
}

const char *rt_boundary_name(uint64_t addr) {

    uint64_t lo = 0, hi = rt_boundary_count;
    while (lo < hi) {   // sorted by address when the generator wrote it; fall back to a scan otherwise
        uint64_t mid = (lo + hi) / 2;
        if (rt_boundary_info[mid].addr < addr) lo = mid + 1; else hi = mid;
    }
    if (lo < rt_boundary_count && rt_boundary_info[lo].addr == addr) return rt_boundary_info[lo].name;
    for (uint64_t i = 0; i < rt_boundary_count; i++)
        if (rt_boundary_info[i].addr == addr) return rt_boundary_info[i].name;
    return NULL;
}

void rt_dispatch_init(void) {
    if (D.slot) return;
    uint64_t n = main_fn_count;
    if (!n) rt_fatal("dispatch: empty function table");
    uint64_t lo = main_fn_addrs[0], hi = main_fn_addrs[n - 1] + 4;
    uintptr_t host_lo = UINTPTR_MAX, host_hi = 0;
    for (uint64_t k = 0; k < n; k++) {
        uintptr_t f = (uintptr_t)main_fn_ptrs[k];
        if (k && main_fn_addrs[k] <= main_fn_addrs[k - 1]) rt_fatal("dispatch: main_fn_addrs not ascending at %llu", (unsigned long long)k);
        if (f < host_lo) host_lo = f;
        if (f > host_hi) host_hi = f;
    }
    uintptr_t anchor = (host_lo & ~(uintptr_t)15) - 16;
    if (host_hi - anchor > UINT32_MAX) rt_fatal("dispatch: lifted code spans more than 4 GiB");
    uint64_t slots = (hi - lo) >> 2;
    uint32_t *slot = VirtualAlloc(NULL, slots * 4, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (!slot) rt_fatal("dispatch: cannot allocate the table");
    for (uint64_t k = 0; k < n; k++) slot[(main_fn_addrs[k] - lo) >> 2] = (uint32_t)((uintptr_t)main_fn_ptrs[k] - anchor);
    D.anchor = anchor;
    D.lo = lo;
    D.slots = slots;
    MemoryBarrier();
    D.slot = slot;
    rt_log("dispatch: %llu lifted functions, guest %#llx-%#llx", (unsigned long long)n, (unsigned long long)lo, (unsigned long long)hi);
}

GuestFn rt_lifted_lookup(uint64_t pc) {
    uint64_t i = __builtin_rotateright64(pc - D.lo, 2);
    if (i < D.slots && D.slot[i]) return (GuestFn)(D.anchor + D.slot[i]);
    return NULL;
}

static void trace_host(Cpu *c, const char *name) {
    char b[300];
    rt_log("host %s(%#llx, %#llx, %#llx, %#llx) lr %s", name, (unsigned long long)c->x[0], (unsigned long long)c->x[1],
           (unsigned long long)c->x[2], (unsigned long long)c->x[3], rt_guest_name(c->x[30], b, sizeof b));
}

__attribute__((noinline)) static void dispatch_slow(Cpu *c) {
    uint64_t pc = c->pc;
    SynEntry *e = rt_syn_entry(pc);
    if (e) {
        e->calls++;
        if (__builtin_expect(rt_trace & 1, 0)) trace_host(c, e->name);
        const char *outer = ((RtThread *)c)->in_host;
        ((RtThread *)c)->in_host = e->name;
        e->fn(c);
        ((RtThread *)c)->in_host = outer;
        return;
    }
    if (rt_in_image(pc)) {
        const char *name = NULL;
        HostFn f = rt_bound_lookup(pc, &name);
        if (f) {
            if (__builtin_expect(rt_trace & 1, 0)) trace_host(c, name);
            f(c);
            return;
        }
        char a[300], l[300];
        rt_fatal_c(c, "rt_dispatch: guest pc %s is not lifted and has no host implementation (%s; lr %s)",
                   rt_guest_name(pc, a, sizeof a), (pc & 3) ? "misaligned" : "non-lifted code or data", rt_guest_name(c->x[30], l, sizeof l));
    }
    if (pc < 0x10000 || (pc >= SYN_BASE && pc < SYN_BASE + (uint64_t)SYN_MAX * 16)) {
        char l[300];
        rt_fatal_c(c, "rt_dispatch: call to invalid address %#llx (lr %s)", (unsigned long long)pc, rt_guest_name(c->x[30], l, sizeof l));
    }
    if (__builtin_expect(rt_trace & 1, 0)) trace_host(c, "<raw host pointer>");
    rt_raw_host_call(c, (void *)(uintptr_t)pc);
}

void rt_dispatch(Cpu *c) {
    uint64_t i = __builtin_rotateright64(c->pc - D.lo, 2);
    if (__builtin_expect(i < D.slots, 1)) {
        uint32_t s = D.slot[i];
        if (__builtin_expect(s != 0, 1)) {
            __attribute__((musttail)) return ((GuestFn)(D.anchor + s))(c);
        }
    }
    __attribute__((musttail)) return dispatch_slow(c);
}

int rt_pinvoke_policy(Cpu *c, uint64_t addr, const char *name);   // pinvoke_policy.c

// A P/Invoke native of the Switch plugins (CRIWARE, NPLN, nn.*) that has no host implementation behaves like a
// missing plugin entry point on any platform: the managed caller gets System.EntryPointNotFoundException (logged
// once per native). BR_PINVOKE=trap turns it into a fatal error instead.
static uint64_t g_pinvoke_missing_calls, g_pinvoke_missing_distinct;
static void pinvoke_missing(Cpu *c, uint64_t addr, const char *name) {
    static int mode;
    static uint8_t *seen;
    if (!mode) { const char *e = getenv("BR_PINVOKE"); mode = e && !strcmp(e, "trap") ? 2 : 1; seen = calloc(1, 0xc6e000 >> 4); }
    if (mode == 2) rt_fatal_c(c, "call to non-lifted native main+%#llx (%s): no host implementation", (unsigned long long)(addr - GUEST_BASE), name);
    uint64_t i = (addr - GUEST_BASE) >> 4;
    g_pinvoke_missing_calls++;
    if (i < (0xc6e000 >> 4) && !seen[i]) {
        seen[i] = 1;
        g_pinvoke_missing_distinct++;
        rt_log("P/Invoke %s (main+%#llx) has no host implementation: raising EntryPointNotFoundException", name, (unsigned long long)(addr - GUEST_BASE));
    }
    uint64_t corlib = rt_call(c, rt_api_addr("il2cpp_get_corlib"), 0);
    uint64_t ex = rt_call(c, rt_api_addr("il2cpp_exception_from_name_msg"), 4, corlib, (uint64_t)(uintptr_t)"System",
                          (uint64_t)(uintptr_t)"EntryPointNotFoundException", (uint64_t)(uintptr_t)name);
    rt_call(c, rt_api_addr("il2cpp_raise_exception"), 1, ex);
    if (!c->eh_unwinding) rt_fatal_c(c, "raising EntryPointNotFoundException for %s did not unwind", name);
}

void rt_boundary(Cpu *c, uint64_t addr) {
    const char *name = NULL;
    HostFn f = rt_bound_lookup(addr, &name);
    c->pc = addr;
    if (!f) {
        const char *bn = rt_boundary_name(addr);
        if (bn && !strncmp(bn, "native for ", 11)) {
            if (!rt_pinvoke_policy(c, addr, bn)) pinvoke_missing(c, addr, bn);
            return;
        }
        rt_fatal_c(c, "call to non-lifted code main+%#llx (%s): no host implementation", (unsigned long long)(addr - GUEST_BASE),
                   bn ? bn : "unnamed");
    }
    if (__builtin_expect(rt_trace & 1, 0)) trace_host(c, name);
    f(c);
}

// ---- host -> guest
void rt_call_regs(Cpu *c, uint64_t fn) {
    RtThread *t = (RtThread *)c;
    EhSave sv;
    eh_save(c, &sv);
    uint64_t lr = c->x[30], pc = c->pc;
    c->x[30] = RT_RET_HOST;
    c->pc = fn;
    rt_fpcr_sync(c);
    t->call_depth++;
    rt_dispatch(c);
    t->call_depth--;
    eh_restore(c, &sv);
    c->x[30] = lr;
    c->pc = pc;
}

uint64_t rt_call(Cpu *c, uint64_t fn, int n, ...) {
    va_list ap;
    va_start(ap, n);
    for (int i = 0; i < n; i++) c->x[i] = va_arg(ap, uint64_t);
    va_end(ap);
    rt_call_regs(c, fn);
    return c->x[0];
}

// A guest exception left the outermost guest frame of a host -> guest call made by engine code.
void rt_escape_check(Cpu *c, const char *what) {
    if (__builtin_expect(c->eh_unwinding == 0, 1)) return;
    RtThread *t = (RtThread *)c;
    if (t->thunk_depth > 0) rt_host_unwind();   // propagate through the engine frames to the managed caller
    char b[512];
    rt_fatal_c(c, "unhandled guest exception (%s) escaped from %s into the engine", rt_eh_describe(c, b, sizeof b), what);
}
