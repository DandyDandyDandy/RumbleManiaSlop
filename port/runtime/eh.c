// Guest C++ exceptions (Itanium ABI surface) on top of the return-based unwinding described in include/eh.h.
// The exception header is private to this file: every function that touches it (__cxa_*, _Unwind_*, the
// std::exception_ptr members) is an import and therefore implemented here.
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include "rt.h"

#define HDR 0x80
struct RtExc {
    uint64_t magic;
    uint64_t tinfo, dtor;
    int32_t handlers, refs;
    uint64_t adjusted;             // pointer handed to the handler (set when a catch matches)
    struct RtExc *next_caught;
    struct RtExc *primary;         // dependent exception (std::rethrow_exception): the exception it refers to
    uint64_t pad[9];
};
_Static_assert(sizeof(struct RtExc) == HDR, "exception header size");
#define EXC_MAGIC 0x4255524e45584321ull

static inline RtExc *hdr_of(uint64_t obj) { return (RtExc *)(uintptr_t)(obj - HDR); }
static inline uint64_t obj_of(RtExc *h) { return (uint64_t)(uintptr_t)((h->primary ? h->primary : h) + 1); }
static RtExc *checked(Cpu *c, uint64_t e, const char *who) {
    RtExc *h = (RtExc *)(uintptr_t)e;
    if (!h || h->magic != EXC_MAGIC) rt_fatal_c(c, "%s: %#llx is not an exception of this runtime", who, (unsigned long long)e);
    return h;
}

static void exc_release(Cpu *c, RtExc *h) {   // h is a primary header
    if (InterlockedDecrement((volatile LONG *)&h->refs) > 0) return;
    if (h->dtor) {
        uint64_t unwinding = c->eh_unwinding, exc = c->eh_exc;
        c->eh_unwinding = 0;
        rt_call(c, h->dtor, 1, obj_of(h));
        c->eh_unwinding = unwinding;
        c->eh_exc = exc;
    }
    h->magic = 0;
    rt_free(h);
}

HOSTFN(__cxa_allocate_exception) {
    size_t n = X(0);
    RtExc *h = rt_malloc(HDR + n);
    memset(h, 0, HDR + n);
    h->magic = EXC_MAGIC;
    RET(h + 1);
}
HOSTFN(__cxa_free_exception) { RtExc *h = hdr_of(X(0)); h->magic = 0; rt_free(h); }

void rt_eh_throw(Cpu *c, uint64_t obj, uint64_t tinfo, uint64_t dtor) {
    RtExc *h = hdr_of(obj);
    if (h->magic != EXC_MAGIC) rt_fatal_c(c, "__cxa_throw: object %#llx was not allocated by __cxa_allocate_exception", (unsigned long long)obj);
    h->tinfo = tinfo;
    h->dtor = dtor;
    h->refs = 1;
    ((RtThread *)c)->uncaught++;
    c->eh_exc = (uint64_t)(uintptr_t)h;
    c->eh_unwinding = 1;
    if (rt_trace & 1) { char b[512]; rt_log("throw: %s", rt_eh_describe(c, b, sizeof b)); }
}
HOSTFN(__cxa_throw) { rt_eh_throw(c, X(0), X(1), X(2)); }
HOSTFN(_Unwind_Resume) { checked(c, X(0), "_Unwind_Resume"); c->eh_exc = X(0); c->eh_unwinding = 1; }

