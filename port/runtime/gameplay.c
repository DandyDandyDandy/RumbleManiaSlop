// Gameplay options for Banana Mania's stages (RumbleManiaSlop only): Spin Dash on or off, Ball Physics Rumble or Mania.
//
// Banana Mania's stages were made for a ball without the Spin Dash and with Mania's physics, so the player can turn
// the Spin Dash off and have the ball move as in Mania. Both options work the same way; for the Spin Dash:
//
//  * Single player: the row Options > General > Spin Dash (Single Player), kept as `spindash=` in
//    <user dir>port_gameplay.txt. On by default.
//  * Multiplayer Adventure (split screen and online): the row Spin Dash under Ball Collision on the game settings
//    screen (`spindash_multi=`). Online the host's choice holds for the whole room: it travels to the guests in the
//    "advanced settings" the host sends with every stage start (AdvGameMaster: int[2] = time limit, ball collision
//    off), as bit 1 of the second number, and is taken out again before the game reads it.
//  * Battle modes, the tutorial (it waits for a Spin Dash) and replays are never changed.
//
// Off means: the local player's charge button is not seen by the spin module (PlayerSpinActionModule's two input
// questions answer "not pressed"), and the charge gauge of the HUD (the ring around the face) is not shown. Other
// players' dashes online are played as their machines report them. BR_SPIN_LOG=1 logs each change of what applies.
//
// Ball Physics: Rumble (the default) or Mania: the players' balls with Banana Mania's gravity, bounce, friction and
// tilt values and without Rumble's speed cap (see "Ball Physics: Mania" below). Rows: Options > General > Ball
// Physics (Single Player) (`ballphysics=`, 1 = Mania) and a Ball Physics picker on the multiplayer game settings
// screen (`ballphysics_multi=`), sent to the room's guests as bit 2 of the same number. Same modes as the Spin Dash:
// never in Battle, the tutorial or replays. BR_SPEED_LOG=1 logs the mode and, each second, the fastest a ball went
// and in how many physics steps it touched the stage.
#include <windows.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_GET_MAIN_GAME 0x43db8d0ull        // Wonder.RuntimeParam::get_mainGame (static): null before the object exists
#define F_GET_BATTLE 0x43dbb50ull           // Wonder.RuntimeParam::get_battle (static)
#define F_IS_BATTLE_MODE 0x43de0a0ull       // BattleParam::get_isBattleMode: the BattleRoyale object exists
#define F_REPLAY_IS_PLAYING 0x437a7c0ull    // Wonder.ReplayManager::get_isPlaying (static)
#define F_PARTVIEW_SET_ACTIVE 0x4515ef0ull  // UI.UIPartViewBase::SetActive(bool)
#define F_GET_ADV_SETTINGS 0x2179830ull     // AdvGameMaster::getAdvancedSettings() -> int[2]
#define F_ROW_INIT 0x4649b10ull             // UIViewCtrl_AdvMulti_GameSetting::onInitSelectableButtonForBallCollision (static)
#define F_SETUP_ITEM_LIST 0x464a040ull      // UIViewCtrl_AdvMulti_GameSetting::setupChoicesItemList(Course.eID)
#define F_SET_VALUE_TEXT 0x4507450ull       // UIPartViewSelectablePicker_Base::SetSettingValueText(string)
#define F_SET_TEXT 0x45117c0ull             // UIPartViewSelectableButton::SetText(string)
#define F_OBJECT_NEW 0x469f40ull            // il2cpp_object_new(klass)
#define F_GC_DISABLE 0x469d10ull
#define F_GC_ENABLE 0x469d00ull
#define F_GCHANDLE_NEW 0x469da0ull          // il2cpp_gchandle_new(obj, pinned)
#define F_GCHANDLE_TARGET 0x469df0ull
#define F_GCHANDLE_FREE 0x469e10ull
#define F_LIST_ADD_WITH_RESIZE 0x33bfab0ull // List<object>::AddWithResize(item, MethodInfo *)

#define MAINGAME_TUTORIAL 0x50              // MainGameParam.m_TutorialParam
#define TUTORIAL_IS_TUTORIAL 0x10
#define BATTLE_IS_ONLINE 0x10               // BattleParam.isOnlineMode
#define BATTLE_GAME_MASTER 0x20             // BattleParam.gameMaster
#define CTRL_VIEW 0x20                      // UIMgPlayerViewCtrl_Base -> its UIViewMainGamePlayer
#define VIEW_SPIN_GAUGE 0x40                // ...the UIPartViewMainGameSpinAttackGauge (+0x48 is the speedometer)
#define MODULE_PLAYER 0x18                  // PlayerSpinActionModule.m_Player
#define PLAYER_IS_LOCAL 0x1c0               // MgPlayer.m_IsLocal
#define VIEW_ITEM_COLLISION 0x78            // UIViewCtrl_AdvMulti_GameSetting.m_InnerItemData_BallCallision
#define ITEM_SIZE 0x40                      // UIChoicesInnerItemData_BallCollision
#define ITEM_INDEX 0x20                     // UIChoicesItemData_ForPickerBase.currentIndex
#define ITEM_PREV_INDEX 0x28
#define ITEM_ELEMENTS 0x30                  // UIChoicesItemData_ForPicker<T>.elementList
#define ELEMENT_RECORD 0x10                 // UIChoicesItemPickerElement_BallCollision.record
#define RECORD_RAW 0x20                     // DB record -> raw record, whose first field is the id
#define COLLISION_ON 2                      // DB.MainGame.BallCollision.eID of the "on" choice (1 is "off")
#define LIST_ITEMS 0x10
#define LIST_SIZE 0x18
#define ARR_DATA 0x20
#define KLASS_NAME 0x10
#define KLASS_RGCTX 0xc0                    // List<T> class: generic context data, +0x70 = AddWithResize

