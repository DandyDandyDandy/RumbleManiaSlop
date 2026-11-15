// Banana Mania's intro camera on imported stages.
//
// Rumble opens a stage with two timelines: the stage timeline (the stage's title card and a generic camera move
// between two points of a box, BeginningBounds) and then, with READY, a player timeline whose camera flies in to
// the ball. Banana Mania's intro is no timeline but a camera state, MainCameraReady, the same for every stage and
// computed from the stage (read from Mania's code, 1.0 PC build):
//
//   from  = look at the centre of the stage's box (every mesh under the stage, the bottom raised to the fall-out
//           height), pitch -60.254 degrees, heading = the ball's start heading - 360, distance 1.6 x half the
//           box's diagonal;
//   to    = look at the ball's start + 0.98 up, pitch -18.281, heading = the start heading, distance 3.362
//           (GameParam.MainGameParam.CameraParam: cameraStartXAng, cameraXAng, cameraDist, interestOffsetY);
//   r     runs from 1 to 0 in 360 frames of 1/60 s (TimeSpeed 1/6 x 0.0166834 a frame), s = r^2 (3 - 2r);
//   look-at point, angles and distance = to + (from - to) x s; the eye = look-at point + Euler(pitch, heading, 0) x
//   (0, 0, distance), looking at the look-at point; field of view 60.
//
// So the camera turns once round the stage while it comes down from the whole stage to behind the ball, and READY
// finds it there. The import writes each stage's numbers ("intro <stage row> cx cy cz distance sx sy sz heading" in
// mania_courses.txt, stage.py mania_intro). Here:
//   * MgBeginningTimelineController.StageTimelineUpdate (asked once a frame in the intro state whether the stage
//     timeline is over; a pure question) answers "not yet" until Mania's six seconds have passed. They are counted
//     from the moment the loading screen has gone (UIFadeManager state None): the intro state begins under it.
//     A skipped intro (a button, or a retry, which the game and Mania both skip) is left alone.
//   * MgBeginningTimelineController.PlayerTimelineUpdate (once a frame in the READY state) only marks that state.
//   * CinemachineBrain.PushStateToUnityCamera (every brain, every frame, just before the camera's transform and
//     lens are set) gets Mania's eye, orientation and field of view: the orbit in the intro state, its end pose in
//     the READY state (instead of the player timeline's second fly-in).
// The title card, READY, GO and the ball's entrance stay the game's. Rumble's own stages have no "intro" line:
// nothing changes for them. BR_MANIA_INTRO=0 turns it off; BR_MANIA_LOG=1 logs the start and a pose twice a second.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_GET_SELECTOR 0x43dbad0ull         // Wonder.RuntimeParam.get_selector (static) -> SelectorParam
#define F_CURRENT_STAGE 0x4357000ull        // Wonder.StageList.GetCurrentStage() -> Stage.eID
#define SELECTOR_STAGELIST 0x28             // SelectorParam.m_StageList
#define F_FADE_STATE 0x4637100ull           // Wonder.UI.Fade.UIFadeManager.get_stateKind (static): 1 None (nothing shown)
#define FADE_NONE 1
// Cinemachine.CameraState as the brain gets it (by reference, no object header)
#define CS_FOV 0x00                         // Lens.FieldOfView
#define CS_RAW_POSITION 0x4c
#define CS_RAW_ORIENTATION 0x58
#define CS_POSITION_CORRECTION 0x78
#define CS_ORIENTATION_CORRECTION 0x84
#define CS_BLEND_HINT 0x94                  // bits 0 NoPosition, 1 NoOrientation, 6 NoLens

#define MANIA_SECONDS 6.0                   // 360 frames of 1/60 s
#define START_PITCH -60.254f
#define END_PITCH -18.281f
#define END_DISTANCE 3.362f
#define LOOK_UP 0.98f
#define FIELD_OF_VIEW 60.0f
#define MAX_INTROS 1024
#define GONE 0.25                           // seconds without a question: that state is over

