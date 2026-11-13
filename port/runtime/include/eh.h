// Contract between the generated C (port/recomp) and the host runtime (port/runtime) for guest C++ exceptions.
//
// The Switch binary throws managed exceptions as Itanium C++ exceptions (libc++abi in the SDK, LSDAs in .eh_frame).
// Lifted functions are plain C functions, so there is no native unwinder to enter a landing pad. Instead an
// exception propagates by returning:
//
//   * __cxa_throw / __cxa_rethrow / _Unwind_Resume / std::rethrow_exception are host functions. They record the
//     exception in the Cpu (eh_exc), set c->eh_unwinding = 1 and return to the lifted caller.
//   * After EVERY guest call (direct f_x(c), rt_dispatch(c), host imports) the generated code tests
//     c->eh_unwinding. A call site with no landing pad returns at once (the frame is abandoned; its guest epilogue
//     does not run). A call site covered by an LSDA call-site record with a landing pad does:
//
//         if (__builtin_expect(c->eh_unwinding, 0)) {
//             EH_RESTORE(sv);                              // callee-saved state of THIS frame, saved before the call
//             if (rt_eh_enter(c, lsda, action)) goto pad;  // handles: x0 = exception object, x1 = selector
//             return;                                      // no matching handler here: keep unwinding
//         }
//
//   * Because abandoned frames never restore X19-X29, SP and D8-D15, a frame with landing pads snapshots them
//     before each covered call (EhSave) and restores them before entering a pad.
//   * Tail calls need no check: the callee returns straight to this function's caller, which checks.
//   * Host -> guest entry points (rt_call) see eh_unwinding still set on return when nothing caught the exception.
#pragma once
#include "cpu.h"

typedef struct EhSave {
    uint64_t x[11];   // X19..X29
    uint64_t sp;
    uint64_t d[8];    // low halves of V8..V15
} EhSave;

static inline __attribute__((always_inline)) void eh_save(const Cpu *c, EhSave *s) {
    for (int i = 0; i < 11; i++) s->x[i] = c->x[19 + i];
    s->sp = c->sp;
    for (int i = 0; i < 8; i++) s->d[i] = (uint64_t)c->v[8 + i];
}
static inline __attribute__((always_inline)) void eh_restore(Cpu *c, const EhSave *s) {
    for (int i = 0; i < 11; i++) c->x[19 + i] = s->x[i];
    c->sp = s->sp;
    for (int i = 0; i < 8; i++) c->v[8 + i] = (__uint128_t)s->d[i];
}

// Decide whether the frame that owns `lsda` handles the exception in c->eh_exc at a call site whose LSDA
// call-site record has action index `action` (the 1-based byte offset into the action table as stored in the
// record; 0 = cleanup only). `lsda` is the guest address of the LSDA. Returns non-zero when the landing pad must
// be entered; it has then set x0 = c->eh_exc, x1 = selector and cleared c->eh_unwinding. Returns 0 when the frame
// does not handle it (eh_unwinding stays set). A cleanup-only record always enters with selector 0.
int rt_eh_enter(Cpu *c, uint64_t lsda, uint32_t action);
