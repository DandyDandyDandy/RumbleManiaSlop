// No title call on the title screen (RumbleManiaSlop only).
//
// Banana Rumble's title screen has the monkeys call out the game's name. The fork's title is its own (Banana
// Mania's music, its own logo: mania\title.py), so the call is kept silent.
//
// How the game plays it: UIStateTitle's start-up coroutine prepares a sound handle with cue 1501 (Sound_Cue row:
// sheet "adv", cue "title_call") and waits until it is prepared; a lambda of the same coroutine plays it with
// Handle.Play() when the logo comes in. Preparing starts the cue paused, Play() lets it run. So the handle is
// left to prepare as usual (the coroutine must see it prepared, or the title would wait for ever) and only that
// handle's Play() is skipped: the cue stays paused and nothing is heard. Pointing the table row at a missing
// cue is not an option for the same reason.
//
// A handle is recognised by its address, remembered at Prepare, and checked again by its inner cue name at Play
// (an address can be reused for another object once the handle is gone). BR_TITLE_CALL=1 lets the call play.
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define CUE_TITLE_CALL 1501         // Wonder.DB.Sound.Cue.eID: Sound_Cue row "adv" / "title_call"
#define HANDLE_INNER_CUE 0x18       // Wonder.Sound+Handle: string m_InnerCueName

static uint64_t g_handle;

static int allowed(void) {
    static int v = -1;
    if (v < 0) { const char *e = getenv("BR_TITLE_CALL"); v = e && *e == '1'; }
    return v;
}

// the handle's inner cue name is "title_call" (il2cpp string: int length at +0x10, UTF-16 at +0x14)
static int is_title_call(uint64_t handle) {
    static const char want[] = "title_call";
    uint64_t s = LD64(handle + HANDLE_INNER_CUE);
    if (!s || LD32(s + 0x10) != sizeof want - 1) return 0;
    for (unsigned i = 0; i < sizeof want - 1; i++)
        if (LD16(s + 0x14 + 2 * i) != (uint16_t)want[i]) return 0;
    return 1;
}

// Wonder.Sound+Handle::Prepare(Sound.Cue.eID in_CueID)
int rt_hook_4393a50(Cpu *c) {
    if ((uint32_t)c->x[1] == CUE_TITLE_CALL && !allowed())
        g_handle = c->x[0];
    return 0;
}

// Wonder.Sound+Handle::Play()
int rt_hook_4393c10(Cpu *c) {
    uint64_t h = c->x[0];
    if (!h || h != g_handle) return 0;
    if (!is_title_call(h)) { g_handle = 0; return 0; }
    rt_log("title: the title call stays silent");
    return 1;
}