static struct { uint32_t stage; float v[8]; } g_intro[MAX_INTROS];
static int g_nintro = -1;
static int g_cur = -1;                      // index of the stage being introduced, -1 none (or skipped)
static uint64_t g_ctrl;                     // the timeline controller asking
static double g_t0;                         // when the orbit began, 0 = the loading screen is still up
static double g_intro_last, g_ready_last;   // last question of the intro / READY state
static int g_jumped;                        // the READY timelines of this intro have been moved on

static double now(void) {
    static LARGE_INTEGER f;
    LARGE_INTEGER t;
    if (!f.QuadPart) QueryPerformanceFrequency(&f);
    QueryPerformanceCounter(&t);
    return (double)t.QuadPart / (double)f.QuadPart;
}
static int logging(void) { static int on = -1; if (on < 0) on = getenv("BR_MANIA_LOG") != NULL; return on; }

static void load(void) {
    char path[700], line[256];
    g_nintro = 0;
    const char *off = getenv("BR_MANIA_INTRO");
    if (off && off[0] == '0') return;
    snprintf(path, sizeof path, "%smania\\mania_courses.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && g_nintro < MAX_INTROS) {
        unsigned id;
        float *v = g_intro[g_nintro].v;
        if (sscanf(line, "intro %u %f %f %f %f %f %f %f %f", &id, v, v + 1, v + 2, v + 3, v + 4, v + 5, v + 6, v + 7) == 9)
            g_intro[g_nintro++].stage = id;
    }
    fclose(f);
}

static void put(uint64_t at, float f) { memcpy((void *)(uintptr_t)at, &f, 4); }

// Wonder.MgBeginningTimelineController::StageTimelineUpdate(bool isSkip) -> is the stage timeline over
int rt_hook_442d1e0(Cpu *c) {
    if (g_nintro < 0) load();
    if (!g_nintro) return 0;
    uint64_t ctrl = c->x[0];
    int skip = (int)(c->x[1] & 1);
    double t = now();
    uint64_t sx[31]; __uint128_t sv[32];
    memcpy(sx, c->x, sizeof sx); memcpy(sv, c->v, sizeof sv);
    if (ctrl != g_ctrl || t - g_intro_last > 0.5) {            // a new intro
        uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
        uint32_t stage = list ? (uint32_t)rt_call(c, FN(F_CURRENT_STAGE), 2, list, 0ull) : 0;
        g_cur = -1;
        for (int i = 0; i < g_nintro; i++)
            if (g_intro[i].stage == stage) { g_cur = i; break; }
        if (g_cur >= 0 && logging()) rt_log("mania: intro of stage row %u%s", stage, skip ? ": skipped" : ": Banana Mania's camera");
        g_ctrl = ctrl; g_t0 = 0; g_jumped = 0;
    }
    g_intro_last = t;
    if (g_cur >= 0 && !skip && !g_t0 && (int)rt_call(c, FN(F_FADE_STATE), 1, 0ull) == FADE_NONE) {
        g_t0 = t;
        if (logging()) rt_log("mania: intro: the loading screen has gone, the camera starts");
    }
    memcpy(c->x, sx, sizeof sx); memcpy(c->v, sv, sizeof sv);
    if (skip) g_cur = -1;
    if (g_cur < 0) return 0;
    if (!g_t0 || t - g_t0 < MANIA_SECONDS) { c->x[0] = 0; return 1; }     // not over yet
    return 0;
}

