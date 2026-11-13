// C++ runtime imports other than exception handling: static-init guards, the out-of-line libc++ std::string members
// (operating on the GUEST libc++ layout), and the few std:: exception classes the lifted code constructs.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "rt.h"

// ---- __cxa_guard_*: byte 0 of the 64-bit guard is the "initialised" flag (ARM64 ABI: bit 0).
static CRITICAL_SECTION g_guard_cs;
static INIT_ONCE g_guard_once = INIT_ONCE_STATIC_INIT;
static BOOL CALLBACK guard_init(PINIT_ONCE o, PVOID p, PVOID *x) { (void)o; (void)p; (void)x; InitializeCriticalSection(&g_guard_cs); return TRUE; }
HOSTFN(__cxa_guard_acquire) {
    uint64_t g = X(0);
    if (LD8(g) & 1) { RET(0); return; }
    InitOnceExecuteOnce(&g_guard_once, guard_init, NULL, NULL);
    EnterCriticalSection(&g_guard_cs);
    if (LD8(g) & 1) { LeaveCriticalSection(&g_guard_cs); RET(0); return; }
    RET(1);
}
HOSTFN(__cxa_guard_release) { ST8(X(0), 1); MemoryBarrier(); LeaveCriticalSection(&g_guard_cs); }
HOSTFN(__cxa_guard_abort) { LeaveCriticalSection(&g_guard_cs); }

// ---- libc++ std::string, little-endian default layout (24 bytes):
//   short: byte0 = size << 1 (bit 0 clear), chars at +1 (capacity 22)
//   long:  word0 = allocation size | 1, word1 = size, word2 = data pointer
#define SSO_CAP 22
static inline int gs_long(uint64_t s) { return LD8(s) & 1; }
static inline char *gs_data(uint64_t s) { return gs_long(s) ? (char *)(uintptr_t)LD64(s + 16) : (char *)(uintptr_t)(s + 1); }
static inline size_t gs_size(uint64_t s) { return gs_long(s) ? LD64(s + 8) : (size_t)(LD8(s) >> 1); }
static inline size_t gs_cap(uint64_t s) { return gs_long(s) ? (LD64(s) & ~1ull) - 1 : SSO_CAP; }
static inline void gs_set_size(uint64_t s, size_t n) {
    if (gs_long(s)) ST64(s + 8, n); else ST8(s, n << 1);
    gs_data(s)[n] = 0;
}
static void gs_init(uint64_t s, const char *p, size_t n) {
    if (n <= SSO_CAP) {
        ST64(s, 0); ST64(s + 8, 0); ST64(s + 16, 0);
        ST8(s, n << 1);
        memcpy((char *)(uintptr_t)(s + 1), p, n);
    } else {
        size_t alloc = (n + 16) & ~15ull;
        char *d = rt_malloc(alloc);
        memcpy(d, p, n);
        d[n] = 0;
        ST64(s, alloc | 1); ST64(s + 8, n); ST64(s + 16, (uint64_t)(uintptr_t)d);
    }
}
// Make room for at least `cap` characters, keeping the contents.
static void gs_grow(uint64_t s, size_t cap) {
    if (cap <= gs_cap(s)) return;
    size_t n = gs_size(s), want = gs_cap(s) * 2;
    if (want < cap) want = cap;
    size_t alloc = (want + 16) & ~15ull;
    char *d = rt_malloc(alloc);
    memcpy(d, gs_data(s), n + 1);
    if (gs_long(s)) rt_free((void *)(uintptr_t)LD64(s + 16));
    ST64(s, alloc | 1); ST64(s + 8, n); ST64(s + 16, (uint64_t)(uintptr_t)d);
}
static void gs_replace(uint64_t s, size_t pos, size_t del, const char *p, size_t n) {
    size_t sz = gs_size(s);
    if (pos > sz) rt_fatal("std::string: position %zu out of range (size %zu)", pos, sz);
    if (del > sz - pos) del = sz - pos;
    char *tmp = NULL;
    const char *old = gs_data(s);
    if (n && p >= old && p <= old + sz) { tmp = rt_malloc(n); memcpy(tmp, p, n); p = tmp; }   // aliasing source
    gs_grow(s, sz - del + n);
    char *d = gs_data(s);
    memmove(d + pos + n, d + pos + del, sz - pos - del);
    if (n) memcpy(d + pos, p, n);
    gs_set_size(s, sz - del + n);
    if (tmp) rt_free(tmp);
}
#define BS(suffix) _ZNSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE##suffix
#define BSK(suffix) _ZNKSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE##suffix
#define HOSTFN2(sym) HOSTFN(sym)

