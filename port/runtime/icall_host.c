// Host implementations of internal calls that exist only in the Switch engine (the Windows engine never registers
// them, so lifted managed code would get MissingMethodException). Guest calling convention: arguments in x0.. / v0..,
// result in x0 / v0. Policy: a docked console that is never asked to exit, with no Switch-specific notifications.
#include <windows.h>
#include <string.h>
#include "rt.h"

typedef struct { const char *name; HostFn fn; } HostIcall;

static void ret0(Cpu *c) { RET(0); }
static void ret1(Cpu *c) { RET(1); }
static void nop(Cpu *c) { (void)c; }

const HostIcall rt_host_icalls[] = {
#include "icall_host.inc"
    {0, 0},
};