// Wonder.MgBeginningTimelineController::PlayerTimelineUpdate(bool isSkip): the READY state is on
// Also: the READY timeline (3.5 s) begins with the game's camera flying in from the front, 1.75 s before the READY
// text. Mania's camera is already behind the ball, so that part was a still picture. On the first READY frame after
// Mania's intro each player's READY timeline jumps to its own "short" point (m_SkipTimeShort, the game's shortened
// READY), with the game's forward-only SetTime.
#define CTRL_PLAYER_TIMELINES 0x80          // MgBeginningTimelineController.m_PlayerOpeningAssetTimelineList
#define PLAYER_SKIP_TIME_SHORT 0x58         // PlayableDirectorInterfaceBeginningPlayer.m_SkipTimeShort (double)
#define F_TIMELINE_SET_TIME 0x442b360ull    // PlayableDirectorInterface.SetTime(double time, bool isEnabledBack)
#define F_TIMELINE_DURATION 0x442ea20ull    // PlayableDirectorInterface.GetDuration
int rt_hook_442d600(Cpu *c) {
    if (g_cur < 0) return 0;
    g_ready_last = now();
    if (g_jumped || (c->x[1] & 1) || !g_t0) return 0;
    g_jumped = 1;
    uint64_t list = LD64(c->x[0] + CTRL_PLAYER_TIMELINES), items = list ? LD64(list + 0x10) : 0;
    int n = list ? (int)LD32(list + 0x18) : 0;
    uint64_t sx[31]; __uint128_t sv[32];
    memcpy(sx, c->x, sizeof sx); memcpy(sv, c->v, sizeof sv);
    for (int i = 0; i < n && items; i++) {
        uint64_t p = LD64(items + 0x20 + 8 * (uint64_t)i);
        if (!p) continue;
        double at, dur;
        memcpy(&at, (void *)(uintptr_t)(p + PLAYER_SKIP_TIME_SHORT), 8);
        c->x[0] = p; c->x[1] = 0;
        rt_call_regs(c, FN(F_TIMELINE_DURATION));
        memcpy(&dur, &c->v[0], 8);
        if (!(at > 0 && at < dur)) continue;
        c->x[0] = p; c->x[1] = 0; c->x[2] = 0; memcpy(&c->v[0], &at, 8);
        rt_call_regs(c, FN(F_TIMELINE_SET_TIME));
        if (logging()) rt_log("mania: intro: READY timeline %d of %d starts at %.2f s of %.2f (no fly-in)", i + 1, n, at, dur);
    }
    memcpy(c->x, sx, sizeof sx); memcpy(c->v, sv, sizeof sv);
    return 0;
}

// q = rotation about y by `yaw`, then about x by `pitch` (Unity's Quaternion.Euler(pitch, yaw, 0)), degrees
static void euler_xy(float pitch, float yaw, float q[4]) {
    float hx = pitch * 0.00872664626f, hy = yaw * 0.00872664626f;
    float sx = sinf(hx), cx = cosf(hx), sy = sinf(hy), cy = cosf(hy);
    q[0] = cy * sx; q[1] = sy * cx; q[2] = -sy * sx; q[3] = cy * cx;
}
static void rotate(const float q[4], const float v[3], float out[3]) {
    float x = q[0], y = q[1], z = q[2], w = q[3];
    float tx = 2 * (y * v[2] - z * v[1]), ty = 2 * (z * v[0] - x * v[2]), tz = 2 * (x * v[1] - y * v[0]);
    out[0] = v[0] + w * tx + (y * tz - z * ty);
    out[1] = v[1] + w * ty + (z * tx - x * tz);
    out[2] = v[2] + w * tz + (x * ty - y * tx);
}

// Where the orbit is now: 1 at its start, 0 at its end; -1 when neither the intro nor the READY state is on
static float progress(double t) {
    if (g_cur < 0) return -1;
    if (t - g_intro_last < GONE) {                              // the intro state (waiting under the loading screen)
        float r = g_t0 ? 1.0f - (float)((t - g_t0) / MANIA_SECONDS) : 1.0f;
        return r < 0 ? 0 : r;
    }
    return t - g_ready_last < GONE ? 0.0f : -1.0f;              // READY: the orbit's end
}

// Mania's camera at progress r: eye, look-at point, orientation
static void pose(float r, float eye[3], float look[3], float view[4], float *pitch_out, float *yaw_out, float *dist_out) {
    const float *v = g_intro[g_cur].v;
    float s = r * r * (3.0f - 2.0f * r);
    float to[3] = {v[4], v[5] + LOOK_UP, v[6]};
    for (int i = 0; i < 3; i++) look[i] = to[i] + (v[i] - to[i]) * s;
    float pitch = END_PITCH + (START_PITCH - END_PITCH) * s, yaw = v[7] - 360.0f * s;
    float dist = END_DISTANCE + (v[3] - END_DISTANCE) * s;
    float q[4], back[3] = {0, 0, dist}, off[3];
    euler_xy(pitch, yaw, q);
    rotate(q, back, off);
    for (int i = 0; i < 3; i++) eye[i] = look[i] + off[i];
    euler_xy(-pitch, yaw + 180.0f, view);                      // from the eye towards the look-at point, level horizon
    *pitch_out = pitch; *yaw_out = yaw; *dist_out = dist;
}