static int g_single = 1, g_multi = 1, g_room = 1, g_loaded;
static int g_fast_single, g_fast_multi, g_fast_room;       // Ball Physics: 1 = Mania
#define NROWS 2                             // the rows added to the multiplayer game settings: Spin Dash, Ball Physics
static uint32_t g_row_h[NROWS];             // GC handles of those row objects

uint64_t rt_tr_str(Cpu *c, const char *english);      // port_text.c

static void cfg_path(char *out, size_t n) { snprintf(out, n, "%sport_gameplay.txt", rt_user_dir()); }
static void load(void) {
    if (g_loaded) return;
    g_loaded = 1;
    char path[MAX_PATH + 32], line[64];
    int v;
    cfg_path(path, sizeof path);
    FILE *f = fopen(path, "r");
    while (f && fgets(line, sizeof line, f)) {
        if (sscanf(line, "spindash=%d", &v) == 1) g_single = v != 0;
        else if (sscanf(line, "spindash_multi=%d", &v) == 1) g_multi = v != 0;
        else if (sscanf(line, "ballphysics=%d", &v) == 1) g_fast_single = v != 0;
        else if (sscanf(line, "ballphysics_multi=%d", &v) == 1) g_fast_multi = v != 0;
    }
    if (f) fclose(f);
    g_room = g_multi;
    g_fast_room = g_fast_multi;
}
static void save(void) {
    char path[MAX_PATH + 32];
    cfg_path(path, sizeof path);
    FILE *f = fopen(path, "w");
    if (!f) return;
    fprintf(f, "spindash=%d\nspindash_multi=%d\nballphysics=%d\nballphysics_multi=%d\n", g_single, g_multi, g_fast_single, g_fast_multi);
    fclose(f);
}
// For the Options rows (display_opt.c).
int spindash_single(void) { load(); return g_single; }
void spindash_set_single(int on) { load(); g_single = on != 0; save(); }
int ballspeed_single(void) { load(); return g_fast_single; }
void ballspeed_set_single(int mania) { load(); g_fast_single = mania != 0; save(); }

static int list_n(uint64_t list) { return list ? (int32_t)LD32(list + LIST_SIZE) : 0; }
static uint64_t list_at(uint64_t list, int i) { return LD64(LD64(list + LIST_ITEMS) + ARR_DATA + 8 * (uint64_t)i); }
static const char *class_name(uint64_t obj) { return obj ? (const char *)(uintptr_t)LD64(LD64(obj) + KLASS_NAME) : ""; }

// What is being played now: 0 single player, 1 tutorial, 2 split screen Adventure, 3 online Adventure, 4 Battle.
static int play_kind(Cpu *c) {
    uint64_t mg = rt_call(c, FN(F_GET_MAIN_GAME), 1, 0ull);
    uint64_t tut = mg ? LD64(mg + MAINGAME_TUTORIAL) : 0;
    uint64_t battle = rt_call(c, FN(F_GET_BATTLE), 1, 0ull);
    if (tut && LD8(tut + TUTORIAL_IS_TUTORIAL)) return 1;
    if (!battle || !(rt_call(c, FN(F_IS_BATTLE_MODE), 2, battle, 0ull) & 1)) return 0;
    if (strcmp(class_name(LD64(battle + BATTLE_GAME_MASTER)), "AdvGameMaster")) return 4;
    return LD8(battle + BATTLE_IS_ONLINE) ? 3 : 2;
}
static const char *const KIND_NAMES[] = {"single player", "tutorial", "split screen Adventure", "online Adventure", "Battle"};

// Whether the local players may Spin Dash in what is being played now.
static int allowed(Cpu *c) {
    load();
    int kind = play_kind(c), v = kind == 0 ? g_single : kind == 2 ? g_multi : kind == 3 ? g_room : 1;
    static int log = -1, last = -1;
    if (log < 0) log = getenv("BR_SPIN_LOG") != NULL;
    if (log && last != kind * 2 + v) {
        last = kind * 2 + v;
        rt_log("spindash: %s, Spin Dash %s", KIND_NAMES[kind], v ? "on" : "off");
    }
    return v;
}

// Whether the players' balls move by Banana Mania's physics (and without Rumble's speed cap) in what is being played now.
static int mania_physics(Cpu *c) {
    load();
    int kind = play_kind(c), v = kind == 0 ? g_fast_single : kind == 2 ? g_fast_multi : kind == 3 ? g_fast_room : 0;
    if (v && (rt_call(c, FN(F_REPLAY_IS_PLAYING), 1, 0ull) & 1)) v = 0;
    static int log = -1, last = -1;
    if (log < 0) log = getenv("BR_SPEED_LOG") != NULL;
    if (log && last != kind * 2 + v) {
        last = kind * 2 + v;
        rt_log("ballspeed: %s, Ball Physics %s", KIND_NAMES[kind], v ? "Mania" : "Rumble");
    }
    return v;
}

