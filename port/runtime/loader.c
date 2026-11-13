// Loads the flat image of the Switch executable `main` (never embedded: read at run time from
// <Name>_Data\il2cpp_data\main.bin) at GUEST_BASE, applies RELR and symbol relocations, binds undefined symbols to
// host functions by name and runs the static initialisers that belong to lifted code.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

uint64_t rt_image_size;

__attribute__((section(".hfn$a"), used)) static const RtHostDef hfn_start[1] = {{0, 0}};
__attribute__((section(".hfn$z"), used)) static const RtHostDef hfn_stop[1] = {{0, 0}};

typedef struct { const char *name; HostFn fn; } NameFn;
static NameFn *g_hfn;
static size_t g_nhfn;
static int namefn_cmp(const void *a, const void *b) { return strcmp(((const NameFn *)a)->name, ((const NameFn *)b)->name); }

HostFn rt_hostfn_find(const char *name) {
    if (!g_hfn) {
        // The section bounds are distinct objects to the compiler: launder them so the range is computed at run time.
        const RtHostDef *volatile lo_v = hfn_start + 1, *volatile hi_v = hfn_stop;
        const RtHostDef *lo = lo_v, *hi = hi_v;
        g_hfn = malloc(((size_t)(hi - lo) + 1) * sizeof *g_hfn);
        for (const RtHostDef *d = lo; d < hi; d++)
            if (d->name) { g_hfn[g_nhfn].name = d->name; g_hfn[g_nhfn++].fn = d->fn; }
        qsort(g_hfn, g_nhfn, sizeof *g_hfn, namefn_cmp);
        for (size_t i = 1; i < g_nhfn; i++)
            if (!strcmp(g_hfn[i].name, g_hfn[i - 1].name)) rt_fatal("host function %s defined twice", g_hfn[i].name);
    }
    NameFn key = {name, 0};
    NameFn *r = bsearch(&key, g_hfn, g_nhfn, sizeof *g_hfn, namefn_cmp);
    return r ? r->fn : NULL;
}

// ---- undefined-symbol bindings
typedef struct { const char *name; uint64_t addr; uint64_t data_lo, data_hi; } Binding;
static Binding *g_bind;
static size_t g_nbind, g_capbind;
static size_t g_bound_host, g_bound_trap, g_bound_data;

uint64_t rt_import_data(const char *name);   // imports_libc.c: storage for imported data symbols it knows, else 0

static void trap_import(Cpu *c) {
    SynEntry *e = rt_syn_entry(c->pc);
    rt_fatal_c(c, "call to unimplemented import %s", e ? e->name : "?");
}
static void trap_data(Cpu *c) {
    SynEntry *e = rt_syn_entry(c->pc);
    rt_fatal_c(c, "call through a slot of imported data symbol %s (not implemented)", e ? e->name : "?");
}

#define DATA_BLOCK_SLOTS 64
static uint64_t bind_symbol(const char *name, int type) {
    for (size_t i = 0; i < g_nbind; i++)
        if (!strcmp(g_bind[i].name, name)) return g_bind[i].addr;
    Binding b = {name, 0, 0, 0};
    HostFn f = rt_hostfn_find(name);
    if (f) {
        b.addr = rt_syn_alloc(f, name, NULL);
        g_bound_host++;
    } else if (type == 1 /* STT_OBJECT */ || !strncmp(name, "_ZTV", 4) || !strncmp(name, "_ZTI", 4)) {
        b.addr = rt_import_data(name);
        if (!b.addr) {
            // Unknown data (vtables of SDK classes, ...): a block whose every slot traps with the symbol's name.
            uint64_t trap = rt_syn_alloc(trap_data, name, NULL);
            uint64_t *blk = malloc(DATA_BLOCK_SLOTS * 8);
            for (int i = 0; i < DATA_BLOCK_SLOTS; i++) blk[i] = trap;
            b.addr = (uint64_t)(uintptr_t)blk;
        }
        b.data_lo = b.addr;
        b.data_hi = b.addr + DATA_BLOCK_SLOTS * 8;
        g_bound_data++;
    } else {
        b.addr = rt_syn_alloc(trap_import, name, NULL);
        g_bound_trap++;
    }
    if (g_nbind == g_capbind) {
        g_capbind = g_capbind ? g_capbind * 2 : 1024;
        g_bind = realloc(g_bind, g_capbind * sizeof *g_bind);
    }
    g_bind[g_nbind++] = b;
    return b.addr;
}