HOSTFN2(BS(C1ERKS5_)) { gs_init(X(0), gs_data(X(1)), gs_size(X(1))); }
HOSTFN2(BS(C2ERKS5_)) { gs_init(X(0), gs_data(X(1)), gs_size(X(1))); }
static void substr_ctor(Cpu *c) {
    size_t sz = gs_size(X(1)), pos = X(2), n = X(3);
    if (pos > sz) rt_fatal_c(c, "std::string(str, pos, n): pos out of range");
    if (n > sz - pos) n = sz - pos;
    gs_init(X(0), gs_data(X(1)) + pos, n);
}
HOSTFN2(BS(C1ERKS5_mmRKS4_)) { substr_ctor(c); }
HOSTFN2(BS(C2ERKS5_mmRKS4_)) { substr_ctor(c); }
static void gs_dtor(Cpu *c) { if (gs_long(X(0))) rt_free((void *)(uintptr_t)LD64(X(0) + 16)); }
HOSTFN2(BS(D1Ev)) { gs_dtor(c); }
HOSTFN2(BS(D2Ev)) { gs_dtor(c); }
HOSTFN2(BS(6appendEPKc)) { gs_replace(X(0), gs_size(X(0)), 0, STR(1), strlen(STR(1))); }
HOSTFN2(BS(6appendEPKcm)) { gs_replace(X(0), gs_size(X(0)), 0, STR(1), X(2)); }
HOSTFN2(BS(6appendEmc)) {
    uint64_t s = X(0);
    size_t sz = gs_size(s), n = X(1);
    gs_grow(s, sz + n);
    memset(gs_data(s) + sz, (int)W(2), n);
    gs_set_size(s, sz + n);
}
HOSTFN2(BS(9push_backEc)) {
    uint64_t s = X(0);
    size_t sz = gs_size(s);
    gs_grow(s, sz + 1);
    gs_data(s)[sz] = (char)W(1);
    gs_set_size(s, sz + 1);
}
HOSTFN2(BS(6assignEPKc)) { gs_replace(X(0), 0, (size_t)-1, STR(1), strlen(STR(1))); }
HOSTFN2(BS(6assignEPKcm)) { gs_replace(X(0), 0, (size_t)-1, STR(1), X(2)); }
HOSTFN2(BS(aSERKS5_)) { if (X(0) != X(1)) gs_replace(X(0), 0, (size_t)-1, gs_data(X(1)), gs_size(X(1))); }
HOSTFN2(BS(6insertEmPKc)) { gs_replace(X(0), X(1), 0, STR(2), strlen(STR(2))); }
HOSTFN2(BS(6insertEmPKcm)) { gs_replace(X(0), X(1), 0, STR(2), X(3)); }
HOSTFN2(BS(5eraseEmm)) { gs_replace(X(0), X(1), X(2), NULL, 0); }
HOSTFN2(BS(7reserveEm)) { gs_grow(X(0), X(1)); }
HOSTFN2(BS(6resizeEmc)) {
    uint64_t s = X(0);
    size_t sz = gs_size(s), n = X(1);
    if (n > sz) { gs_grow(s, n); memset(gs_data(s) + sz, (int)W(2), n - sz); }
    gs_set_size(s, n);
}
// __grow_by(old_cap, delta_cap, old_sz, n_copy, n_del, n_add): reallocate to at least old_cap + delta_cap, copying
// n_copy characters, leaving a gap of n_add and then the tail after n_del. The size is not updated (caller does).
HOSTFN2(BS(9__grow_byEmmmmmm)) {
    uint64_t s = X(0);
    size_t old_cap = X(1), delta = X(2), old_sz = X(3), n_copy = X(4), n_del = X(5), n_add = X(6);
    size_t want = old_cap + delta;
    if (want < old_cap * 2) want = old_cap * 2;
    size_t alloc = (want + 16) & ~15ull;
    char *d = rt_malloc(alloc), *old = gs_data(s);
    if (n_copy) memcpy(d, old, n_copy);
    size_t tail = old_sz - n_del - n_copy;
    if (tail) memcpy(d + n_copy + n_add, old + n_copy + n_del, tail);
    if (gs_long(s)) rt_free(old);
    ST64(s + 16, (uint64_t)(uintptr_t)d);
    ST64(s, alloc | 1);
}
HOSTFN2(BSK(4findEcm)) {
    size_t sz = gs_size(X(0)), pos = X(2);
    const char *d = gs_data(X(0)), *r = pos < sz ? memchr(d + pos, (int)W(1), sz - pos) : NULL;
    RET(r ? (uint64_t)(r - d) : ~0ull);
}
HOSTFN2(BSK(5rfindEcm)) {
    size_t sz = gs_size(X(0)), pos = X(2);
    const char *d = gs_data(X(0));
    if (!sz) { RET(~0ull); return; }
    if (pos >= sz) pos = sz - 1;
    for (size_t i = pos + 1; i-- > 0;)
        if (d[i] == (char)W(1)) { RET(i); return; }
    RET(~0ull);
}
HOSTFN2(BSK(7compareEPKc)) {
    size_t a = gs_size(X(0)), b = strlen(STR(1));
    int r = memcmp(gs_data(X(0)), STR(1), a < b ? a : b);
    RET((int64_t)(r ? r : a < b ? -1 : a > b));
}
// operator+(const char *, const std::string &): result through x8.
HOSTFN(_ZNSt3__1plIcNS_11char_traitsIcEENS_9allocatorIcEEEENS_12basic_stringIT_T0_T1_EEPKS6_RKS9_) {
    uint64_t out = X(8), rhs = X(1);
    const char *lhs = STR(0);
    size_t a = strlen(lhs), b = gs_size(rhs);
    char *tmp = rt_malloc(a + b + 1);
    memcpy(tmp, lhs, a);
    memcpy(tmp + a, gs_data(rhs), b);
    gs_init(out, tmp, a + b);
    rt_free(tmp);
}

