// Sony pads (DualSense, DualSense Edge, DualShock 4) read directly over HID, because they are not XInput devices.
// A background thread finds the first such pad (USB or Bluetooth), reads its input reports and keeps the latest
// state; imports_hid.c merges it into the virtual npad. The pad is re-searched once a second after a disconnect,
// so plugging it in while the game runs works. No rumble or lightbar output.
#include <windows.h>
#include <setupapi.h>
#include <hidsdi.h>
#include <string.h>
#include "rt.h"
#include "pad_sony.h"

static volatile LONG g_started;
static SRWLOCK g_lock = SRWLOCK_INIT;
static SonyPad g_state;
static volatile LONG g_kind;                 // 2 DualSense, 3 DualShock 4 (rt_sony_kind), 0 none
int rt_sony_kind(void) { return (int)g_kind; }

static int is_ds4(USHORT pid) { return pid == 0x05c4 || pid == 0x09cc; }
static int is_dualsense(USHORT pid) { return pid == 0x0ce6 || pid == 0x0df2; }

// Open the first Sony pad. Returns the handle, its product id and its input report length.
static HANDLE open_pad(USHORT *pid, DWORD *report_len) {
    GUID hid;
    HidD_GetHidGuid(&hid);
    HDEVINFO set = SetupDiGetClassDevsA(&hid, NULL, NULL, DIGCF_PRESENT | DIGCF_DEVICEINTERFACE);
    if (set == INVALID_HANDLE_VALUE) return INVALID_HANDLE_VALUE;
    HANDLE found = INVALID_HANDLE_VALUE;
    SP_DEVICE_INTERFACE_DATA ifd = {.cbSize = sizeof ifd};
    for (DWORD i = 0; found == INVALID_HANDLE_VALUE && SetupDiEnumDeviceInterfaces(set, NULL, &hid, i, &ifd); i++) {
        union { SP_DEVICE_INTERFACE_DETAIL_DATA_A d; char raw[1024]; } det;
        det.d.cbSize = sizeof(SP_DEVICE_INTERFACE_DETAIL_DATA_A);
        if (!SetupDiGetDeviceInterfaceDetailA(set, &ifd, &det.d, sizeof det, NULL, NULL)) continue;
        HANDLE h = CreateFileA(det.d.DevicePath, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE, NULL,
                               OPEN_EXISTING, 0, NULL);
        if (h == INVALID_HANDLE_VALUE) continue;
        HIDD_ATTRIBUTES at = {.Size = sizeof at};
        PHIDP_PREPARSED_DATA pp = NULL;
        HIDP_CAPS caps;
        if (HidD_GetAttributes(h, &at) && at.VendorID == 0x054c && (is_ds4(at.ProductID) || is_dualsense(at.ProductID)) &&
            HidD_GetPreparsedData(h, &pp) && HidP_GetCaps(pp, &caps) == HIDP_STATUS_SUCCESS && caps.InputReportByteLength >= 10) {
            *pid = at.ProductID; *report_len = caps.InputReportByteLength;
            found = h;
        }
        if (pp) HidD_FreePreparsedData(pp);
        if (found == INVALID_HANDLE_VALUE) CloseHandle(h);
    }
    SetupDiDestroyDeviceInfoList(set);
    return found;
}

static int stick(uint8_t v, int invert) {
    int s = ((int)v - 128) * 258;
    if (invert) s = -s;
    if (s > 32767) s = 32767;
    if (s < -32767) s = -32767;
    return s > 3500 || s < -3500 ? s : 0;       // about 10% dead zone
}
// d points at the left stick X byte; face/btn1 are the two button bytes; l2/r2 the analog triggers.
static void decode(SonyPad *p, const uint8_t *d, uint8_t face, uint8_t btn1) {
    static const uint32_t hat[9] = {SONY_UP, SONY_UP | SONY_RIGHT, SONY_RIGHT, SONY_RIGHT | SONY_DOWN, SONY_DOWN,
                                    SONY_DOWN | SONY_LEFT, SONY_LEFT, SONY_LEFT | SONY_UP, 0};
    uint32_t b = hat[(face & 15) > 8 ? 8 : (face & 15)];
    if (face & 0x10) b |= SONY_SQUARE;
    if (face & 0x20) b |= SONY_CROSS;
    if (face & 0x40) b |= SONY_CIRCLE;
    if (face & 0x80) b |= SONY_TRIANGLE;
    if (btn1 & 0x01) b |= SONY_L1;
    if (btn1 & 0x02) b |= SONY_R1;
    if (btn1 & 0x04) b |= SONY_L2;
    if (btn1 & 0x08) b |= SONY_R2;
    if (btn1 & 0x10) b |= SONY_CREATE;
    if (btn1 & 0x20) b |= SONY_OPTIONS;
    if (btn1 & 0x40) b |= SONY_L3;
    if (btn1 & 0x80) b |= SONY_R3;
    p->connected = 1; p->buttons = b;
    p->lx = stick(d[0], 0); p->ly = stick(d[1], 1); p->rx = stick(d[2], 0); p->ry = stick(d[3], 1);
}

static DWORD WINAPI reader(void *unused) {
    (void)unused;
    uint8_t rep[256];
    for (;;) {
        USHORT pid = 0; DWORD len = 0;
        HANDLE h = open_pad(&pid, &len);
        if (h == INVALID_HANDLE_VALUE) { Sleep(1000); continue; }
        int bt = len > 64;
        if (bt && is_dualsense(pid)) {       // reading this feature report switches a Bluetooth DualSense to full reports
            uint8_t f[64] = {0x05};
            HidD_GetFeature(h, f, 41);
        }
        rt_log("input: Sony pad %04x connected over %s (report length %lu)", pid, bt ? "Bluetooth" : "USB", (unsigned long)len);
        g_kind = is_ds4(pid) ? 3 : 2;
        DWORD got;
        while (ReadFile(h, rep, len < sizeof rep ? len : sizeof rep, &got, NULL) && got >= 10) {
            SonyPad p = {0};
            if (is_dualsense(pid) && rep[0] == 0x01 && !bt) decode(&p, rep + 1, rep[8], rep[9]);          // USB
            else if (is_dualsense(pid) && rep[0] == 0x31 && got >= 12) decode(&p, rep + 2, rep[9], rep[10]);   // Bluetooth, full
            else if (rep[0] == 0x01) decode(&p, rep + 1, rep[5], rep[6]);      // DualShock 4 USB, or a Bluetooth pad in basic mode
            else if (is_ds4(pid) && rep[0] == 0x11 && got >= 12) decode(&p, rep + 3, rep[7], rep[8]);     // DualShock 4 Bluetooth
            else continue;
            AcquireSRWLockExclusive(&g_lock);
            g_state = p;
            ReleaseSRWLockExclusive(&g_lock);
        }
        CloseHandle(h);
        AcquireSRWLockExclusive(&g_lock);
        memset(&g_state, 0, sizeof g_state);
        ReleaseSRWLockExclusive(&g_lock);
        rt_log("input: Sony pad disconnected");
        Sleep(1000);
    }
    return 0;
}

int rt_sony_pad(SonyPad *out) {
    if (!InterlockedExchange(&g_started, 1)) {
        const char *e = getenv("BR_SONY_PAD");
        if (!(e && (!strcmp(e, "off") || !strcmp(e, "0")))) CloseHandle(CreateThread(NULL, 0, reader, NULL, 0, NULL));
    }
    AcquireSRWLockShared(&g_lock);
    *out = g_state;
    ReleaseSRWLockShared(&g_lock);
    return out->connected;
}