uint64_t rt_sym_addr(const char *name) {
    for (size_t i = 0; i < g_nbind; i++)
        if (!strcmp(g_bind[i].name, name)) return g_bind[i].addr;
    return 0;
}

const char *rt_syn_data_name(uint64_t addr) {
    for (size_t i = 0; i < g_nbind; i++)
        if (g_bind[i].data_lo && addr >= g_bind[i].data_lo && addr < g_bind[i].data_hi) return g_bind[i].name;
    return NULL;
}

// ---- image
static uint64_t g_init_array, g_init_count;

static void apply_rela(uint8_t *img, uint64_t rela, uint64_t size, uint64_t symtab, uint64_t strtab, uint64_t counts[4]) {
    for (uint64_t p = rela; p + 24 <= rela + size; p += 24) {
        uint64_t off = LD64(img + p), info = LD64(img + p + 8), addend = LD64(img + p + 16);
        uint32_t type = (uint32_t)info, symi = (uint32_t)(info >> 32);
        if (type == 0x403) {   // R_AARCH64_RELATIVE
            ST64(img + off, GUEST_BASE + addend);
            counts[0]++;
            continue;
        }
        if (type != 0x101 && type != 0x401 && type != 0x402) rt_fatal("loader: unsupported relocation type %#x at %#llx", type, (unsigned long long)off);
        const uint8_t *sym = img + symtab + 24ull * symi;
        uint32_t name = LD32(sym);
        uint8_t st_info = sym[4];
        uint16_t shndx = LD16(sym + 6);
        uint64_t value = LD64(sym + 8), target;
        if (shndx) {
            target = GUEST_BASE + value;
            counts[1]++;
        } else {
            target = bind_symbol((const char *)img + strtab + name, st_info & 15);
            counts[2]++;
        }
        ST64(img + off, target + (type == 0x402 ? 0 : addend));
    }
}