// Run `expr` (guest calls) from an entry hook that lets the game's function run afterwards: its arguments survive.
#define KEEP_ARGS(expr) do { uint64_t sx_[19], lr_ = c->x[30]; memcpy(sx_, c->x, sizeof sx_); expr; memcpy(c->x, sx_, sizeof sx_); c->x[30] = lr_; } while (0)

// PlayerSpinActionModule.getMainActionInput() / getMainActionDownInput(): is the charge button held / just pressed.
// A player of another machine and a replay take other paths in there and are left alone.
static int input_hook(Cpu *c) {
    uint64_t player = c->x[0] ? LD64(c->x[0] + MODULE_PLAYER) : 0;
    if (!player || !LD8(player + PLAYER_IS_LOCAL)) return 0;
    int off = 0;
    KEEP_ARGS(off = !allowed(c) && !(rt_call(c, FN(F_REPLAY_IS_PLAYING), 1, 0ull) & 1));
    if (!off || c->eh_unwinding) return 0;
    c->x[0] = 0;
    return 1;
}
int rt_hook_4307c30(Cpu *c) { return input_hook(c); }
int rt_hook_43084a0(Cpu *c) { return input_hook(c); }

// Ball Physics: Mania. A player's ball moves in two steps each physics frame: MainGamePlayerBall.BallMove (gravity,
// rotated by the stage tilt, its sideways part scaled) and PhysicsBall.BallCollision (stage contact: bounce and
// friction; then Rumble's speed cap). Values shared with other balls are swapped in for each of the two steps and
// put back after it (the character tables are shared: CPUs and Battle stay untouched); the ball's own values stay set
// while Mania applies (own_values). A change in the pause menu holds from the next step. Mania's values (its
// GameParam.physicsParam, sharedassets0.assets):
//
//                              Mania      Rumble (AiAi)            where Rumble keeps it
//   gravity                    0.0098     0.012 x 0.99             ball m_Gravity (+0x28); SPHERE.gravity (+0x40)
//   restitution (bounce)       0.5        0.3                      SPHERE.restitution (+0x44)
//   friction                   0.01       0.018 x 0.725            SPHERE.friction (+0x98)
//   gravityXZGeneral           1.0        1.4                      the ball's CharaParam.PhysicsParam (+0x10)
//   gravityXZDirectional       0.11       0                        same (+0x14)
//   gravityBackwardsDamping    1.0        0.65                     GameParam.physicsParam (+0x18)
//   slideVanish                (none)     0.001                    GameParam.physicsParam (+0x20); set to 0
//   staticFrictionThreshold    (none)     0.001                    same (+0x24); set to 0
//   speed cap                  none       500 km/h                 ball m_IsEnableSpeedLimit (+0x8a)
//
// The bounce matters most: on a curved track a fast ball's velocity points into the wall each frame, Mania bounces it
// off (it touches on about 17 of 60 frames on Coaster), Rumble's keeps it pressed on (60 of 60), and friction only
// acts on a touch. Measured on Coaster (st2010) holding forward: Mania itself (BananaModManager probe) up to 378 km/h
// on the track, then the ball leaves it; Rumble 144 km/h at most; Rumble with these values up to 376 km/h, then the
// ball leaves the track the same way (MANIA.md "Ball Physics").
#define F_BALL_COLLISION 0x42ed590ull
#define F_BALL_MOVE 0x42e57b0ull            // MainGamePlayerBall.BallMove
#define BALL_GRAVITY 0x28                   // PhysicsBall.m_Gravity
#define BALL_SPHERE_OWNER 0x38              // PhysicsBall.m_CollisionSphere; its +0x68 is the MonkeyPhysics.SPHERE
#define BALL_VELOCITY 0x64                  // PhysicsBall.m_Velocity (metres per physics step)
#define BALL_SPEED_LIMIT 0x8a               // PhysicsBall.m_IsEnableSpeedLimit
#define BALL_CHARA_PHYSICS 0xf0             // MainGamePlayerBall.m_PhysicsParam (CharaParam.PhysicsParam)
#define MPF_TO_KPH 215.78f                  // Util.Math.KphToMpf divides by this
#define F_GET_PHYSICS_PARAM 0x43abde0ull    // Wonder.GameParam.get_physicsParam (static)
#define PP_GENERAL_MAX 0x54                 // GameParam.PhysicsParam.generalMaxSpeed (km/h; 500 in the game's data)
static float LDF(uint64_t a) { float f; memcpy(&f, (const void *)(uintptr_t)a, 4); return f; }
static void STF(uint64_t a, float f) { memcpy((void *)(uintptr_t)a, &f, 4); }
static uint64_t sphere_of(uint64_t ball) { uint64_t cs = LD64(ball + BALL_SPHERE_OWNER); return cs ? LD64(cs + 0x68) : 0; }