// Wonder.MgCameraStateReady::setPos(GameObject camera): the game camera of the READY state (also on, under the stage
// timeline's own camera, during the intro). It sets the controller's gazing point and the camera's position; here
// they are Mania's.
#define F_SET_GAZING_POINT 0x429c430ull     // Wonder.MgCameraState.SetGazingPoint(Vector3)
#define F_GO_TRANSFORM 0x3f0bb40ull         // UnityEngine.GameObject.get_transform
#define F_SET_POSITION 0x3f1a2c0ull         // UnityEngine.Transform.set_position(Vector3)
#define F_SET_ROTATION 0x3f1a850ull         // UnityEngine.Transform.set_rotation(Quaternion)
static void put_v(Cpu *c, const float *f, int n) {
    for (int i = 0; i < n; i++) { uint32_t u; memcpy(&u, &f[i], 4); c->v[i] = u; }
}
#define READY_RATIO 0x58                    // MgCameraStateReady.m_Ratio: how far the READY timeline is, 0..1
#define GAZING_POINT 0x20                   // MgCameraState.m_GazingPoint
#define F_GET_POSITION 0x3f1a1f0ull         // UnityEngine.Transform.get_position
#define CTRL_STAGE_TIMELINE 0x78            // MgBeginningTimelineController.m_OpeningAssetTimeline (null: no title card)
#define F_STRING_NEW_UTF16 0x45af94ull      // il2cpp::vm::String::NewUtf16(const Il2CppChar *, int32_t)
#define F_GO_GET_COMPONENT_NAME 0x3f0adf0ull // GameObject.GetComponent(string type)
#define F_BEHAVIOUR_GET_ENABLED 0x3f072d0ull
#define F_BEHAVIOUR_SET_ENABLED 0x3f07320ull
#define BLEND_FROM 0.6f                    // READY: from this part on, Mania's end pose blends into the game's own
static void get_v(Cpu *c, float *f, int n) {
    for (int i = 0; i < n; i++) { uint32_t u = (uint32_t)c->v[i]; memcpy(&f[i], &u, 4); }
}
int rt_hook_42aa8f0(Cpu *c) {
    static int inside;
    if (inside) return 0;                                       // the game's own setPos, called from below
    double t = now();
    float r = progress(t);
    if (r < 0 || !c->x[1]) return 0;
    uint64_t state = c->x[0], camera = c->x[1], lr = c->x[30];
    float eye[3], look[3], view[4], pitch, yaw, dist;
    pose(r, eye, look, view, &pitch, &yaw, &dist);
    uint64_t tr = rt_call(c, FN(F_GO_TRANSFORM), 2, camera, 0ull);
    // A world whose title card is "none" (editor) has no stage timeline, so no timeline camera draws the intro, and
    // the game camera stays off until READY: the screen was black for the six seconds. Then the game camera draws it.
    if (r > 0 && g_ctrl && !LD64(g_ctrl + CTRL_STAGE_TIMELINE)) {
        static const uint16_t name[] = {'C', 'a', 'm', 'e', 'r', 'a'};
        uint64_t s = rt_call(c, FN(F_STRING_NEW_UTF16), 2, (uint64_t)(uintptr_t)name, 6ull);
        uint64_t cam = s ? rt_call(c, FN(F_GO_GET_COMPONENT_NAME), 3, camera, s, 0ull) : 0;
        if (cam && !((int)rt_call(c, FN(F_BEHAVIOUR_GET_ENABLED), 2, cam, 0ull) & 1)) {
            rt_call(c, FN(F_BEHAVIOUR_SET_ENABLED), 3, cam, 1ull, 0ull);
            if (logging()) rt_log("mania: intro: no stage timeline (no title card): the game camera draws the intro");
        }
    }
    // In READY the game's camera flies in from the front and ends where play begins. Mania's end pose is a little
    // closer: over the last part of READY it is blended into the game's own pose, so GO does not jump.
    float ratio = 0, w = 0;
    memcpy(&ratio, (void *)(uintptr_t)(state + READY_RATIO), 4);
    if (r == 0 && tr && ratio > BLEND_FROM) {
        float own_eye[3], own_look[3];
        inside = 1;
        rt_call(c, FN(0x42aa8f0ull), 3, state, camera, 0ull);
        inside = 0;
        memcpy(own_look, (void *)(uintptr_t)(state + GAZING_POINT), 12);
        c->x[0] = tr; c->x[1] = 0; rt_call_regs(c, FN(F_GET_POSITION)); get_v(c, own_eye, 3);
        float k = (ratio - BLEND_FROM) / (1.0f - BLEND_FROM);
        if (k > 1) k = 1;
        w = k * k * (3.0f - 2.0f * k);
        float f[3];
        for (int i = 0; i < 3; i++) {
            eye[i] += (own_eye[i] - eye[i]) * w;
            look[i] += (own_look[i] - look[i]) * w;
            f[i] = look[i] - eye[i];
        }
        float len = sqrtf(f[0] * f[0] + f[1] * f[1] + f[2] * f[2]);
        if (len > 1e-4f) euler_xy(asinf(-f[1] / len) * 57.2957795f, atan2f(f[0], f[2]) * 57.2957795f, view);
    }
    static double logged;
    if (logging() && t - logged > 1.0) {
        logged = t;
        rt_log("mania: intro: the READY camera state takes Mania's pose (r %.3f, READY %.2f, blended %.2f)", r, ratio, w);
    }
    c->x[0] = state; c->x[1] = 0; put_v(c, look, 3);
    rt_call_regs(c, FN(F_SET_GAZING_POINT));
    if (tr) {
        c->x[0] = tr; c->x[1] = 0; put_v(c, eye, 3);
        rt_call_regs(c, FN(F_SET_POSITION));
        c->x[0] = tr; c->x[1] = 0; put_v(c, view, 4);
        rt_call_regs(c, FN(F_SET_ROTATION));
    }
    c->x[30] = lr;
    return 1;
}