void rt_load_image(void) {
    char path[MAX_PATH];
    const char *e = getenv("BR_IMAGE");
    if (e && *e) snprintf(path, sizeof path, "%s", e);
    else snprintf(path, sizeof path, "%sil2cpp_data\\main.bin", rt_data_dir());
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, NULL);
    if (h == INVALID_HANDLE_VALUE)
        rt_fatal("cannot open the game image %s (the game folder is incomplete: run setup again)", path);
    LARGE_INTEGER fsz;
    GetFileSizeEx(h, &fsz);
    uint64_t fsize = (uint64_t)fsz.QuadPart;
    // MOD0 header first, to learn the bss end.
    uint8_t head[8];
    DWORD got;
    ReadFile(h, head, 8, &got, NULL);
    uint32_t mod0 = LD32(head + 4);
    uint8_t mh[0x1c];
    SetFilePointer(h, (LONG)mod0, NULL, FILE_BEGIN);
    ReadFile(h, mh, sizeof mh, &got, NULL);
    if (memcmp(mh, "MOD0", 4)) rt_fatal("loader: %s has no MOD0 header", path);
    uint64_t dyn = mod0 + (int32_t)LD32(mh + 4), bss_end = mod0 + (int32_t)LD32(mh + 12);
    uint64_t total = ((bss_end > fsize ? bss_end : fsize) + 0xffff) & ~0xffffull;
    uint8_t *img = VirtualAlloc((void *)GUEST_BASE, total, MEM_RESERVE | MEM_COMMIT, PAGE_READWRITE);
    if (img != (uint8_t *)GUEST_BASE) rt_fatal("loader: cannot map %#llx bytes at guest base %#llx (error %lu)", (unsigned long long)total, GUEST_BASE, GetLastError());
    rt_log("loader: mapped, reading");
    SetFilePointer(h, 0, NULL, FILE_BEGIN);
    for (uint64_t done = 0; done < fsize;) {
        DWORD want = fsize - done > (64u << 20) ? (64u << 20) : (DWORD)(fsize - done);
        if (!ReadFile(h, img + done, want, &got, NULL) || !got) rt_fatal("loader: read error in %s", path);
        done += got;
    }
    CloseHandle(h);

    uint64_t symtab = 0, strtab = 0, rela = 0, relasz = 0, jmprel = 0, pltrelsz = 0, relr = 0, relrsz = 0;
    for (uint64_t p = dyn;; p += 16) {
        uint64_t tag = LD64(img + p), val = LD64(img + p + 8);
        if (!tag) break;
        switch (tag) {
        case 5: strtab = val; break;
        case 6: symtab = val; break;
        case 7: rela = val; break;
        case 8: relasz = val; break;
        case 0x17: jmprel = val; break;
        case 2: pltrelsz = val; break;
        case 0x24: relr = val; break;
        case 0x23: relrsz = val; break;
        case 0x19: g_init_array = val; break;
        case 0x1b: g_init_count = val / 8; break;
        }
    }
    rt_log("loader: read, relocating");
    uint64_t nrelr = 0;
    uint64_t where = 0;
    for (uint64_t p = relr; p < relr + relrsz; p += 8) {
        uint64_t ent = LD64(img + p);
        if (!(ent & 1)) {
            ST64(img + ent, LD64(img + ent) + GUEST_BASE);
            where = ent + 8;
            nrelr++;
        } else {
            uint64_t bits = ent >> 1;
            for (int i = 0; bits; i++, bits >>= 1)
                if (bits & 1) {
                    ST64(img + where + 8ull * i, LD64(img + where + 8ull * i) + GUEST_BASE);
                    nrelr++;
                }
            where += 63 * 8;
        }
    }
    rt_log("loader: relr done");
    uint64_t counts[4] = {0};
    apply_rela(img, rela, relasz, symtab, strtab, counts);
    apply_rela(img, jmprel, pltrelsz, symtab, strtab, counts);
    rt_image_size = total;
    rt_log("loader: %s mapped at %#llx (%#llx bytes, file %#llx); relocations: %llu RELR, %llu relative, %llu to defined symbols, "
           "%llu to imports", path, GUEST_BASE, (unsigned long long)total, (unsigned long long)fsize, (unsigned long long)nrelr,
           (unsigned long long)counts[0], (unsigned long long)counts[1], (unsigned long long)counts[2]);
    rt_log("loader: %zu imported symbols: %zu bound to host functions, %zu data, %zu trap when called", g_nbind, g_bound_host,
           g_bound_data, g_bound_trap);
    if (getenv("BR_LIST_IMPORTS"))
        for (size_t i = 0; i < g_nbind; i++) {
            SynEntry *s = rt_syn_entry(g_bind[i].addr);
            rt_log("  import %s -> %s", g_bind[i].name, g_bind[i].data_lo ? "data" : s && s->fn == trap_import ? "TRAP" : "host");
        }
}

void rt_run_init_array(void) {
    uint64_t ran = 0;
    Cpu *c = rt_cpu();
    for (uint64_t i = 0; i < g_init_count; i++) {
        uint64_t fn = LD64(GUEST_BASE + g_init_array + 8 * i);
        if (!rt_lifted_lookup(fn)) continue;
        if (rt_trace & 1) rt_log("init_array[%llu] main+%#llx", (unsigned long long)i, (unsigned long long)(fn - GUEST_BASE));
        rt_call(c, fn, 0);
        if (c->eh_unwinding) rt_fatal_c(c, "exception escaped static initialiser main+%#llx", (unsigned long long)(fn - GUEST_BASE));
        ran++;
    }
    rt_log("loader: ran %llu of %llu init_array entries (the rest belong to non-lifted code)", (unsigned long long)ran,
           (unsigned long long)g_init_count);
}