typedef struct { uint64_t at[8]; float old[8]; int n; } Swap;
static void swap_in(Swap *s, uint64_t a, float mania) {
    if (!a) return;
    s->at[s->n] = a; s->old[s->n] = LDF(a); s->n++;
    STF(a, mania);
}
static void swap_back(Swap *s) { while (s->n > 0) { s->n--; STF(s->at[s->n], s->old[s->n]); } }
// The values shared with other balls (the character's table, the game's physics param) are swapped for each step.
static void mania_values(Swap *s, uint64_t ball, uint64_t pp) {
    uint64_t cp = LD64(ball + BALL_CHARA_PHYSICS);
    s->n = 0;
    if (cp) { swap_in(s, cp + 0x10, 1.0f); swap_in(s, cp + 0x14, 0.11f); }
    if (pp) swap_in(s, pp + 0x18, 1.0f);
    if (pp) { swap_in(s, pp + 0x20, 0.0f); swap_in(s, pp + 0x24, 0.0f); }      // Rumble-only: slideVanish, staticFrictionThreshold
}
// The ball's own values (its gravity, its SPHERE's gravity, bounce and friction) are also read outside the two steps
// (ground checks), so they stay on the ball while Mania applies and are put back when it stops applying. The game
// writes them anew when a stage (re)starts (SetBall), so a ball whose values look fresh is taken over again.
#define OWN_N 4
typedef struct { uint64_t ball, sp; float rumble[OWN_N]; } Own;
static Own g_own[8];
static uint64_t own_addr(const Own *o, int i) { return i == 0 ? o->ball + BALL_GRAVITY : o->sp + (i == 1 ? 0x40 : i == 2 ? 0x44 : 0x98); }
static const float MANIA_OWN[OWN_N] = {0.0098f, 0.0098f, 0.5f, 0.01f};
static void own_values(uint64_t ball, int mania) {
    uint64_t sp = sphere_of(ball);
    Own *o = NULL, *free_slot = NULL;
    for (int i = 0; i < 8; i++) {
        if (g_own[i].ball == ball) o = &g_own[i];
        else if (!g_own[i].ball && !free_slot) free_slot = &g_own[i];
    }
    if (o && (o->sp != sp || LDF(own_addr(o, 0)) != MANIA_OWN[0] || LDF(own_addr(o, 3)) != MANIA_OWN[3])) {
        o->ball = 0;      // reset by the game (or another sphere): Rumble's values are the ones there now
        o = NULL;
    }
    if (mania && !o && sp) {
        o = free_slot ? free_slot : &g_own[0];
        o->ball = ball; o->sp = sp;
        for (int i = 0; i < OWN_N; i++) { o->rumble[i] = LDF(own_addr(o, i)); STF(own_addr(o, i), MANIA_OWN[i]); }
    } else if (!mania && o) {
        for (int i = 0; i < OWN_N; i++) STF(own_addr(o, i), o->rumble[i]);
        o->ball = 0;
    }
}

static void speed_log(Cpu *c, uint64_t ball) {
    static int log = -1, params, steps, contacts;
    static float peak;
    static DWORD since;
    if (log < 0) log = getenv("BR_SPEED_LOG") != NULL;
    if (!log) return;
    if (!params) {      // the cap, and Rumble's own values for this ball
        params = 1;
        uint64_t pp = rt_call(c, FN(F_GET_PHYSICS_PARAM), 1, 0ull), cp = LD64(ball + BALL_CHARA_PHYSICS), sp = sphere_of(ball);
        if (pp && !c->eh_unwinding) {
            const char *test = getenv("BR_SPEED_CAP_TEST");      // test aid: a low cap (km/h) to see it held and lifted
            if (test) STF(pp + PP_GENERAL_MAX, (float)atof(test));
            rt_log("ballspeed: generalMaxSpeed %.0f km/h; the ball's values now: gravity %g, restitution %g, friction %g, xz %g / %g, backwards %g",
                   LDF(pp + PP_GENERAL_MAX), LDF(ball + BALL_GRAVITY), sp ? LDF(sp + 0x44) : -1.0f, sp ? LDF(sp + 0x98) : -1.0f,
                   cp ? LDF(cp + 0x10) : -1.0f, cp ? LDF(cp + 0x14) : -1.0f, LDF(pp + 0x18));
        }
    }
    float v[3];
    memcpy(v, (const void *)(uintptr_t)(ball + BALL_VELOCITY), sizeof v);
    float kph = sqrtf(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) * MPF_TO_KPH;
    if (kph > peak) peak = kph;
    uint64_t sp = sphere_of(ball);      // steps in which the ball touched the stage (SPHERE flag bit 0)
    steps++;
    if (sp && (LD32(sp + 0x10) & 1)) contacts++;
    DWORD now = GetTickCount();
    if (now - since >= 1000) {
        if (peak > 1.0f) rt_log("ballspeed: fastest %.0f km/h (%.0f mph), contact in %d of %d steps", peak, peak / 1.609344f, contacts, steps);
        peak = 0;
        steps = contacts = 0;
        since = now;
    }
}

