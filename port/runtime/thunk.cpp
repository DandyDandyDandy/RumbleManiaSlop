// Guest -> host calls that engine code may leave by raising a managed exception (il2cpp_raise_exception never
// returns to the engine). The raise becomes a host C++ throw; on this toolchain that is an SEH unwind
// (RaiseException / RtlUnwindEx), which runs the unwind handlers of the MSVC-compiled engine frames in between and
// lands in the catch below. The thunk then returns to its lifted caller with c->eh_unwinding still set, which is how
// guest exceptions propagate through lifted code (include/eh.h).
#include "rt.h"

namespace { struct GuestUnwind {}; }

extern "C" void rt_host_unwind(void) { throw GuestUnwind(); }

extern "C" void rt_thunk_run(Cpu *c, ThunkBody body, void *user) {
    RtThread *t = (RtThread *)c;
    EhSave sv;
    eh_save(c, &sv);
    int depth = t->thunk_depth, calls = t->call_depth;
    uint64_t lr = c->x[30];
    t->thunk_depth = depth + 1;
    try {
        body(c, user);
    } catch (GuestUnwind &) {
        eh_restore(c, &sv);
        c->x[30] = lr;
        t->call_depth = calls;
        if (!c->eh_unwinding) rt_fatal_c(c, "host unwind reached a thunk without a pending guest exception");
    }
    t->thunk_depth = depth;
}

static void raw_body(Cpu *c, void *fn) {
    uint64_t slots[8];
    for (int i = 0; i < 8; i++) slots[i] = c->x[i];
    c->x[0] = rt_win64_call(fn, slots, 8, nullptr);
}

extern "C" void rt_raw_host_call(Cpu *c, void *fn) { rt_thunk_run(c, raw_body, fn); }
