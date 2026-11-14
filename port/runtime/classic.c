// Classic-style monkeys (the six classic models of Banana Mania's Classic Character Pack, rebuilt on Rumble's rig)
// as an Outfit item, "Classic Outfit", in the game's own Style menu. The assets, the catalog and the database
// tables with the new item are made by port/assets/classic_outfit.py and live in <exe dir>mania\, laid out like
// the game's StreamingAssets\aa folder. The game's own files are never modified. This file does three things:
//
//  1. File overrides. A bundle the game asks the engine to load from ...\aa\Switch\<x> is loaded from
//     <exe dir>mania\Switch\<x> when that file exists (new bundles, and the copies of the item/asset/text tables),
//     and the Addressables catalog is read from <exe dir>mania\catalog.json when it exists (classic_fs_override,
//     called from the file layer). Without the classic folder nothing changes.
//
//  2. Hiding Rumble's own parts. The classic costume asset is one mesh (body, hands, feet, head) that the game's
//     costume system puts on the character's `*_cstm_body01` renderers. Rumble's head, face, mouth, ear, hair, hand
//     and shoe renderers have no place in the costume system's idea of an outfit, so while a character's body
//     renderer carries a mesh named `classic_*`, the meshes of its other skinned renderers are taken off
//     (remembered, and put back when the outfit is taken off). The check runs once per frame per character and
//     only does work when the body mesh changed or a costume call was made.
//
//  3. Nothing else: wearing, saving and previewing the outfit is the game's own code.
//
// Hooks: UnityEngine.AssetBundle::LoadFromFileAsync (three overloads); Wonder.CharaCustomizeAssetAssign::Set,
// Revert and RevertAll (they only mark the characters for a re-check). classic_track is called from the
// CharaComponentReference::Awake hook in chara_dump.c, classic_tick from the per-frame hook in display_opt.c.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_STRING_NEW_UTF16 0x45af94ull   // il2cpp::vm::String::NewUtf16(const Il2CppChar *, int32_t)
#define F_GET_RENDERER_LIST 0x486d350ull // Wonder.CharaComponentReference::get_rendererList -> List<Renderer>
#define F_GET_GAMEOBJECT 0x3f07fb0ull    // UnityEngine.Component::get_gameObject
#define F_OBJ_ALIVE 0x3f10610ull         // UnityEngine.Object::op_Implicit (static)
#define F_OBJ_NAME 0x3f10820ull          // UnityEngine.Object::get_name
#define F_SMR_GET_MESH 0x3ed84c0ull      // UnityEngine.SkinnedMeshRenderer::get_sharedMesh
#define F_SMR_SET_MESH 0x3ed8510ull      // UnityEngine.SkinnedMeshRenderer::set_sharedMesh

static int is_file(const char *p) { DWORD a = GetFileAttributesA(p); return a != INVALID_FILE_ATTRIBUTES && !(a & FILE_ATTRIBUTE_DIRECTORY); }
static int g_have = -1;                  // <exe dir>mania\catalog.json exists
static int have(void) {
    if (g_have < 0) {
        char p[700];
        snprintf(p, sizeof p, "%smania\\catalog.json", rt_exe_dir());
        g_have = is_file(p);
        rt_log("classic: outfit files %s", g_have ? "found" : "not installed");
    }
    return g_have;
}

// ---- 1. file overrides
// host path of a file about to be opened by the file layer; rewritten in place for the catalog
void classic_fs_override(char *path, size_t cap) {
    size_t n = strlen(path);
    static const char tail[] = "\\aa\\catalog.json", sound[] = "\\StreamingAssets\\Sound\\";
    if (!have()) return;
    if (n >= sizeof tail - 1 && !_stricmp(path + n - (sizeof tail - 1), tail)) {
        snprintf(path, cap, "%smania\\catalog.json", rt_exe_dir());
        return;
    }
    // a sound file (CRIWARE cue sheet or stream) that the override folder has: imported music
    for (const char *p = path; *p; p++)
        if (!_strnicmp(p, sound, sizeof sound - 1)) {
            char cand[700];
            snprintf(cand, sizeof cand, "%smania\\Sound\\%s", rt_exe_dir(), p + sizeof sound - 1);
            if (is_file(cand)) {
                static char last[96];                   // one log line per file, not per open
                if (_stricmp(last, p + sizeof sound - 1)) {
                    snprintf(last, sizeof last, "%s", p + sizeof sound - 1);
                    rt_log("classic: opens mania\\Sound\\%s", last);
                }
                snprintf(path, cap, "%s", cand);
            }
            return;
        }
}