// Run one of the two steps (`fn`, re-entered with the bypass flag set) for a player's ball, with Mania's values when
// they apply. Only balls with m_IsEnableSpeedLimit are players' balls in a stage (PlayerStateMainGame sets it).
static int ball_step(Cpu *c, uint64_t fn, int *inside, int collision) {
    uint64_t ball = c->x[0], pp = 0;
    if (*inside || !ball || !LD8(ball + BALL_SPEED_LIMIT)) return 0;
    int mania = 0;
    KEEP_ARGS(mania = mania_physics(c); if (mania) pp = rt_call(c, FN(F_GET_PHYSICS_PARAM), 1, 0ull));
    if (c->eh_unwinding) return 0;
    Swap s = {0};
    own_values(ball, mania);
    if (mania) {
        mania_values(&s, ball, pp);
        if (collision) ST8(ball + BALL_SPEED_LIMIT, 0);
    }
    *inside = 1; c->pc = FN(fn); rt_dispatch(c); *inside = 0;
    if (mania) {
        swap_back(&s);
        if (collision) ST8(ball + BALL_SPEED_LIMIT, 1);
    }
    if (collision && !c->eh_unwinding) speed_log(c, ball);
    return 1;
}
int rt_hook_42ed590(Cpu *c) { static __thread int inside; return ball_step(c, F_BALL_COLLISION, &inside, 1); }
int rt_hook_42e57b0(Cpu *c) { static __thread int inside; return ball_step(c, F_BALL_MOVE, &inside, 0); }

// UIMgPlayerViewCtrl_Base.SpinAction_OnUpdateIdle(): a player's HUD is told, every frame the spin module idles, to
// show the charge gauge full. With the Spin Dash off the gauge (the ring around the character's face, with the
// button's glyph) is taken off the screen instead; the speedometer next to it stays. The game shows the gauge
// again in places (the HUD option, the pause menu), so this is repeated rather than done once.
int rt_hook_45ca090(Cpu *c) {
    uint64_t view = c->x[0] ? LD64(c->x[0] + CTRL_VIEW) : 0, gauge = view ? LD64(view + VIEW_SPIN_GAUGE) : 0;
    if (!gauge) return 0;
    int off = 0;
    KEEP_ARGS(off = !allowed(c));
    if (!off || c->eh_unwinding) return 0;
    rt_call(c, FN(F_PARTVIEW_SET_ACTIVE), 3, gauge, 0ull, 0ull);
    return 1;
}

// ------------------------------------------------------------------------------ the room's choice, host to guests
// AdvGameMaster.getAdvancedSettings(): what the host sends. The second number is "ball collision off" (0 or 1).
int rt_hook_2179830(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    load();
    inside = 1; c->pc = FN(F_GET_ADV_SETTINGS); rt_dispatch(c); inside = 0;
    uint64_t arr = c->x[0];
    if (c->eh_unwinding || !arr || (int32_t)LD32(arr + 0x18) < 2) return 1;
    g_room = g_multi;
    g_fast_room = g_fast_multi;
    uint32_t v = LD32(arr + ARR_DATA + 4);
    if (!g_room) v |= 2;
    if (g_fast_room) v |= 4;
    ST32(arr + ARR_DATA + 4, v);
    return 1;
}
// AdvGameMaster.OnRecvAdvInit(int[]) / setAdvancedSettings(int[]): what a machine of the room is told.
static int recv_hook(Cpu *c) {
    uint64_t arr = c->x[1];
    if (!arr || (int32_t)LD32(arr + 0x18) < 2) return 0;
    uint32_t v = LD32(arr + ARR_DATA + 4);
    load();
    g_room = !(v & 2);
    g_fast_room = (v & 4) != 0;
    ST32(arr + ARR_DATA + 4, v & 1);
    if (getenv("BR_SPIN_LOG")) rt_log("spindash: the room's settings say Spin Dash %s", g_room ? "on" : "off");
    if (getenv("BR_SPEED_LOG")) rt_log("ballspeed: the room's settings say Ball Physics %s", g_fast_room ? "Mania" : "Rumble");
    return 0;
}
int rt_hook_2179930(Cpu *c) { return recv_hook(c); }
int rt_hook_2179a30(Cpu *c) { return recv_hook(c); }