// Cinemachine.CinemachineBrain::PushStateToUnityCamera(ref CameraState state)
int rt_hook_20c7800(Cpu *c) {
    if (g_cur < 0 || !c->x[1]) return 0;
    double t = now();
    float r = progress(t);
    if (r < 0) return 0;
    float eye[3], look[3], view[4], pitch, yaw, dist;
    pose(r, eye, look, view, &pitch, &yaw, &dist);
    uint64_t st = c->x[1];
    for (int i = 0; i < 3; i++) put(st + CS_RAW_POSITION + 4 * i, eye[i]);
    for (int i = 0; i < 4; i++) put(st + CS_RAW_ORIENTATION + 4 * i, view[i]);
    for (int i = 0; i < 3; i++) put(st + CS_POSITION_CORRECTION + 4 * i, 0.0f);
    for (int i = 0; i < 4; i++) put(st + CS_ORIENTATION_CORRECTION + 4 * i, i == 3 ? 1.0f : 0.0f);
    put(st + CS_FOV, FIELD_OF_VIEW);
    uint32_t hint = LD32(st + CS_BLEND_HINT) & ~(uint32_t)(1 | 2 | 64);
    memcpy((void *)(uintptr_t)(st + CS_BLEND_HINT), &hint, 4);
    static double logged;
    if (logging() && t - logged > 0.5) {
        logged = t;
        rt_log("mania: intro %.2f s after the loading screen, r %.3f: eye (%.2f, %.2f, %.2f) looks at (%.2f, %.2f, %.2f), pitch %.1f heading %.1f distance %.2f",
               g_t0 ? t - g_t0 : -1.0, r, eye[0], eye[1], eye[2], look[0], look[1], look[2], pitch, yaw, dist);
    }
    return 0;
}
