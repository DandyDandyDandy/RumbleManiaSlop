// Stage pictures for the import (mania\thumbshot.py): the game shows the stage it is in from a given point of
// view, with nothing but the stage and its background on the screen, so the importer can photograph the window.
//
// BR_THUMB_VIEW="<tx>,<ty>,<tz>,<distance>,<pitch>,<turn>,<fov>": the point looked at (stage coordinates), how far
// the eye is from it, the angles in degrees (pitch up from level, turn about the vertical; turn 0 looks from +z)
// and the vertical field of view in degrees.
//
// The view is the game's own free camera, "View Stage" of the pause menu (MgViewStageController /
// MgViewStageCamera): once the stage has started it is begun the way the pause menu begins it, without the menu.
// From then on, every frame:
//   * the camera's orbit values are set to the wanted ones just before it computes its transform
//     (rt_hook_4290ef0, MgViewStageCamera.updateTRS), and its cameras get the field of view;
//   * the markers of that mode (start, goal and player billboards, the orbit centre) are switched off, and so are
//     the players;
//   * every UI canvas is switched off (rt_hide_ui, ultrawide.c).
// "thumb: ready" in port.log says that the picture can be taken; "thumb: failed" that it cannot.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_MAIN_GAME_STAGE 0x42cf030ull      // Wonder.MainGame::get_mainGameStage (static; null outside a stage)
#define F_IS_STARTED 0x42cfef0ull           // Wonder.MainGame::get_isStarted (static)
#define F_PLAYER_LIST 0x42cf6c0ull          // Wonder.MainGame::get_playerList -> List<MgPlayer>
#define F_VIEW_STAGE 0x42cfa40ull           // Wonder.MainGame::get_viewStage -> MgViewStageController
#define F_SEQ_OBSERVER 0x42d0110ull         // Wonder.MainGame::get_seqObserver
#define F_VIEW_BEGIN 0x4291450ull           // MgViewStageController.Begin(int inputIndex, IMgSeqObserver)
#define F_OBJ_ALIVE 0x3f10610ull            // UnityEngine.Object::op_Implicit (static)
#define F_GET_GAMEOBJECT 0x3f07fb0ull       // UnityEngine.Component::get_gameObject
#define F_SET_ACTIVE 0x3f0bd10ull           // UnityEngine.GameObject::SetActive(bool)
#define F_SET_FOV 0x3ea9a70ull              // UnityEngine.Camera::set_fieldOfView(float)
#define PLAYER_CAMERA_INDEX 0x80            // MgPlayer.m_CameraIndex
#define CTRL_CAMERA 0x20                    // MgViewStageController.m_CameraController
#define CTRL_BILLBOARDS 0x28                // ... four GameObjects: goal arch, goal circle, start, player
#define CAM_TILT 0x20                       // MgCameraControllerBase.m_TiltCamera, +0x28 m_BaseCamera
#define CAM_INTR 0x26c                      // MgViewStageCamera.m_Intr (the point looked at), +0x278 m_IntrOffset
#define CAM_INTR_OFFSET 0x278
#define CAM_DIST 0x298                      // m_dist, +0x2a0 m_distSpeed
#define CAM_ROT_X 0x2a4                     // m_rotX (pitch, degrees), +0x2a8 m_rotY
#define CAM_ORIGIN_OBJ 0x300                // m_OriginObj, +0x310 m_IntrObj: the markers of the orbit
#define LIST_ITEMS 0x10
#define LIST_SIZE 0x18
#define ARR_DATA 0x20
#define SETTLE_FRAMES 45                    // between the start of the stage and the view; between the view and "ready"

extern int rt_hide_ui;                      // ultrawide.c
static float g_view[7];
static int g_state;                         // 0 waiting for the stage, 1 the view is on, 2 ready, -1 off

static int wanted(void) {
    static int on = -1;
    if (on < 0) {
        const char *e = getenv("BR_THUMB_VIEW");
        on = e && sscanf(e, "%f,%f,%f,%f,%f,%f,%f", &g_view[0], &g_view[1], &g_view[2], &g_view[3], &g_view[4], &g_view[5],
                         &g_view[6]) == 7;
        if (e && !on) rt_log("thumb: BR_THUMB_VIEW is not seven numbers");
    }
    return on;
}
static int alive(Cpu *c, uint64_t o) { return o && (rt_call(c, FN(F_OBJ_ALIVE), 2, o, 0ull) & 1); }
static void put(uint64_t at, float f) { memcpy((void *)(uintptr_t)at, &f, 4); }
static void hide(Cpu *c, uint64_t game_object) {
    if (alive(c, game_object)) rt_call(c, FN(F_SET_ACTIVE), 3, game_object, 0ull, 0ull);
}
static uint64_t item(uint64_t list, int i) {
    uint64_t items = list ? LD64(list + LIST_ITEMS) : 0;
    return items && i < (int)LD32(list + LIST_SIZE) ? LD64(items + ARR_DATA + 8 * (uint64_t)i) : 0;
}

