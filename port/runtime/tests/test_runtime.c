// Stand-alone tests of the host runtime (no generated code): python build_runtime.py --test
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

// A tiny "lifted" table: two fake guest functions inside the image range.
static void f_sum(Cpu *c) { c->x[0] = c->x[0] + c->x[1] + c->x[2] + c->x[3] + c->x[4] + c->x[5]; }
static void f_thrower(Cpu *c) {   // allocates and throws a guest exception whose type_info is in x1
    uint64_t ti = c->x[1];
    uint64_t obj = rt_call(c, rt_sym_addr("__cxa_allocate_exception"), 1, 8ull);
    rt_eh_throw(c, obj, ti, 0);
}
#define A_SUM (GUEST_BASE + 0x100000)
#define A_THROW (GUEST_BASE + 0x100010)
const uint64_t main_fn_addrs[] = {A_SUM, A_THROW};
const GuestFn main_fn_ptrs[] = {f_sum, f_thrower};
const uint64_t main_fn_count = 2;
const struct { uint64_t addr; const char *kind; const char *name; } rt_boundary_info[] = {{GUEST_BASE + 0x473050, "pinvoke", "native for Test::X"}};
const uint64_t rt_boundary_count = 1;

static int fails;
#define CHECK(cond, what) do { if (cond) printf("ok   %s\n", what); else { printf("FAIL %s\n", what); fails++; } } while (0)

static double host_mixed(int a, double b, float c3, void *d, long long e, double f, int g, float h, long long i, void *j) {
    return a + b + c3 + (double)(uintptr_t)d + (double)e + f + g + h + (double)i + (double)(uintptr_t)j;
}
typedef struct { float x, y, z; } V3;
typedef struct { uint64_t a, b; } P16;
static V3 host_icall(void *self, float f, double d, P16 p, V3 v, int n, long long a7, long long a8, long long a9, long long a10) {
    V3 r = {f + v.x + (float)p.a, (float)d + v.y + (float)p.b, (float)n + v.z + (float)(a7 + a8 + a9 + a10) + (self ? 1 : 0)};
    return r;
}
void rt_icall_marshal(Cpu *c, void *host, const char *sig);

static int cmp_throw(const void *a, const void *b) {
    (void)a; (void)b;
    rt_cpu()->eh_unwinding = 1;   // pretend a managed exception was raised by engine code
    rt_host_unwind();
}
static void body_qsort(Cpu *c, void *user) {
    (void)user;
    int v[8] = {5, 3, 8, 1, 9, 2, 7, 4};
    uint64_t slots[4] = {(uint64_t)(uintptr_t)v, 8, sizeof(int), (uint64_t)(uintptr_t)cmp_throw};
    rt_win64_call((void *)qsort, slots, 4, NULL);   // ucrtbase!qsort: MSVC-compiled frames between throw and catch
    c->x[0] = 12345;                                 // must not be reached
}