// UnityEngine.AssetBundle::LoadFromFileAsync_Internal(string path, uint crc, ulong offset) and the public overloads
int rt_hook_3ea1630(Cpu *c) {
    uint64_t s = c->x[0];
    if (!s || !have()) return 0;
    char path[1200], cand[1400];
    int n = WideCharToMultiByte(CP_UTF8, 0, (const wchar_t *)(uintptr_t)(s + 0x14), (int)LD32(s + 0x10), path, sizeof path - 1, NULL, NULL);
    path[n > 0 ? n : 0] = 0;
    char *rel = NULL;                                  // the part from "Switch/..." of ".../aa/Switch/..."
    for (char *q = path; *q; q++)
        if ((q[0] == 'a' && q[1] == 'a') && (q[2] == '/' || q[2] == '\\') && !_strnicmp(q + 3, "Switch", 6) && (q == path || q[-1] == '/' || q[-1] == '\\')) rel = q + 3;
    if (!rel) return 0;
    snprintf(cand, sizeof cand, "%smania\\%s", rt_exe_dir(), rel);
    for (char *q = cand; *q; q++) if (*q == '/') *q = '\\';
    if (!is_file(cand)) return 0;
    wchar_t w[1400];
    int wn = MultiByteToWideChar(CP_UTF8, 0, cand, -1, w, 1400) - 1;
    uint64_t x1 = c->x[1], x2 = c->x[2], x3 = c->x[3];
    uint64_t ns = rt_call(c, FN(F_STRING_NEW_UTF16), 2, (uint64_t)(uintptr_t)w, (uint64_t)wn);
    c->x[1] = x1; c->x[2] = x2; c->x[3] = x3;
    c->x[0] = ns ? ns : s;
    if (ns) rt_log("classic: loads %s", rel);
    return 0;
}
int rt_hook_3ea1690(Cpu *c) { return rt_hook_3ea1630(c); }
int rt_hook_3ea16f0(Cpu *c) { return rt_hook_3ea1630(c); }

// ---- 2. hiding Rumble's own parts under the classic mesh
#define NCHARA 64
#define NBODY 4
#define NSAVED 4096
typedef struct { uint64_t ref, body[NBODY], last[NBODY]; int nbody, scanned, classic; unsigned gen; } Chara;
static Chara g_ch[NCHARA];
static struct { uint64_t renderer, mesh; } g_saved[NSAVED];
static unsigned g_gen = 1;               // bumped by every costume call

static int alive(Cpu *c, uint64_t o) { return o && (rt_call(c, FN(F_OBJ_ALIVE), 2, o, 0ull) & 1); }
static const uint16_t *name_of(Cpu *c, uint64_t o, uint32_t *len) {   // UTF-16 name of a live Unity object
    uint64_t s = rt_call(c, FN(F_OBJ_NAME), 2, o, 0ull);
    *len = s ? LD32(s + 0x10) : 0;
    return (const uint16_t *)(uintptr_t)(s + 0x14);
}
static int ends_with(const uint16_t *u, uint32_t n, const char *tail) {
    uint32_t k = (uint32_t)strlen(tail);
    if (n < k) return 0;
    for (uint32_t i = 0; i < k; i++) if (u[n - k + i] != (uint8_t)tail[i]) return 0;
    return 1;
}
static int starts_with(const uint16_t *u, uint32_t n, const char *head) {
    uint32_t k = (uint32_t)strlen(head);
    if (n < k) return 0;
    for (uint32_t i = 0; i < k; i++) if (u[i] != (uint8_t)head[i]) return 0;
    return 1;
}
static int is_skinned(uint64_t r) { return !strcmp((const char *)(uintptr_t)LD64(LD64(r) + 0x10), "SkinnedMeshRenderer"); }

void classic_track(uint64_t chara_component_reference) {
    if (!have()) return;
    for (int i = 0; i < NCHARA; i++)
        if (!g_ch[i].ref) { memset(&g_ch[i], 0, sizeof g_ch[i]); g_ch[i].ref = chara_component_reference; return; }
}