// ------------------------------------------------------------------------------ the row under Ball Collision
// The game settings screen of multiplayer Adventure (split screen: UIViewCtrl_AdvMultiSetting_Offline, online Create
// Room: UIViewCtrl_AdvMulti_GameSetting) is a list of row objects (the world picker, the Ball Collision picker, the
// Confirm button) shown by as many views of a fixed panel, each picker under a heading:
//
//     Bg_Title01 "World"           y 240      ui_PartView_Template_Vertical_Picker_0   y 144
//     Bg_Title02 "Ball Collision"  y 0        ui_PartView_Template_Vertical_Picker_1   y -96
//     Bg_Line                      y -295     ui_PartView_Template_SelectableButton    y -356
//
// (split screen; the online panel has one more picker and heading that this screen does not use, and its line is
// at -276). The Spin Dash and Ball Physics rows are copies of the Ball Collision row object, so the screen treats
// them as the same kind of picker with two choices; the two functions the screen calls for such a row tell the
// copies apart by their GC handles. Their views and headings are copies of Ball Collision's, and the four groups
// are spread evenly over the room the two had.
#define F_GET_TRANSFORM 0x3f07f60ull        // UnityEngine.Component.get_transform
#define F_GET_GAMEOBJECT 0x3f07fb0ull       // UnityEngine.Component.get_gameObject
#define F_OBJ_NAME 0x3f10820ull             // UnityEngine.Object.get_name
#define F_CHILD_COUNT 0x3f1e1f0ull          // Transform.get_childCount
#define F_GET_CHILD 0x3f1ea10ull            // Transform.GetChild(int)
#define F_INSTANTIATE 0x3f117f0ull          // UnityEngine.Object.Instantiate(Object original, Transform parent)
#define F_GET_PARENT 0x3f1a0a0ull           // Transform.get_parent
#define F_GET_ANCHORED_POS 0x3f182c0ull     // RectTransform.get_anchoredPosition -> Vector2 in v0, v1
#define F_SET_ANCHORED_POS 0x3f18390ull     // RectTransform.set_anchoredPosition(Vector2)
#define F_GO_GET_COMPONENT_NAME 0x3f0adf0ull   // GameObject.GetComponent(string type)
#define F_TMP_SET_TEXT 0x3e38300ull         // TMP_Text.SetText(string, bool syncTextInputBox)
#define F_STRING_NEW_UTF16 0x45af94ull      // il2cpp::vm::String::NewUtf16(const Il2CppChar *, int32_t)
#define VIEW_BUTTONS 0x40                   // UIViewBaseChoice: List<UIPartViewSelectableButton>, one per row
#define HEAD_TO_PICKER 88.0f                // a heading to its picker, a picker to the next heading, and the last picker
#define PICKER_TO_HEAD 96.0f                // to the line: the shares of the room (scaled to the panel's)
#define LINE_TO_PICKER 84.0f
static uint32_t g_head_h[NROWS];            // GC handles of the added headings' text components
static const char *const ROW_TITLE[NROWS] = {"Spin Dash", "Ball Physics"};

// The added row `item` is (0 Spin Dash, 1 Ball Physics), or -1 for the game's own rows.
static int my_row(Cpu *c, uint64_t item) {
    for (int r = 0; r < NROWS; r++)
        if (item && g_row_h[r] && rt_call(c, FN(F_GCHANDLE_TARGET), 1, (uint64_t)g_row_h[r]) == item) return r;
    return -1;
}
// Whether row r shows its "on" choice (the Ball Collision element "Collision"): Spin Dash on, Ball Physics Mania.
static int row_on(int r) { return r == 0 ? g_multi : g_fast_multi; }
static const char *row_value(int r) { return r == 0 ? (g_multi ? "On" : "Off") : g_fast_multi ? "Mania" : "Rumble"; }
static void row_set(int r, int on) {
    if (r == 0) g_multi = g_room = on;
    else g_fast_multi = g_fast_room = on;
    save();
}
static int element_id(uint64_t item, int i) {
    uint64_t list = LD64(item + ITEM_ELEMENTS), e = i >= 0 && i < list_n(list) ? list_at(list, i) : 0;
    uint64_t rec = e ? LD64(e + ELEMENT_RECORD) : 0, raw = rec ? LD64(rec + RECORD_RAW) : 0;
    return raw ? (int32_t)LD32(raw + 0x10) : 0;
}
static void keep(Cpu *c, uint32_t *h, uint64_t obj) {
    if (*h) rt_call(c, FN(F_GCHANDLE_FREE), 1, (uint64_t)*h);
    *h = obj ? (uint32_t)rt_call(c, FN(F_GCHANDLE_NEW), 2, obj, 0ull) : 0;
}
static uint64_t str8(Cpu *c, const char *s) {
    uint16_t w[64];
    int n = 0;
    for (; s[n] && n < 64; n++) w[n] = (uint8_t)s[n];
    return rt_call(c, FN(F_STRING_NEW_UTF16), 2, (uint64_t)(uintptr_t)w, (uint64_t)n);
}
static void get_floats(Cpu *c, uint64_t fn, uint64_t tr, float *f, int n) {
    c->x[0] = tr; c->x[1] = 0;
    rt_call_regs(c, FN(fn));
    for (int i = 0; i < n; i++) { uint32_t u = (uint32_t)c->v[i]; memcpy(&f[i], &u, 4); }
}
static void set_y(Cpu *c, uint64_t tr, float y) {
    float p[2] = {0, 0};
    if (!tr) return;
    get_floats(c, F_GET_ANCHORED_POS, tr, p, 2);
    p[1] = y;
    c->x[0] = tr; c->x[1] = 0;
    for (int i = 0; i < 2; i++) { uint32_t u; memcpy(&u, &p[i], 4); c->v[i] = u; }
    rt_call_regs(c, FN(F_SET_ANCHORED_POS));
}
static int name_cmp(Cpu *c, uint64_t tr, const char *name, int prefix) {
    uint64_t s = rt_call(c, FN(F_OBJ_NAME), 2, rt_call(c, FN(F_GET_GAMEOBJECT), 2, tr, 0ull), 0ull);
    int len = s ? (int32_t)LD32(s + 0x10) : 0, k = 0;
    for (; k < len && name[k] && LD16(s + 0x14 + 2ull * k) == (uint8_t)name[k]; k++) {}
    return !name[k] && (prefix || k == len);
}
static int name_is(Cpu *c, uint64_t tr, const char *name) { return name_cmp(c, tr, name, 0); }
static int name_starts(Cpu *c, uint64_t tr, const char *name) { return name_cmp(c, tr, name, 1); }
static uint64_t child_named(Cpu *c, uint64_t tr, const char *name) {
    int n = tr ? (int)rt_call(c, FN(F_CHILD_COUNT), 2, tr, 0ull) : 0;
    for (int i = 0; i < n; i++) {
        uint64_t ch = rt_call(c, FN(F_GET_CHILD), 3, tr, (uint64_t)i, 0ull);
        if (name_is(c, ch, name)) return ch;
    }
    return 0;
}
static void list_insert(Cpu *c, uint64_t list, int at, uint64_t obj) {      // obj becomes element `at`
    int n = list_n(list);
    rt_call(c, FN(F_LIST_ADD_WITH_RESIZE), 3, list, obj, LD64(LD64(LD64(list) + KLASS_RGCTX) + 0x70));
    if (c->eh_unwinding || list_n(list) != n + 1) return;
    uint64_t items = LD64(list + LIST_ITEMS) + ARR_DATA;
    for (int i = n; i > at; i--) ST64(items + 8ull * i, LD64(items + 8ull * (i - 1)));
    ST64(items + 8ull * at, obj);
}
static void set_heading(Cpu *c, int r) {
    uint64_t text = g_head_h[r] ? rt_call(c, FN(F_GCHANDLE_TARGET), 1, (uint64_t)g_head_h[r]) : 0;
    if (!text || !LD64(text + 0x10)) return;      // +0x10: the engine object; 0 once the screen is gone
    uint64_t s = rt_tr_str(c, ROW_TITLE[r]);
    if (!c->eh_unwinding) rt_call(c, FN(F_TMP_SET_TEXT), 4, text, s, 1ull, 0ull);
}

