// The Switch software keyboard on Windows: a small modal window with a prompt, one text box, OK and Cancel.
// The game opens it for room codes and room passwords (nn::swkbd::ShowKeyboard in imports_plat.c). It runs on the
// game's main thread, which also owns the game window, and blocks it the way the console's keyboard does.
// Enter confirms, Esc cancels, Ctrl+V pastes.
#include <windows.h>
#include <stdint.h>

#define ID_EDIT 100
typedef struct { HWND edit; uint16_t *out; int max, done, ok; } Kb;

static LRESULT CALLBACK kb_proc(HWND h, UINT m, WPARAM w, LPARAM l) {
    Kb *kb = (Kb *)GetWindowLongPtrW(h, GWLP_USERDATA);
    switch (m) {
    case WM_COMMAND:
        if (!kb) break;
        if (LOWORD(w) == IDOK) {
            GetWindowTextW(kb->edit, (LPWSTR)kb->out, kb->max);
            kb->ok = kb->done = 1;
            return 0;
        }
        if (LOWORD(w) == IDCANCEL) { kb->done = 1; return 0; }
        break;
    case WM_CLOSE:
        if (kb) kb->done = 1;
        return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

static BOOL CALLBACK find_main(HWND h, LPARAM out) {
    if (IsWindowVisible(h) && !GetWindow(h, GW_OWNER)) { *(HWND *)out = h; return FALSE; }
    return TRUE;
}

int swkbd_prompt(const uint16_t *header, const uint16_t *sub, const uint16_t *initial, uint16_t *out, int max_chars) {
    static ATOM cls;
    HINSTANCE inst = GetModuleHandleW(NULL);
    HWND owner = NULL;
    Kb kb = {0};
    if (max_chars < 2) return 0;
    out[0] = 0;
    if (!cls) {
        WNDCLASSW wc = {0};
        wc.lpfnWndProc = kb_proc;
        wc.hInstance = inst;
        wc.hCursor = LoadCursorW(NULL, (LPCWSTR)IDC_ARROW);
        wc.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
        wc.lpszClassName = L"RumbleSlopTextBox";
        cls = RegisterClassW(&wc);
        if (!cls) return 0;
    }
    EnumThreadWindows(GetCurrentThreadId(), find_main, (LPARAM)&owner);
    UINT dpi = 96;
    HDC dc = GetDC(NULL);
    if (dc) { dpi = (UINT)GetDeviceCaps(dc, LOGPIXELSX); ReleaseDC(NULL, dc); }
#define S(v) MulDiv(v, (int)dpi, 96)
    int w = S(440), hgt = S(190);
    RECT r = {0, 0, GetSystemMetrics(SM_CXSCREEN), GetSystemMetrics(SM_CYSCREEN)};
    if (owner) GetWindowRect(owner, &r);
    HWND win = CreateWindowExW(WS_EX_DLGMODALFRAME | WS_EX_TOPMOST, L"RumbleSlopTextBox", header && header[0] ? (LPCWSTR)header : L"Enter text",
                               WS_POPUP | WS_CAPTION | WS_SYSMENU, r.left + (r.right - r.left - w) / 2, r.top + (r.bottom - r.top - hgt) / 2, w, hgt,
                               owner, NULL, inst, NULL);
    if (!win) return 0;
    kb.out = out; kb.max = max_chars;
    SetWindowLongPtrW(win, GWLP_USERDATA, (LONG_PTR)&kb);
    NONCLIENTMETRICSW ncm = {sizeof ncm};
    HFONT font = SystemParametersInfoW(SPI_GETNONCLIENTMETRICS, sizeof ncm, &ncm, 0) ? CreateFontIndirectW(&ncm.lfMessageFont) : NULL;
    RECT cr;
    GetClientRect(win, &cr);
    int cw = cr.right, m = S(14);
    HWND label = CreateWindowExW(0, L"STATIC", sub && sub[0] ? (LPCWSTR)sub : (header && header[0] ? (LPCWSTR)header : L"Enter text"),
                                 WS_CHILD | WS_VISIBLE, m, m, cw - 2 * m, S(40), win, NULL, inst, NULL);
    kb.edit = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", initial ? (LPCWSTR)initial : L"", WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                              m, m + S(46), cw - 2 * m, S(26), win, (HMENU)(INT_PTR)ID_EDIT, inst, NULL);
    HWND ok = CreateWindowExW(0, L"BUTTON", L"OK", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                              cw - m - S(180), cr.bottom - m - S(28), S(84), S(28), win, (HMENU)(INT_PTR)IDOK, inst, NULL);
    HWND cancel = CreateWindowExW(0, L"BUTTON", L"Cancel", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                                  cw - m - S(84), cr.bottom - m - S(28), S(84), S(28), win, (HMENU)(INT_PTR)IDCANCEL, inst, NULL);
#undef S
    if (font) {
        SendMessageW(label, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(kb.edit, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(ok, WM_SETFONT, (WPARAM)font, TRUE);
        SendMessageW(cancel, WM_SETFONT, (WPARAM)font, TRUE);
    }
    SendMessageW(kb.edit, EM_SETLIMITTEXT, (WPARAM)(max_chars - 1), 0);
    SendMessageW(kb.edit, EM_SETSEL, 0, -1);
    if (owner) EnableWindow(owner, FALSE);
    ShowWindow(win, SW_SHOW);
    SetForegroundWindow(win);
    SetFocus(kb.edit);
    MSG msg;
    while (!kb.done) {
        BOOL g = GetMessageW(&msg, NULL, 0, 0);
        if (g <= 0) {                                               // WM_QUIT: hand it back to the game's own loop
            if (g == 0) PostQuitMessage((int)msg.wParam);
            break;
        }
        if (!IsDialogMessageW(win, &msg)) {
            TranslateMessage(&msg);
            DispatchMessageW(&msg);
        }
    }
    if (owner) EnableWindow(owner, TRUE);
    DestroyWindow(win);
    if (owner) SetForegroundWindow(owner);
    if (font) DeleteObject(font);
    return kb.ok;
}