void thumb_tick(Cpu *c) {      // once per frame, on the game's main thread; the caller preserves the registers
    static int frames;
    if (!wanted() || g_state < 0 || g_state == 2) return;
    uint64_t stage = rt_call(c, FN(F_MAIN_GAME_STAGE), 1, 0ull);
    if (g_state == 0) {
        if (!stage || !(rt_call(c, FN(F_IS_STARTED), 1, 0ull) & 1)) { frames = 0; return; }
        if (++frames < SETTLE_FRAMES) return;
        uint64_t ctrl = rt_call(c, FN(F_VIEW_STAGE), 1, 0ull), player = item(rt_call(c, FN(F_PLAYER_LIST), 1, 0ull), 0);
        uint64_t observer = rt_call(c, FN(F_SEQ_OBSERVER), 1, 0ull);
        if (!alive(c, ctrl) || !player) { rt_log("thumb: failed: this stage has no View Stage camera or no player"); g_state = -1; return; }
        rt_call(c, FN(F_VIEW_BEGIN), 4, ctrl, (uint64_t)LD32(player + PLAYER_CAMERA_INDEX), observer, 0ull);
        rt_hide_ui = 1;
        g_state = 1; frames = 0;
        rt_log("thumb: the view is on: looks at %.2f %.2f %.2f from %.2f away, pitch %.1f turn %.1f, field of view %.1f",
               g_view[0], g_view[1], g_view[2], g_view[3], g_view[4], g_view[5], g_view[6]);
        return;
    }
    if (!stage) { rt_log("thumb: failed: the stage is gone"); g_state = -1; return; }
    uint64_t ctrl = rt_call(c, FN(F_VIEW_STAGE), 1, 0ull), players = rt_call(c, FN(F_PLAYER_LIST), 1, 0ull);
    if (alive(c, ctrl))
        for (int i = 0; i < 4; i++) hide(c, LD64(ctrl + CTRL_BILLBOARDS + 8 * i));
    for (int i = 0, n = players ? (int)LD32(players + LIST_SIZE) : 0; i < n; i++) {
        uint64_t p = item(players, i);
        if (alive(c, p)) hide(c, rt_call(c, FN(F_GET_GAMEOBJECT), 2, p, 0ull));
    }
    if (++frames == SETTLE_FRAMES) { g_state = 2; rt_log("thumb: ready"); }
}

// Wonder.MgViewStageCamera::updateTRS(): turns m_Intr, m_dist, m_rotX, m_rotY into the camera's position and
// rotation, every frame of the View Stage mode.
int rt_hook_4290ef0(Cpu *c) {
    if (g_state < 1) return 0;
    uint64_t self = c->x[0], sx[31]; __uint128_t sv[8];
    memcpy(sx, c->x, sizeof sx); memcpy(sv, c->v, sizeof sv);
    for (int i = 0; i < 3; i++) put(self + CAM_INTR + 4 * i, g_view[i]);
    put(self + CAM_INTR_OFFSET, 0); put(self + CAM_INTR_OFFSET + 4, 0);
    put(self + CAM_DIST, g_view[3]); put(self + CAM_DIST + 8, 0);
    put(self + CAM_ROT_X, g_view[4]); put(self + CAM_ROT_X + 4, g_view[5]);
    hide(c, LD64(self + CAM_ORIGIN_OBJ)); hide(c, LD64(self + CAM_ORIGIN_OBJ + 0x10));
    for (int i = 0; i < 2; i++) {
        uint64_t cam = LD64(self + CAM_TILT + 8 * i);
        if (!alive(c, cam)) continue;
        uint32_t bits; memcpy(&bits, &g_view[6], 4);
        c->x[0] = cam; c->x[1] = 0; c->v[0] = bits;
        rt_call_regs(c, FN(F_SET_FOV));
    }
    memcpy(c->x, sx, sizeof sx); memcpy(c->v, sv, sizeof sv);
    return 0;
}