// The heading over a picker: the panel's "Bg_Title.." child nearest above it.
static uint64_t heading_over(Cpu *c, uint64_t panel, uint64_t picker_tr) {
    float py[2] = {0, 0}, best = 1e9f;
    uint64_t hit = 0;
    get_floats(c, F_GET_ANCHORED_POS, picker_tr, py, 2);
    int n = (int)rt_call(c, FN(F_CHILD_COUNT), 2, panel, 0ull);
    for (int i = 0; i < n; i++) {
        uint64_t ch = rt_call(c, FN(F_GET_CHILD), 3, panel, (uint64_t)i, 0ull);
        float y[2] = {0, 0};
        if (!name_starts(c, ch, "Bg_Title")) continue;
        get_floats(c, F_GET_ANCHORED_POS, ch, y, 2);
        if (y[1] > py[1] && y[1] - py[1] < best) { best = y[1] - py[1]; hit = ch; }
    }
    return hit;
}

// The picker views and the headings for the rows at index `at` + 1 .. `at` + NROWS, made from those of the Ball
// Collision row `at`, and all the groups spread between the World heading and the line over the Confirm button.
static void add_views(Cpu *c, uint64_t buttons, int at) {
    uint64_t picker = list_at(buttons, at), world = at > 0 ? list_at(buttons, at - 1) : 0;
    uint64_t ptr = picker ? rt_call(c, FN(F_GET_TRANSFORM), 2, picker, 0ull) : 0, wtr = world ? rt_call(c, FN(F_GET_TRANSFORM), 2, world, 0ull) : 0;
    uint64_t panel = ptr ? rt_call(c, FN(F_GET_PARENT), 2, ptr, 0ull) : 0;
    uint64_t head = panel ? heading_over(c, panel, ptr) : 0, world_head = panel && wtr ? heading_over(c, panel, wtr) : 0;
    uint64_t line = child_named(c, panel, "Bg_Line");
    if (!head || !world_head || head == world_head || !line) { rt_log("gameplay: the game settings panel is not as expected; no added rows"); return; }
    uint64_t heads[NROWS + 2] = {world_head, head}, pickers[NROWS + 2] = {wtr, ptr};
    for (int r = 0; r < NROWS; r++) {
        uint64_t copy = rt_call(c, FN(F_INSTANTIATE), 3, picker, panel, 0ull);
        uint64_t head2 = copy && !c->eh_unwinding ? rt_call(c, FN(F_INSTANTIATE), 3, head, panel, 0ull) : 0;
        if (!copy || !head2 || c->eh_unwinding) return;
        list_insert(c, buttons, at + 1 + r, copy);
        uint64_t label = (int)rt_call(c, FN(F_CHILD_COUNT), 2, head2, 0ull) > 0 ? rt_call(c, FN(F_GET_CHILD), 3, head2, 0ull, 0ull) : 0;
        uint64_t text = label ? rt_call(c, FN(F_GO_GET_COMPONENT_NAME), 3, rt_call(c, FN(F_GET_GAMEOBJECT), 2, label, 0ull), str8(c, "TextMeshProUGUI"), 0ull) : 0;
        keep(c, &g_head_h[r], text);
        set_heading(c, r);
        heads[2 + r] = head2;
        pickers[2 + r] = rt_call(c, FN(F_GET_TRANSFORM), 2, copy, 0ull);
    }
    float top[2] = {0, 0}, bottom[2] = {0, 0};
    get_floats(c, F_GET_ANCHORED_POS, world_head, top, 2);
    get_floats(c, F_GET_ANCHORED_POS, line, bottom, 2);
    const int g = NROWS + 2;
    float k = (top[1] - bottom[1] - LINE_TO_PICKER) / (g * HEAD_TO_PICKER + (g - 1) * PICKER_TO_HEAD);
    for (int i = 0; i < g; i++) {
        float y = top[1] - k * (HEAD_TO_PICKER + PICKER_TO_HEAD) * (float)i;
        set_y(c, heads[i], y);
        set_y(c, pickers[i], y - k * HEAD_TO_PICKER);
    }
    rt_log("gameplay: the game settings screen has Spin Dash and Ball Physics rows");
}

