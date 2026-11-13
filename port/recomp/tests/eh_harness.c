// Harness for port/recomp/tests/difftest.py: xc2-recomp tests/diff/harness.c (MIT, Copyright (c) 2026 Peiikai;
// included unmodified through UPSTREAM_HARNESS) with its call stub extended to throw guest C++ exceptions the way
// the port's runtime will (port/runtime/include/eh.h). difftest.py's EhRunner.stub is the same function for Unicorn.
#define rt_dispatch up_rt_dispatch
#define rt_stub_call up_rt_stub_call
#include UPSTREAM_HARNESS
#undef rt_dispatch
#undef rt_stub_call
#include "eh.h"

extern const uint64_t eh_rets[];      // sorted return addresses of the call sites that have a landing pad
extern const int eh_nrets;
extern const uint64_t eh_throwers[];  // __cxa_throw, __cxa_rethrow, _Unwind_Resume, std::rethrow_exception
extern const int eh_nthrowers;

#define EH_EXC (PTR_LO + 0x100)
static int g_handle;
static uint64_t g_sel;

static int has_pad(uint64_t ret) {
    int lo = 0, hi = eh_nrets;
    while (lo < hi) {
        int mid = (lo + hi) / 2;
        if (eh_rets[mid] < ret) lo = mid + 1; else hi = mid;
    }
    return lo < eh_nrets && eh_rets[lo] == ret;
}

// After the upstream stub: decide from the digest whether this call throws.
//  * a call site with a pad throws when the callee is a thrower or on a quarter of the digests; the abandoned
//    callee frames are modelled by trashing X19-X29, SP and V8-V15, which the caller must restore from its EhSave;
//  * a thrower called from a site without a pad throws out of the function (nothing trashed: the test compares the
//    state at that point).
static void eh_after(Cpu *c, uint64_t target) {
    uint64_t h = g_stub_h;
    int thrower = 0;
    for (int i = 0; i < eh_nthrowers; i++) thrower |= eh_throwers[i] == target;
    if (has_pad(c->x[30]) && (thrower || ((h >> 8) & 3) == 0)) {
        for (int i = 19; i < 30; i++) c->x[i] = splitmix(h + 100 + i);
        c->sp = splitmix(h + 99) & ~15ull;
        for (int i = 8; i < 16; i++) c->v[i] = (__uint128_t)splitmix(h + 200 + i) << 64 | splitmix(h + 300 + i);
        c->eh_unwinding = 1;
        c->eh_exc = EH_EXC;
        g_handle = ((h >> 20) & 7) != 0;
        g_sel = (h >> 12) & 3;
    } else if (thrower) {
        c->eh_unwinding = 1;
        c->eh_exc = EH_EXC;
    }
}

void rt_dispatch(Cpu *c) {
    up_rt_dispatch(c);
    if (g_stubs) eh_after(c, c->pc);
}
void rt_stub_call(Cpu *c, uint64_t target) {
    up_rt_stub_call(c, target);
    eh_after(c, target);
}
int rt_eh_enter(Cpu *c, uint64_t lsda, uint32_t action) {
    (void)lsda; (void)action;
    if (!g_handle) return 0;
    c->x[0] = c->eh_exc;
    c->x[1] = g_sel;
    c->eh_unwinding = 0;
    return 1;
}
void rt_boundary(Cpu *c, uint64_t addr) { rt_stub_call(c, addr); }
