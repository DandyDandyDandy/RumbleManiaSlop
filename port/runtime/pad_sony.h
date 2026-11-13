// Latest state of a directly read Sony pad (pad_sony.c). Sticks are -32767..32767 with up positive.
#pragma once
#include <stdint.h>
enum {
    SONY_CROSS = 1 << 0, SONY_CIRCLE = 1 << 1, SONY_SQUARE = 1 << 2, SONY_TRIANGLE = 1 << 3,
    SONY_L1 = 1 << 4, SONY_R1 = 1 << 5, SONY_L2 = 1 << 6, SONY_R2 = 1 << 7,
    SONY_CREATE = 1 << 8, SONY_OPTIONS = 1 << 9, SONY_L3 = 1 << 10, SONY_R3 = 1 << 11,
    SONY_UP = 1 << 12, SONY_RIGHT = 1 << 13, SONY_DOWN = 1 << 14, SONY_LEFT = 1 << 15,
};
typedef struct { int connected; uint32_t buttons; int lx, ly, rx, ry; } SonyPad;
int rt_sony_pad(SonyPad *out);   // 1 when a pad is connected
int rt_sony_kind(void);           // 2 DualSense, 3 DualShock 4