// setupChoicesItemList(...): returns the screen's List<UIChoicesItemData>. The game also calls it again for a screen
// that is already up (another list of worlds), so the views are only made when the screen has one per game row.
static int setup_list(Cpu *c, uint64_t fn, int view_off, int collision_off) {
    static __thread int inside;
    if (inside) return 0;
    load();
    uint64_t ctrl = c->x[0];
    inside = 1; c->pc = FN(fn); rt_dispatch(c); inside = 0;
    uint64_t list = c->x[0], pattern = ctrl ? LD64(ctrl + collision_off) : 0, view = ctrl ? LD64(ctrl + view_off) : 0;
    uint64_t buttons = view ? LD64(view + VIEW_BUTTONS) : 0;
    if (c->eh_unwinding || !list || !pattern || !buttons) return 1;
    int n = list_n(list), at = -1;
    for (int i = 0; i < n; i++)
        if (list_at(list, i) == pattern) at = i;
    if (at < 1 || list_n(buttons) < n) return 1;      // no Ball Collision row on this screen: left as it is
    rt_call(c, FN(F_GC_DISABLE), 0);      // the copies are only reachable from host locals until they are in the list
    if (list_n(buttons) == n) add_views(c, buttons, at);
    for (int r = 0; r < NROWS && list_n(buttons) >= n + NROWS && !c->eh_unwinding; r++) {
        uint64_t obj = rt_call(c, FN(F_OBJECT_NEW), 1, LD64(pattern));
        if (!obj || c->eh_unwinding) break;
        memcpy((void *)(uintptr_t)(obj + 0x10), (const void *)(uintptr_t)(pattern + 0x10), ITEM_SIZE - 0x10);
        int idx = 0;
        for (int i = 0; i < list_n(LD64(obj + ITEM_ELEMENTS)); i++)
            if ((element_id(obj, i) == COLLISION_ON) == (row_on(r) != 0)) idx = i;
        ST32(obj + ITEM_INDEX, idx); ST32(obj + ITEM_PREV_INDEX, idx);
        list_insert(c, list, at + 1 + r, obj);
        keep(c, &g_row_h[r], obj);
    }
    rt_call(c, FN(F_GC_ENABLE), 0);
    c->x[0] = list;
    return 1;
}
int rt_hook_464a040(Cpu *c) { return setup_list(c, F_SETUP_ITEM_LIST, 0x38, VIEW_ITEM_COLLISION); }      // online
int rt_hook_4645c70(Cpu *c) { return setup_list(c, 0x4645c70ull, 0x28, 0x48); }                           // split screen

// onInitSelectableButtonForBallCollision(item, view): a row is shown. The game writes the row's name and its choice
// ("Collision" / "No Collision"); the copies get their own.
int rt_hook_4649b10(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    uint64_t item = c->x[0], view = c->x[1];
    int r = -1;
    KEEP_ARGS(r = my_row(c, item));
    if (r < 0) return 0;
    inside = 1; c->pc = FN(F_ROW_INIT); rt_dispatch(c); inside = 0;
    if (c->eh_unwinding || !view) return 1;
    uint64_t s = rt_tr_str(c, ROW_TITLE[r]);
    if (!c->eh_unwinding) rt_call(c, FN(F_SET_TEXT), 3, view, s, 0ull);
    s = rt_tr_str(c, row_value(r));
    if (!c->eh_unwinding) rt_call(c, FN(F_SET_VALUE_TEXT), 3, view, s, 0ull);
    if (!c->eh_unwinding) set_heading(c, r);      // again: the copied heading's own text component may have set its text since
    return 1;
}

// onChangePickerValueForBallCollision(item, pickerView): the player changed a picker. For the game's row this sets
// ball collision; for a copy it sets that row's choice.
int rt_hook_4649c50(Cpu *c) {
    uint64_t item = c->x[0], view = c->x[1];
    int r = -1;
    KEEP_ARGS(r = my_row(c, item));
    if (r < 0) return 0;
    int idx = (int32_t)LD32(item + ITEM_INDEX);
    row_set(r, element_id(item, idx) == COLLISION_ON);
    uint64_t s = rt_tr_str(c, row_value(r));
    if (!c->eh_unwinding && view) rt_call(c, FN(F_SET_VALUE_TEXT), 3, view, s, 0ull);
    return 1;
}
