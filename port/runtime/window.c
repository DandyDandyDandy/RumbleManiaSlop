// The game window's title. The game's player settings name the product by its code name ("Wonder"), which the
// engine puts in the title bar; the port shows its own name instead (GAME_NAME, given by the build).
#include <windows.h>
#include "rt.h"

#ifndef GAME_NAME
#define GAME_NAME "RumbleSlop"
#endif

static BOOL CALLBACK find_main(HWND h, LPARAM out) {
    DWORD pid = 0;
    GetWindowThreadProcessId(h, &pid);
    if (pid == GetCurrentProcessId() && IsWindowVisible(h) && !GetWindow(h, GW_OWNER)) { *(HWND *)out = h; return FALSE; }
    return TRUE;
}

// called once per frame from the per-frame hook in display_opt.c; does its work once, when the window exists
void window_title_tick(void) {
    static int done, tries;
    if (done || (++tries & 15)) return;          // look every 16th frame until the window is there
    HWND w = NULL;
    EnumWindows(find_main, (LPARAM)&w);
    if (!w) return;
    wchar_t cls[64] = L"";
    GetClassNameW(w, cls, 64);
    if (wcscmp(cls, L"UnityWndClass")) return;   // a dialog or the text box, not the game window
    SetWindowTextW(w, L"" GAME_NAME);
    done = 1;
    rt_log("window: title set to %s", GAME_NAME);
}