HOSTFN(__cxa_begin_catch) {
    RtThread *t = (RtThread *)c;
    RtExc *h = checked(c, X(0), "__cxa_begin_catch");
    h->handlers = h->handlers < 0 ? -h->handlers + 1 : h->handlers + 1;
    if (h != t->caught) { h->next_caught = t->caught; t->caught = h; }
    if (t->uncaught) t->uncaught--;
    if (!h->adjusted) h->adjusted = obj_of(h);
    RET(h->adjusted);
}
HOSTFN(__cxa_get_exception_ptr) { RtExc *h = checked(c, X(0), "__cxa_get_exception_ptr"); RET(h->adjusted ? h->adjusted : obj_of(h)); }
HOSTFN(__cxa_end_catch) {
    RtThread *t = (RtThread *)c;
    RtExc *h = t->caught;
    if (!h) return;
    if (h->handlers < 0) {
        if (++h->handlers == 0) t->caught = h->next_caught;   // rethrown: still in flight, not destroyed
        return;
    }
    if (--h->handlers) return;
    t->caught = h->next_caught;
    if (h->primary) {
        RtExc *p = h->primary;
        h->magic = 0;
        rt_free(h);
        exc_release(c, p);
    } else exc_release(c, h);
}
HOSTFN(__cxa_rethrow) {
    RtThread *t = (RtThread *)c;
    RtExc *h = t->caught;
    if (!h) rt_fatal_c(c, "__cxa_rethrow with no caught exception (std::terminate)");
    h->handlers = -h->handlers;
    t->uncaught++;
    c->eh_exc = (uint64_t)(uintptr_t)h;
    c->eh_unwinding = 1;
}
HOSTFN(__cxa_current_exception_type) { RtThread *t = (RtThread *)c; RET(t->caught ? t->caught->tinfo : 0); }
HOSTFN(_ZSt9terminatev) { rt_fatal_c(c, "guest called std::terminate()"); }
HOSTFN(__cxa_pure_virtual) { rt_fatal_c(c, "guest called a pure virtual function"); }
HOSTFN(_ZSt18uncaught_exceptionv) { RET(((RtThread *)c)->uncaught != 0); }

// std::exception_ptr: one pointer to the thrown object, reference counted in the header.
HOSTFN(_ZSt17current_exceptionv) {
    RtThread *t = (RtThread *)c;
    RtExc *h = t->caught;
    if (h && h->primary) h = h->primary;
    if (h) InterlockedIncrement((volatile LONG *)&h->refs);
    ST64(X(8), h ? obj_of(h) : 0);
}
HOSTFN(_ZNSt13exception_ptrC1ERKS_) {
    uint64_t o = LD64(X(1));
    ST64(X(0), o);
    if (o) InterlockedIncrement((volatile LONG *)&hdr_of(o)->refs);
}
HOSTALIAS(_ZNSt13exception_ptrC2ERKS_, _ZNSt13exception_ptrC1ERKS_)
HOSTFN(_ZNSt13exception_ptrD1Ev) {
    uint64_t self = X(0), o = LD64(self);
    if (o) exc_release(c, hdr_of(o));
    ST64(self, 0);
    RET(self);
}
HOSTALIAS(_ZNSt13exception_ptrD2Ev, _ZNSt13exception_ptrD1Ev)
HOSTFN(_ZNSt13exception_ptraSERKS_) {
    uint64_t self = X(0), o = LD64(X(1)), old = LD64(self);
    if (o != old) {
        if (o) InterlockedIncrement((volatile LONG *)&hdr_of(o)->refs);
        ST64(self, o);
        if (old) exc_release(c, hdr_of(old));
    }
    RET(self);
}
HOSTFN(_ZSt17rethrow_exceptionSt13exception_ptr) {
    uint64_t o = LD64(X(0));
    if (!o) rt_fatal_c(c, "std::rethrow_exception(nullptr)");
    RtExc *p = hdr_of(o), *d = rt_malloc(HDR);
    memset(d, 0, HDR);
    d->magic = EXC_MAGIC;
    d->primary = p;
    d->tinfo = p->tinfo;
    InterlockedIncrement((volatile LONG *)&p->refs);
    ((RtThread *)c)->uncaught++;
    c->eh_exc = (uint64_t)(uintptr_t)d;
    c->eh_unwinding = 1;
}

// ---- type matching against guest type_info objects
static uint64_t g_vt_class, g_vt_si, g_vt_vmi, g_vt_ptr;
static void vt_init(void) {
    static int done;
    if (done) return;
    g_vt_class = rt_sym_addr("_ZTVN10__cxxabiv117__class_type_infoE");
    g_vt_si = rt_sym_addr("_ZTVN10__cxxabiv120__si_class_type_infoE");
    g_vt_vmi = rt_sym_addr("_ZTVN10__cxxabiv121__vmi_class_type_infoE");
    g_vt_ptr = rt_sym_addr("_ZTVN10__cxxabiv119__pointer_type_infoE");
    done = 1;
}
static const char *ti_name(uint64_t ti) { return ti ? (const char *)(uintptr_t)LD64(ti + 8) : "<catch-all>"; }
static int ti_same(uint64_t a, uint64_t b) { return a == b || !strcmp(ti_name(a), ti_name(b)); }