static void apply(Cpu *c, Chara *ch) {
    uint64_t list = rt_call(c, FN(F_GET_RENDERER_LIST), 2, ch->ref, 0ull);
    uint64_t items = list ? LD64(list + 0x10) : 0;
    int n = list ? (int)LD32(list + 0x18) : 0, changed = 0;
    for (int i = 0; items && i < n; i++) {
        uint64_t r = LD64(items + 0x20 + 8ull * i);
        if (!alive(c, r) || !is_skinned(r)) continue;
        int body = 0;
        for (int k = 0; k < ch->nbody; k++) body |= ch->body[k] == r;
        if (body) continue;
        uint64_t mesh = rt_call(c, FN(F_SMR_GET_MESH), 2, r, 0ull);
        int slot = -1, free_slot = -1;
        for (int k = 0; k < NSAVED; k++) {
            if (g_saved[k].renderer == r) { slot = k; break; }
            if (!g_saved[k].renderer && free_slot < 0) free_slot = k;
        }
        if (ch->classic) {
            if (!alive(c, mesh)) continue;
            if (slot < 0) slot = free_slot;
            if (slot < 0) continue;                   // table full: leave this renderer as it is
            g_saved[slot].renderer = r; g_saved[slot].mesh = mesh;
            rt_call(c, FN(F_SMR_SET_MESH), 3, r, 0ull, 0ull);
            changed++;
        } else if (slot >= 0) {
            if (!alive(c, mesh) && alive(c, g_saved[slot].mesh)) { rt_call(c, FN(F_SMR_SET_MESH), 3, r, g_saved[slot].mesh, 0ull); changed++; }
            g_saved[slot].renderer = 0;
        }
    }
    if (changed) rt_log("classic: %s Rumble's own parts on a character (%d renderers)", ch->classic ? "hid" : "restored", changed);
}

void classic_tick(Cpu *c) {   // once per frame; the caller preserves the registers
    if (g_have <= 0) return;
    for (int i = 0; i < NCHARA; i++) {
        Chara *ch = &g_ch[i];
        if (!ch->ref) continue;
        if (!alive(c, ch->ref)) {
            for (int k = 0; k < NSAVED; k++)          // forget what belonged to renderers that are gone
                if (g_saved[k].renderer && !alive(c, g_saved[k].renderer)) g_saved[k].renderer = 0;
            ch->ref = 0;
            continue;
        }
        if (!ch->scanned) {
            uint64_t list = rt_call(c, FN(F_GET_RENDERER_LIST), 2, ch->ref, 0ull);
            uint64_t items = list ? LD64(list + 0x10) : 0;
            int n = list ? (int)LD32(list + 0x18) : 0;
            if (!n) continue;                         // the list is filled by the character's own Awake/Start
            for (int k = 0; k < n && ch->nbody < NBODY; k++) {
                uint64_t r = LD64(items + 0x20 + 8ull * k);
                if (!alive(c, r) || !is_skinned(r)) continue;
                uint32_t len;
                const uint16_t *u = name_of(c, rt_call(c, FN(F_GET_GAMEOBJECT), 2, r, 0ull), &len);
                if (ends_with(u, len, "_cstm_body01")) ch->body[ch->nbody++] = r;
            }
            ch->scanned = 1;
            ch->gen = 0;
        }
        int changed = ch->gen != g_gen, classic = 0;
        uint64_t now[NBODY];
        for (int k = 0; k < ch->nbody; k++) {
            now[k] = alive(c, ch->body[k]) ? rt_call(c, FN(F_SMR_GET_MESH), 2, ch->body[k], 0ull) : 0;
            changed |= now[k] != ch->last[k];
        }
        if (!changed) continue;
        for (int k = 0; k < ch->nbody; k++) {
            ch->last[k] = now[k];
            if (!alive(c, now[k])) continue;
            uint32_t len;
            const uint16_t *u = name_of(c, now[k], &len);
            classic |= starts_with(u, len, "classic_");
        }
        ch->gen = g_gen;
        ch->classic = classic;
        apply(c, ch);
    }
}

// Wonder.CharaCustomizeAssetAssign::Set / Revert / RevertAll: a costume part is about to change
int rt_hook_486d570(Cpu *c) { (void)c; g_gen++; return 0; }
int rt_hook_486d900(Cpu *c) { (void)c; g_gen++; return 0; }
int rt_hook_486dab0(Cpu *c) { (void)c; g_gen++; return 0; }