// ---- std exception classes constructed by lifted code. The vtables are imported data blocks (loader.c); what()
// and the destructors are only reached when such an exception is destroyed or printed.
static void set_vptr(uint64_t obj, const char *vtable_sym) {
    uint64_t vt = rt_sym_addr(vtable_sym);
    if (vt) ST64(obj, vt + 16);
}
static void logic_error_ctor(Cpu *c) {   // {vptr, __libcpp_refstring}: chars preceded by {len, cap, count}
    const char *msg = STR(1);
    size_t n = strlen(msg);
    uint64_t *rep = rt_malloc(24 + n + 1);
    rep[0] = n; rep[1] = n; rep[2] = 0;
    memcpy(rep + 3, msg, n + 1);
    set_vptr(X(0), "_ZTVSt11logic_error");
    ST64(X(0) + 8, (uint64_t)(uintptr_t)(rep + 3));
}
HOSTFN(_ZNSt11logic_errorC2EPKc) { logic_error_ctor(c); }
HOSTFN(_ZNSt11logic_errorC1EPKc) { logic_error_ctor(c); }
HOSTFN(_ZNSt13runtime_errorC2EPKc) { logic_error_ctor(c); set_vptr(X(0), "_ZTVSt13runtime_error"); }
HOSTFN(_ZNSt20bad_array_new_lengthC1Ev) { set_vptr(X(0), "_ZTVSt20bad_array_new_length"); }
HOSTFN(_ZNSt8bad_castC1Ev) { set_vptr(X(0), "_ZTVSt8bad_cast"); }
HOSTFN(_ZNSt9bad_allocC1Ev) { set_vptr(X(0), "_ZTVSt9bad_alloc"); }
HOSTFN(_ZNSt9exceptionD2Ev) { (void)c; }
HOSTALIAS(_ZNSt9exceptionD1Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt12length_errorD1Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt12out_of_rangeD1Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt20bad_array_new_lengthD1Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt8bad_castD1Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt11logic_errorD2Ev, _ZNSt9exceptionD2Ev)
HOSTALIAS(_ZNSt13runtime_errorD2Ev, _ZNSt9exceptionD2Ev)
HOSTFN(_ZNKSt9exception4whatEv) { RET("std::exception"); }