// Does `thrown` derive from (or equal) `want`? *adj receives the pointer adjustment to the base subobject.
static int ti_derives(uint64_t thrown, uint64_t want, uint64_t obj, int64_t *adj, int depth) {
    if (ti_same(thrown, want)) return 1;
    if (depth > 16) return 0;
    uint64_t vt = LD64(thrown) - 16;
    if (g_vt_si && vt == g_vt_si) return ti_derives(LD64(thrown + 16), want, obj, adj, depth + 1);
    if (g_vt_vmi && vt == g_vt_vmi) {
        uint32_t n = LD32(thrown + 20);
        for (uint32_t i = 0; i < n; i++) {
            uint64_t base = LD64(thrown + 24 + 16 * i);
            int64_t of = (int64_t)LD64(thrown + 32 + 16 * i);
            if (!(of & 2)) continue;                       // not public
            int64_t off = of >> 8, sub = 0;
            if (of & 1) off = (int64_t)LD64(LD64(obj + *adj) + off);   // virtual base: offset from the vtable
            int64_t saved = *adj;
            *adj += off;
            if (ti_derives(base, want, obj, &sub, depth + 1)) { *adj += sub; return 1; }
            *adj = saved;
        }
    }
    return 0;
}
static int can_catch(uint64_t want, RtExc *h, uint64_t *adjusted) {
    uint64_t obj = obj_of(h);
    *adjusted = obj;
    if (!want) return 1;
    vt_init();
    uint64_t thrown = h->tinfo;
    if (ti_same(thrown, want)) return 1;
    uint64_t wvt = LD64(want) - 16, tvt = LD64(thrown) - 16;
    if (g_vt_ptr && wvt == g_vt_ptr && tvt == g_vt_ptr) {   // pointer to derived caught as pointer to base
        int64_t adj = 0;
        uint64_t p = LD64(obj);
        if (ti_derives(LD64(thrown + 24), LD64(want + 24), p, &adj, 0)) {
            if (p) ST64(obj, p + adj);
            return 1;
        }
        return 0;
    }
    int64_t adj = 0;
    if (ti_derives(thrown, want, obj, &adj, 0)) { *adjusted = obj + adj; return 1; }
    return 0;
}

static uint64_t uleb(uint64_t *p) {
    uint64_t v = 0;
    int sh = 0;
    uint8_t b;
    do { b = LD8((*p)++); v |= (uint64_t)(b & 0x7f) << sh; sh += 7; } while (b & 0x80);
    return v;
}
static int64_t sleb(uint64_t *p) {
    int64_t v = 0;
    int sh = 0;
    uint8_t b;
    do { b = LD8((*p)++); v |= (int64_t)(b & 0x7f) << sh; sh += 7; } while (b & 0x80);
    if (sh < 64 && (b & 0x40)) v |= -((int64_t)1 << sh);
    return v;
}
static uint64_t read_enc(uint64_t *p, uint8_t enc) {
    uint64_t at = *p, v;
    switch (enc & 0x0f) {
    case 0x00: case 0x04: v = LD64(at); *p += 8; break;
    case 0x0c: v = LD64(at); *p += 8; break;
    case 0x03: v = LD32(at); *p += 4; break;
    case 0x0b: v = (uint64_t)(int64_t)(int32_t)LD32(at); *p += 4; break;
    case 0x02: v = LD16(at); *p += 2; break;
    case 0x0a: v = (uint64_t)(int64_t)(int16_t)LD16(at); *p += 2; break;
    case 0x01: v = uleb(p); break;
    case 0x09: v = (uint64_t)sleb(p); break;
    default: rt_fatal("LSDA: unsupported pointer encoding %#x", enc);
    }
    if (!v) return 0;
    if ((enc & 0x70) == 0x10) v += at;
    if (enc & 0x80) v = LD64(v);
    return v;
}
static unsigned enc_size(uint8_t enc) {
    switch (enc & 0x0f) {
    case 0x02: case 0x0a: return 2;
    case 0x03: case 0x0b: return 4;
    default: return 8;
    }
}