int main(int argc, char **argv) {
    if (argc > 1) _putenv_s("BR_IMAGE", argv[1]);
    rt_log_init();
    rt_dispatch_init();
    rt_load_image();
    Cpu *c = rt_cpu();

    // loader / relocations against the real image
    CHECK(LD64(GUEST_BASE + 0x5f43d18 + 7 * 8) == GUEST_BASE + 0x5f86c58, "RELR: g_MetadataRegistration.types relocated");
    CHECK(rt_syn_entry(LD64(GUEST_BASE + 0x61531b8)) != NULL, "JUMP_SLOT of open bound to a synthetic host address");
    CHECK(rt_sym_addr("memcpy") && rt_sym_addr("__cxa_throw") && rt_sym_addr("_ZTVN10__cxxabiv117__class_type_infoE"), "imports bound by name");

    // trampoline: integers, floats and doubles in register and stack positions
    uint64_t s[10], xr = 0;
    double db = 2.5, df = 6.25;
    float fc = 3.5f, fh = 8.5f;
    memset(s, 0, sizeof s);
    s[0] = 1; memcpy(&s[1], &db, 8); memcpy(&s[2], &fc, 4); s[3] = 4; s[4] = 5; memcpy(&s[5], &df, 8); s[6] = 7; memcpy(&s[7], &fh, 4); s[8] = 9; s[9] = 10;
    rt_win64_call((void *)host_mixed, s, 10, &xr);
    double got;
    memcpy(&got, &xr, 8);
    CHECK(got == 1 + 2.5 + 3.5 + 4 + 5 + 6.25 + 7 + 8.5 + 9 + 10, "rt_win64_call: 10 mixed arguments, double return");

    // icall marshalling: this, float, double, 16-byte aggregate, HFA, int, stack ints; HFA return through hidden pointer
    memset(c->x, 0, 8 * 8);
    c->x[0] = 0x1234; rt_setf(c, 0, 1.0f); rt_setd(c, 1, 2.0); c->x[1] = 10; c->x[2] = 20;
    rt_setf(c, 2, 100.0f); rt_setf(c, 3, 200.0f); rt_setf(c, 4, 300.0f); c->x[3] = 7; c->x[4] = 1; c->x[5] = 2; c->x[6] = 3; c->x[7] = 4;
    rt_icall_marshal(c, (void *)host_icall, "H3f:ifdA16.H3fiiiii");
    CHECK(rt_getf(c, 0) == 111.0f && rt_getf(c, 1) == 222.0f && rt_getf(c, 2) == 318.0f, "icall thunk: AAPCS64 -> Win64 with aggregates and HFA return");

    // host -> guest and the host-callable callback stub
    CHECK(rt_call(c, A_SUM, 6, 1ull, 2ull, 3ull, 4ull, 5ull, 6ull) == 21, "rt_call into a lifted function");
    long long (*cb)(long long, long long, long long, long long, long long, long long) = rt_guest_callback(A_SUM, NULL);
    CHECK(cb(10, 20, 30, 40, 50, 60) == 210, "host-callable stub for a guest function (6 integer arguments)");

    // std::string helpers on the guest layout
    uint64_t str[3] = {0}, str2[3] = {0};
#define BSN "_ZNSt3__112basic_stringIcNS_11char_traitsIcEENS_9allocatorIcEEE"
    rt_call(c, rt_sym_addr(BSN "6appendEPKc"), 2, (uint64_t)(uintptr_t)str, (uint64_t)(uintptr_t)"short");
    int short_ok = ((uint8_t *)str)[0] == 5 << 1 && !strcmp((char *)str + 1, "short");
    rt_call(c, rt_sym_addr(BSN "6appendEPKc"), 2, (uint64_t)(uintptr_t)str, (uint64_t)(uintptr_t)" and now a long string beyond 22 chars");
    rt_call(c, rt_sym_addr(BSN "6insertEmPKc"), 3, (uint64_t)(uintptr_t)str, 0ull, (uint64_t)(uintptr_t)">> ");
    rt_call(c, rt_sym_addr(BSN "C1ERKS5_"), 2, (uint64_t)(uintptr_t)str2, (uint64_t)(uintptr_t)str);
    CHECK(short_ok && (str[0] & 1) && str[1] == 46 && !strcmp((char *)(uintptr_t)str2[2], ">> short and now a long string beyond 22 chars"),
          "libc++ std::string append/insert/copy (SSO and long form)");
    char out[64];
    c->x[0] = (uint64_t)(uintptr_t)out; c->x[1] = sizeof out; c->x[2] = (uint64_t)(uintptr_t)"%s=%d %5.2f %lx"; c->x[3] = (uint64_t)(uintptr_t)"v";
    c->x[4] = (uint64_t)-3; rt_setd(c, 0, 3.14159); c->x[5] = 0xdeadbeefcafeull;
    rt_call_regs(c, rt_sym_addr("snprintf"));
    CHECK(!strcmp(out, "v=-3  3.14 deadbeefcafe"), "guest snprintf with AAPCS64 variadic arguments");

    // exceptions: synthetic type_info objects and LSDA; action chain {catch T2} -> {catch T1}; cleanup-only record
    uint64_t vt = rt_sym_addr("_ZTVN10__cxxabiv117__class_type_infoE") + 16;
    uint64_t t1[2] = {vt, (uint64_t)(uintptr_t)"2T1"}, t2[2] = {vt, (uint64_t)(uintptr_t)"2T2"};
    static struct __attribute__((packed)) { uint8_t lpstart, ttenc, ttoff, csenc, cslen, actions[6]; uint8_t pad[5]; uint64_t types[2]; } lsda;
    lsda.lpstart = 0xff; lsda.ttenc = 0x00; lsda.csenc = 0x01; lsda.cslen = 0;
    lsda.ttoff = (uint8_t)((uint8_t *)&lsda.types[2] - (uint8_t *)&lsda.csenc);   // the type table grows down from its end
    uint8_t acts[6] = {2, 1, 1, 0, 0, 0};
    memcpy(lsda.actions, acts, 6);
    lsda.types[1] = (uint64_t)(uintptr_t)t1;   // filter 1
    lsda.types[0] = (uint64_t)(uintptr_t)t2;   // filter 2
    c->x[1] = (uint64_t)(uintptr_t)t1;
    rt_call_regs(c, A_THROW);
    CHECK(c->eh_unwinding == 1, "__cxa_throw sets eh_unwinding and returns; rt_call comes back unwinding");
    uint64_t exc = c->eh_exc;
    int entered = rt_eh_enter(c, (uint64_t)(uintptr_t)&lsda, 1);
    CHECK(entered && c->x[1] == 1 && c->x[0] == exc && !c->eh_unwinding, "rt_eh_enter: skips catch(T2), enters catch(T1) with selector 1");
    uint64_t obj = rt_call(c, rt_sym_addr("__cxa_begin_catch"), 1, exc);
    CHECK(obj == exc + 0x80, "__cxa_begin_catch returns the thrown object");
    rt_call(c, rt_sym_addr("__cxa_rethrow"), 0);
    int unw = c->eh_unwinding == 1;
    CHECK(unw && rt_eh_enter(c, (uint64_t)(uintptr_t)&lsda, 0) && c->x[1] == 0, "__cxa_rethrow, then a cleanup-only record enters with selector 0");
    rt_call(c, rt_sym_addr("__cxa_end_catch"), 0);
    rt_call(c, rt_sym_addr("_Unwind_Resume"), 1, exc);
    uint8_t only_t2[2] = {2, 0};
    memcpy(lsda.actions, only_t2, 2);
    unw = c->eh_unwinding == 1;
    CHECK(unw && !rt_eh_enter(c, (uint64_t)(uintptr_t)&lsda, 1) && c->eh_unwinding == 1, "rt_eh_enter: no matching handler keeps unwinding");
    c->eh_unwinding = 0;

    // host unwind through MSVC-compiled frames (ucrtbase qsort) to the thunk
    c->x[0] = 0;
    uint64_t sp = c->sp;
    rt_thunk_run(c, body_qsort, NULL);
    CHECK(c->eh_unwinding == 1 && c->x[0] != 12345 && c->sp == sp && ((RtThread *)c)->thunk_depth == 0,
          "host C++ unwind crosses rt_win64_call and ucrtbase (MSVC) frames into the thunk");
    c->eh_unwinding = 0;

    // ---- platform layer (imports_fs.c, imports_audio.c, imports_hid.c, imports_plat.c, pinvoke_policy.c)
    #define HOST(sym) (rt_hostfn_find(sym)(c))
    #define P(x) ((uint64_t)(uintptr_t)(x))
    static char uid[16], path[64], data[32] = "banana rumble save data", back[32];
    static uint64_t fhnd, dh, n64;
    static uint8_t entries[2 * 0x310];
    c->x[0] = P("TST"); c->x[1] = P(uid);
    HOST("_ZN2nn2fs13MountSaveDataEPKcRKNS_7account3UidE");
    int mounted = c->x[0] == 0;
    strcpy(path, "TST:/unit_test.bin");
    c->x[0] = P(path); HOST("_ZN2nn2fs10DeleteFileEPKc");
    c->x[0] = P(path); c->x[1] = 0; HOST("_ZN2nn2fs10CreateFileEPKcl");
    int created = c->x[0] == 0;
    c->x[0] = P(&fhnd); c->x[1] = P(path); c->x[2] = 7; HOST("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci");
    int opened = c->x[0] == 0;
    c->x[0] = fhnd; c->x[1] = 0; c->x[2] = P(data); c->x[3] = 24; c->x[4] = P(&n64);
    HOST("_ZN2nn2fs9WriteFileENS0_10FileHandleElPKvmRKNS0_11WriteOptionE");
    c->x[0] = P(&n64); c->x[1] = fhnd; HOST("_ZN2nn2fs11GetFileSizeEPlNS0_10FileHandleE");
    int sized = n64 == 24;
    c->x[0] = P(&n64); c->x[1] = fhnd; c->x[2] = 7; c->x[3] = P(back); c->x[4] = 32;
    HOST("_ZN2nn2fs8ReadFileEPmNS0_10FileHandleElPvm");
    int readok = n64 == 17 && !memcmp(back, "rumble save data", 17);
    c->x[0] = fhnd; HOST("_ZN2nn2fs9CloseFileENS0_10FileHandleE");
    CHECK(mounted && created && opened && sized && readok, "nn::fs: save-data mount, create, write, size, read at offset");
    c->x[0] = P(&dh); c->x[1] = P("TST:/"); c->x[2] = 2; HOST("_ZN2nn2fs13OpenDirectoryEPNS0_15DirectoryHandleEPKci");
    int dopen = c->x[0] == 0, found = 0;
    for (;;) {
        c->x[0] = P(&n64); c->x[1] = P(entries); c->x[2] = dh; c->x[3] = 2;
        HOST("_ZN2nn2fs13ReadDirectoryEPlPNS0_14DirectoryEntryENS0_15DirectoryHandleEl");
        if (!n64) break;
        for (uint64_t i = 0; i < n64; i++)
            if (!strcmp((char *)entries + 0x310 * i, "unit_test.bin") && entries[0x310 * i + 0x304] == 1 && LD64(entries + 0x310 * i + 0x308) == 24) found = 1;
    }
    c->x[0] = dh; HOST("_ZN2nn2fs14CloseDirectoryENS0_15DirectoryHandleE");
    c->x[0] = P(path); HOST("_ZN2nn2fs10DeleteFileEPKc");
    int deleted = c->x[0] == 0;
    c->x[0] = P(&fhnd); c->x[1] = P(path); c->x[2] = 1; HOST("_ZN2nn2fs8OpenFileEPNS0_10FileHandleEPKci");
    int gone = c->x[0] == 0x202;
    c->x[0] = P("TST"); HOST("_ZN2nn2fs7UnmountEPKc");
    c->x[0] = P("TST"); HOST("_ZN2nn2fs9IsMountedEPKc");
    CHECK(dopen && found && deleted && gone && c->x[0] == 0, "nn::fs: directory listing, delete, PathNotFound, unmount");

    // AudioOut without a device (BR_AUDIO=off): a 0.05 s buffer is released by the clock and signals the event
    _putenv_s("BR_AUDIO", "off");
    static uint64_t aout[8], aev[8], abuf[8], aparam;
    static int16_t pcm[2400 * 2];
    c->x[0] = P(&aparam); HOST("_ZN2nn5audio27InitializeAudioOutParameterEPNS0_17AudioOutParameterE");
    c->x[0] = P(aout); c->x[1] = P(aev); c->x[2] = P(&aparam);
    HOST("_ZN2nn5audio19OpenDefaultAudioOutEPNS0_8AudioOutEPNS_2os11SystemEventERKNS0_17AudioOutParameterE");
    c->x[0] = P(abuf); c->x[1] = P(pcm); c->x[2] = sizeof pcm; c->x[3] = sizeof pcm;
    HOST("_ZN2nn5audio21SetAudioOutBufferInfoEPNS0_14AudioOutBufferEPvmm");
    c->x[0] = P(aout); c->x[1] = P(abuf); HOST("_ZN2nn5audio20AppendAudioOutBufferEPNS0_8AudioOutEPNS0_14AudioOutBufferE");
    int appended = c->x[0] == 1;
    c->x[0] = P(aout); HOST("_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE");
    int early = c->x[0] == 0;
    c->x[0] = P(aout); HOST("_ZN2nn5audio13StartAudioOutEPNS0_8AudioOutE");
    c->x[0] = P(aev); c->x[1] = 2000000000ull; HOST("_ZN2nn2os14TimedWaitEventEPNS0_9EventTypeENS_8TimeSpanE");
    int signalled = c->x[0] == 1;
    c->x[0] = P(aout); HOST("_ZN2nn5audio25GetReleasedAudioOutBufferEPNS0_8AudioOutE");
    int released = c->x[0] == P(abuf);
    c->x[0] = P(aout); HOST("_ZN2nn5audio13CloseAudioOutEPNS0_8AudioOutE");
    CHECK(appended && early && signalled && released, "nn::audio AudioOut (timed): append, release in order, buffer event");

    // npad: No.1 is a connected FullKey controller, No.2 is absent
    static uint32_t id0 = 0, id1 = 1;
    static uint8_t st[0x28];
    c->x[0] = P(&id0); HOST("_ZN2nn3hid15GetNpadStyleSetERKj");
    int style0 = c->x[0] == 1;
    c->x[0] = P(&id1); HOST("_ZN2nn3hid15GetNpadStyleSetERKj");
    int style1 = c->x[0] == 0;
    c->x[0] = P(st); c->x[1] = P(&id0); HOST("_ZN2nn3hid12GetNpadStateEPNS0_16NpadFullKeyStateERKj");
    int conn0 = (LD32(st + 0x20) & 1) && LD64(st) != 0;
    c->x[0] = P(st); c->x[1] = P(&id1); HOST("_ZN2nn3hid12GetNpadStateEPNS0_16NpadFullKeyStateERKj");
    CHECK(style0 && style1 && conn0 && !(LD32(st + 0x20) & 1), "nn::hid: npad No.1 connected as FullKey, No.2 absent");

    // language code by value, account, network
    HOST("_ZN2nn2oe18GetDesiredLanguageEv");
    uint64_t lang = c->x[0];
    static uint64_t handle[3], uid2[2];
    c->x[0] = P(handle); HOST("_ZN2nn7account22TryOpenPreselectedUserEPNS0_10UserHandleE");
    int open_ok = c->x[0] == 1;
    c->x[0] = P(uid2); c->x[1] = P(handle); HOST("_ZN2nn7account9GetUserIdEPNS0_3UidERKNS0_10UserHandleE");
    HOST("_ZN2nn4nifm18IsNetworkAvailableEv");
    CHECK(!memcmp(&lang, "en-US\0\0", 8) && open_ok && uid2[0] == handle[0] && uid2[0] && c->x[0] == 0,
          "platform policy: language en-US by value, one local user, no network");

    // P/Invoke policy table
    int rt_pinvoke_policy(Cpu *c, uint64_t addr, const char *name);
    c->x[0] = 77;
    int p1 = rt_pinvoke_policy(c, GUEST_BASE + 0x57b850, "native for MariaUpload.Lib::Maria_SetAppInformations") && c->x[0] == 0;
    int p2 = rt_pinvoke_policy(c, GUEST_BASE + 0x591490, "native for nn.npln.leaderboard.RankDataInterop::DtorImpl_0badf00d");
    int p3 = !rt_pinvoke_policy(c, GUEST_BASE + 0x5914a0, "native for nn.npln.leaderboard.RankDataInterop::GetIndexImpl");
    CHECK(p1 && p2 && p3, "P/Invoke policy: telemetry and NPLN destructors answered, an NPLN accessor is not");

    // a guest thread through nn::os::CreateThread
    static uint64_t tt[64];
    static uint8_t tstack[0x10000];
    c->x[0] = P(tt); c->x[1] = A_SUM; c->x[2] = 5; c->x[3] = P(tstack); c->x[4] = sizeof tstack; c->x[5] = 16;
    HOST("_ZN2nn2os12CreateThreadEPNS0_10ThreadTypeEPFvPvES3_S3_mi");
    int tcreated = c->x[0] == 0;
    c->x[0] = P(tt); HOST("_ZN2nn2os11StartThreadEPNS0_10ThreadTypeE");
    c->x[0] = P(tt); HOST("_ZN2nn2os10WaitThreadEPNS0_10ThreadTypeE");
    c->x[0] = P(tt); HOST("_ZN2nn2os13TryWaitThreadEPNS0_10ThreadTypeE");
    int tdone = c->x[0] == 1;
    c->x[0] = P(tt); HOST("_ZN2nn2os13DestroyThreadEPNS0_10ThreadTypeE");
    CHECK(tcreated && tdone, "nn::os: guest thread created on a guest stack, started, joined, destroyed");

    printf("%d failure(s)\n", fails);
    return fails != 0;
}