int rt_eh_enter(Cpu *c, uint64_t lsda, uint32_t action) {
    RtExc *h = checked(c, c->eh_exc, "rt_eh_enter");
    int64_t selector = 0;
    if (action) {
        uint64_t p = lsda, ttype = 0;
        uint8_t lp_enc = LD8(p++);
        if (lp_enc != 0xff) read_enc(&p, lp_enc);
        uint8_t tt_enc = LD8(p++);
        if (tt_enc != 0xff) { uint64_t off = uleb(&p); ttype = p + off; }
        p++;                                   // call-site encoding
        uint64_t cs_len = uleb(&p);
        uint64_t actions = p + cs_len, rec = actions + action - 1;
        int cleanup = 0, found = 0;
        for (;;) {
            uint64_t q = rec;
            int64_t filter = sleb(&q);
            uint64_t next_at = q;
            int64_t next = sleb(&q);
            if (filter > 0) {
                uint64_t ent = ttype - (uint64_t)filter * enc_size(tt_enc), adjusted;
                uint64_t want = read_enc(&ent, tt_enc);
                if (can_catch(want, h, &adjusted)) {
                    h->adjusted = adjusted;
                    selector = filter;
                    found = 1;
                    break;
                }
            } else if (filter == 0) {
                cleanup = 1;
            } else {
                // Exception specification: the list of allowed types is in the type table at ttype - filter - 1 (ULEB
                // indices, 0-terminated). Enter the pad (which calls __cxa_call_unexpected) when the type is not listed.
                uint64_t lst = ttype + (uint64_t)(-filter) - 1, adjusted;
                int allowed = 0;
                for (uint64_t idx; (idx = uleb(&lst)) != 0;) {
                    uint64_t ent = ttype - idx * enc_size(tt_enc);
                    if (can_catch(read_enc(&ent, tt_enc), h, &adjusted)) { allowed = 1; break; }
                }
                if (!allowed) { selector = filter; found = 1; break; }
            }
            if (!next) break;
            rec = next_at + (uint64_t)next;
        }
        if (!found && !cleanup) return 0;
    }
    c->x[0] = c->eh_exc;
    c->x[1] = (uint64_t)selector;
    c->eh_unwinding = 0;
    return 1;
}

static int safe_read(uint64_t a, size_t n) { return a > 0x10000 && !IsBadReadPtr((void *)(uintptr_t)a, n); }

const char *rt_eh_describe(Cpu *c, char *buf, int size) {
    RtExc *h = (RtExc *)(uintptr_t)c->eh_exc;
    if (!h || !safe_read(c->eh_exc, HDR) || h->magic != EXC_MAGIC) { snprintf(buf, size, "<no exception>"); return buf; }
    const char *tn = h->tinfo && safe_read(h->tinfo, 16) ? ti_name(h->tinfo) : "?";
    int n = snprintf(buf, size, "C++ type %s", tn);
    if (strstr(tn, "Il2CppExceptionWrapper")) {
        uint64_t ex = LD64(obj_of(h));
        if (safe_read(ex, 0x20)) {
            uint64_t klass = LD64(ex), msg = LD64(ex + 0x18);
            if (safe_read(klass, 0x20)) {
                const char *name = (const char *)(uintptr_t)LD64(klass + 0x10), *ns = (const char *)(uintptr_t)LD64(klass + 0x18);
                if (safe_read((uint64_t)(uintptr_t)name, 1) && safe_read((uint64_t)(uintptr_t)ns, 1))
                    n += snprintf(buf + n, n < size ? size - n : 0, ": managed %s.%s", ns, name);
            }
            if (safe_read(msg, 0x18) && n < size - 8) {
                uint32_t len = LD32(msg + 0x10);
                if (len < 400 && safe_read(msg + 0x14, len * 2)) {
                    n += snprintf(buf + n, size - n, ": ");
                    for (uint32_t i = 0; i < len && n < size - 2; i++) {
                        uint16_t ch = LD16(msg + 0x14 + 2 * i);
                        buf[n++] = ch >= 32 && ch < 127 ? (char)ch : '?';
                    }
                    buf[n] = 0;
                }
            }
        }
    }
    return buf;
}
