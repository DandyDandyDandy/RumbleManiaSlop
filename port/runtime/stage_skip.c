// Skip Stage: a row in the pause menu of Adventure that leaves the stage being played for the next one.
//
// Single player (UIStatePauseMenu): the row is the last one of the Help Menu tab, under the game's Mark as
// Cleared (the Game Menu tab is full: the menu shows five rows). After a Yes the stage list
// moves on one stage and the game changes scene the way the result screen's Next does (FlowMaingameResultBase.
// onDecideNext: StageList.IncIndex, setNextStageParam, UIStateArgTransitionToMainGameScene_NoParamNextStage).
// The stage left is not marked as cleared and nothing is recorded for it; the next stage becomes selectable in
// Select Stage, as it does after a clear. The game's own Help Menu > Mark as Cleared (costs points, only on a
// stage not cleared yet) is untouched. Not offered on the last stage of a world, in the tutorial, in a replay or
// in the challenge modes (the stage list there is a timed run).
//
// Split screen and online (UIStateInBattleMenu): the row stands above Quit; the menu's view has four buttons, so a
// fifth is made from the last one and the five are spread over the envelope. A stage of several players can only
// end through the game master every machine runs (BattleGameMaster.AdvGameMaster), and the next stage is started
// by the host from the scene that follows the result screen, so here the stage is ended the way the game's own
// Mark as Cleared ends one: every player still playing is flagged as having reached the goal (MgPlayer.isGoal,
// with the time played so far as the goal time), which PlayerStateMainGame.OnUpdate turns into the ordinary goal
// (NetworkEvent.Goal online). The result screen follows and Next Stage is chosen there as after any stage.
// Online only the host has the row; its choice goes to the guests as a message of the port's own (online.c hands
// it over before the game sees it) and each machine flags its own players.
//
// BR_SKIP_LOG=1 logs why the row is or is not offered.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_INIT_METADATA 0x4506d0ull         // il2cpp_codegen_initialize_runtime_metadata(uintptr_t *slot)
#define F_OBJECT_NEW 0x450aa0ull
#define F_GCHANDLE_NEW 0x469da0ull          // il2cpp_gchandle_new(obj, pinned)
#define F_GCHANDLE_TARGET 0x469df0ull
#define F_GCHANDLE_FREE 0x469e10ull
#define F_GC_DISABLE 0x469d10ull
#define F_GC_ENABLE 0x469d00ull
#define F_LIST_ADD_WITH_RESIZE 0x33bfab0ull // List<object>::AddWithResize(item, MethodInfo *)
#define F_SET_TEXT 0x45117c0ull             // UIPartViewSelectableButton.SetText(string)
#define F_YESNO_ARG_CTOR 0x4510cc0ull       // UIStateArgYesNoDialog..ctor(text, focus, onYes, onNo, system view, open SE, wait sec, no cancel)
#define F_STATE_PUSH_UP 0x45386a0ull        // UIStateBase.RequestStatePushUp(kind, arg) -> UIStateHandle
#define F_STATE_POP 0x4538850ull            // UIStateBase.RequestStatePop(result, bool)
#define F_SCENE_CHANGE 0x4538a00ull         // UIStateBase.RequestSceneChange(arg)
#define F_NEXT_STAGE_ARG_CTOR 0x454d330ull  // UIStateArgTransitionToMainGameScene_NoParamNextStage..ctor(scene, mode, bool, force change)
#define F_PAUSE_SET_ENABLED 0x4467c90ull    // PauseSequenceManager.SetEnabled(bool) (static)
#define F_PAUSE_IS_PAUSE 0x4467af0ull       // PauseSequenceManager.isPause (static)
#define F_GET_SELECTOR 0x43dbad0ull         // RuntimeParam.selector (static) -> SelectorParam
#define F_GET_MAIN_GAME 0x43db8d0ull        // RuntimeParam.mainGame (static) -> MainGameParam
#define F_GET_BATTLE 0x43dbb50ull           // RuntimeParam.battle (static) -> BattleParam
#define F_IS_BATTLE_MODE 0x43de0a0ull       // BattleParam.isBattleMode: a game master exists (split screen, online)
#define F_BATTLE_IS_STARTED 0x43de280ull    // BattleParam.isStarted
#define F_BATTLE_IS_FINISHED 0x43de370ull   // BattleParam.isFinished
#define F_REPLAY_IS_PLAYING 0x437a7c0ull    // ReplayManager.isPlaying (static)
#define F_PLAYER_LIST 0x42cf6c0ull          // MainGame.playerList (static) -> List<MgPlayer>; null outside a stage
#define F_MAIN_GAME_STAGE 0x42cf030ull      // MainGame.mainGameStage (static); null outside a stage
#define F_LIST_INC_INDEX 0x4357230ull       // StageList.IncIndex()
#define F_LIST_IS_LAST 0x4357410ull         // StageList.IsLastStage()
#define F_LIST_CURRENT_RECORD 0x4356370ull  // StageList.currentStageRecord -> Stage.Record
#define F_RECORD_SCENE 0x47b3b50ull         // Stage.Record.SceneID
#define F_USER_PARAM 0x4403f70ull           // SaveDataContainer.UserParam.entity (static) -> SaveUserParam
#define F_SET_STAGE_CONDITION 0x43f2430ull  // AdventureParam.SetConditionFromStageIndex(course, stage index, condition, bool)
#define F_INSTANTIATE 0x3f117f0ull          // UnityEngine.Object.Instantiate(Object original, Transform parent)
#define F_GET_TRANSFORM 0x3f07f60ull        // UnityEngine.Component.get_transform
#define F_GET_PARENT 0x3f1a0a0ull           // Transform.get_parent
#define F_GET_ANCHORED_POS 0x3f182c0ull     // RectTransform.get_anchoredPosition -> Vector2 in v0, v1
#define F_SET_ANCHORED_POS 0x3f18390ull     // RectTransform.set_anchoredPosition(Vector2)
#define M_CLASS_YESNO_ARG 0x61679d0ull      // metadata usage pointer slots
#define M_CLASS_NEXT_STAGE_ARG 0x616f770ull
#define STATE_YESNO_DIALOG 0x3b             // Def_UIState.eStateKind
#define HANDLE_STATUS 0x10                  // UIStateHandle.status: 3 = Finished
#define HANDLE_RESULT 0x14                  // UIStateHandle.result: 2 = Yes
#define SELECTOR_CATEGORY 0x10              // SelectorParam.m_MainGameCategoryID: 1 = stages picked one by one (the others are timed runs)
#define SELECTOR_COURSE 0x20
#define SELECTOR_STAGELIST 0x28
#define STAGELIST_INDEX 0x20
#define MAINGAME_STAGE_TO_STAGE 0x41        // MainGameParam.transitionStageToStage
#define MAINGAME_TUTORIAL 0x50              // MainGameParam.m_TutorialParam
#define TUTORIAL_IS_TUTORIAL 0x10
#define BATTLE_IS_ONLINE 0x10               // BattleParam.isOnlineMode
#define BATTLE_GAME_MASTER 0x20             // BattleParam.gameMaster
#define MASTER_ELAPSED_MS 0x18              // GameMasterBase: milliseconds played (BattleParam.elapsedTime reads it)
#define USER_ADVENTURE 0x38                 // SaveUserParam -> AdventureParam
#define CONDITION_OPEN 3                    // what the result screen's Next gives the stage it goes to
#define PLAYER_IS_GOAL 0x20                 // MgPlayer.isGoal
#define PLAYER_GOAL_TIME 0xc8               // MgPlayer.m_GoalTime (seconds)
#define PLAYER_IS_LOCAL 0x1c0               // MgPlayer.m_IsLocal
#define PAUSE_MAIN_LIST 0xa8                // UIStatePauseMenu.m_MainChoicesDataList (tab Game Menu)
#define PAUSE_SUPPORT_LIST 0xb0             // UIStatePauseMenu.m_SupportChoicesDataList (tab Help Menu)
#define STATE_REQUESTED 0x30                // UIStateBase: a push or pop is under way (no further request is taken)
#define ITEM_FIELDS 0x10                    // UIChoicesItemData: +0x10 isDisable, +0x18 text, +0x20 the menu's record
#define ITEM_FIELDS_SIZE 0x18
#define LIST_ITEMS 0x10
#define LIST_SIZE 0x18
#define ARR_DATA 0x20
#define KLASS_NAME 0x10
#define KLASS_RGCTX 0xc0                    // List<T> class: generic context data, +0x70 = AddWithResize

enum { KIND_SINGLE = 1, KIND_MULTI = 2 };
static const uint8_t k_magic[8] = {0xf5, 'B', 'R', 'S', 'K', 'I', 'P', 1};

static uint64_t g_pause_menu;               // the UIStatePauseMenu whose initChoicesModule is running
static uint32_t g_buttons_h;                // the multiplayer menu's button list that was given a fifth button,
static float g_button_y[4];                 // and where its four buttons stood
static uint32_t g_item_h;                   // GC handles: the Skip Stage row of the menu that is open,
static uint32_t g_state_h;                  // the menu that asked,
static uint32_t g_dialog_h;                 // the question's UIStateHandle
static int g_kind;                          // which menu asked
static int g_pending;                       // several players: flag the local players once the game runs again
static uint32_t g_close_h;                  // the multiplayer menu to close once it takes requests again
static volatile LONG g_net_skip;            // a guest: the host skipped stage index (value - 1)

uint64_t rt_tr_str(Cpu *c, const char *english);      // port_text.c
int online_role(void);                                // online.c: 0 not in a room, 1 host, 2 guest
int online_send_port(const uint8_t *data, uint32_t len);

static int logging(void) {
    static int on = -1;
    if (on < 0) on = getenv("BR_SKIP_LOG") != NULL;
    return on;
}
static int list_n(uint64_t list) { return list ? (int32_t)LD32(list + LIST_SIZE) : 0; }
static uint64_t list_at(uint64_t list, int i) { return LD64(LD64(list + LIST_ITEMS) + ARR_DATA + 8 * (uint64_t)i); }
static const char *class_name(uint64_t obj) { return obj ? (const char *)(uintptr_t)LD64(LD64(obj) + KLASS_NAME) : ""; }
static uint64_t class_of_slot(Cpu *c, uint64_t slot_ptr) {
    uint64_t p = LD64(FN(slot_ptr));
    if (LD64(p) & 1) rt_call(c, FN(F_INIT_METADATA), 1, p);
    return LD64(p);
}
static uint64_t target(Cpu *c, uint32_t h) { return h ? rt_call(c, FN(F_GCHANDLE_TARGET), 1, (uint64_t)h) : 0; }
static void keep(Cpu *c, uint32_t *h, uint64_t obj) {
    if (*h) rt_call(c, FN(F_GCHANDLE_FREE), 1, (uint64_t)*h);
    *h = obj ? (uint32_t)rt_call(c, FN(F_GCHANDLE_NEW), 2, obj, 0ull) : 0;
}
static uint64_t stage_list(Cpu *c) {
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull);
    return sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
}
// The Adventure game master of a stage of several players that is being played, or 0.
static uint64_t adv_master(Cpu *c, int *online) {
    uint64_t battle = rt_call(c, FN(F_GET_BATTLE), 1, 0ull);
    if (!battle || !(rt_call(c, FN(F_IS_BATTLE_MODE), 2, battle, 0ull) & 1)) return 0;
    uint64_t master = LD64(battle + BATTLE_GAME_MASTER);
    if (strcmp(class_name(master), "AdvGameMaster")) return 0;
    if (!(rt_call(c, FN(F_BATTLE_IS_STARTED), 2, battle, 0ull) & 1) || (rt_call(c, FN(F_BATTLE_IS_FINISHED), 2, battle, 0ull) & 1)) return 0;
    if (online) *online = LD8(battle + BATTLE_IS_ONLINE) != 0;
    return master;
}

// Whether the menu being built gets the row.
static int offered(Cpu *c, int kind) {
    const char *why = NULL;
    if (!rt_call(c, FN(F_MAIN_GAME_STAGE), 1, 0ull)) why = "not in a stage";
    else if (rt_call(c, FN(F_REPLAY_IS_PLAYING), 1, 0ull) & 1) why = "a replay";
    else if (kind == KIND_SINGLE) {
        uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), mg = rt_call(c, FN(F_GET_MAIN_GAME), 1, 0ull);
        uint64_t tut = mg ? LD64(mg + MAINGAME_TUTORIAL) : 0, list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
        uint64_t battle = rt_call(c, FN(F_GET_BATTLE), 1, 0ull);
        if (!sel || !list) why = "no stage list";
        else if (tut && LD8(tut + TUTORIAL_IS_TUTORIAL)) why = "the tutorial";
        else if (battle && (rt_call(c, FN(F_IS_BATTLE_MODE), 2, battle, 0ull) & 1)) why = "a game of several players";
        else if (LD32(sel + SELECTOR_CATEGORY) != 1) why = "a challenge mode";
        else if (rt_call(c, FN(F_LIST_IS_LAST), 2, list, 0ull) & 1) why = "the last stage of the world";
    } else {
        int online = 0;
        if (!adv_master(c, &online)) why = "not an Adventure stage being played";
        else if (online && online_role() != 1) why = "a guest of the room";
    }
    if (logging()) rt_log("stage skip: %s menu: %s%s", kind == KIND_SINGLE ? "pause" : "multiplayer", why ? "no row: " : "row added", why ? why : "");
    return !why;
}

static float get_y(Cpu *c, uint64_t tr) {
    float y;
    c->x[0] = tr; c->x[1] = 0;
    rt_call_regs(c, FN(F_GET_ANCHORED_POS));
    uint32_t u = (uint32_t)c->v[1];
    memcpy(&y, &u, 4);
    return y;
}
static void set_y(Cpu *c, uint64_t tr, float y) {
    c->x[0] = tr; c->x[1] = 0;
    rt_call_regs(c, FN(F_GET_ANCHORED_POS));
    uint32_t u;
    memcpy(&u, &y, 4);
    c->v[1] = u;                             // x stays in v0
    c->x[0] = tr; c->x[1] = 0;
    rt_call_regs(c, FN(F_SET_ANCHORED_POS));
}
// The multiplayer menu's view (kept and used again by the game) has one button per row of the game: four. With
// the row a fifth button is made from the last one, and the five stand around the middle of the four, a little
// closer together (the envelope has room for four and a half rows); without the row the four stand where the
// game put them (the module hides a spare button).
static void fit_buttons(Cpu *c, uint64_t buttons, int with_row) {
    if (!buttons || list_n(buttons) < 4) return;
    uint64_t tr[5] = {0};
    if (target(c, g_buttons_h) != buttons) {
        if (list_n(buttons) != 4 || !with_row) return;
        for (int i = 0; i < 4; i++) g_button_y[i] = get_y(c, rt_call(c, FN(F_GET_TRANSFORM), 2, list_at(buttons, i), 0ull));
        uint64_t last = list_at(buttons, 3), ltr = rt_call(c, FN(F_GET_TRANSFORM), 2, last, 0ull);
        uint64_t copy = rt_call(c, FN(F_INSTANTIATE), 3, last, rt_call(c, FN(F_GET_PARENT), 2, ltr, 0ull), 0ull);
        if (!copy || c->eh_unwinding) return;
        rt_call(c, FN(F_LIST_ADD_WITH_RESIZE), 3, buttons, copy, LD64(LD64(LD64(buttons) + KLASS_RGCTX) + 0x70));
        if (c->eh_unwinding || list_n(buttons) != 5) return;
        keep(c, &g_buttons_h, buttons);
    }
    for (int i = 0; i < 5; i++) tr[i] = rt_call(c, FN(F_GET_TRANSFORM), 2, list_at(buttons, i), 0ull);
    float step = g_button_y[3] - g_button_y[2], mid = 0.5f * (g_button_y[0] + g_button_y[3]);
    for (int i = 0; i < 5; i++) set_y(c, tr[i], with_row ? mid + 0.92f * step * (float)(i - 2) : i < 4 ? g_button_y[i] : g_button_y[3] + step);
}

// UIStatePauseMenu.initChoicesModule(): fills the row lists of both tabs, then makes the row module (below).
int rt_hook_4626eb0(Cpu *c) {
    g_pause_menu = c->x[0];
    return 0;
}

// UIChoicesGroupModule_Vertical..ctor(List<UIChoicesItemData> items, ...): both menus hand their finished row list
// to this (the pause menu its Game Menu rows; its Help Menu rows are complete by then too). The new row is a copy
// of the list's first row (same class, same record, so whatever reads a row finds what it expects), told apart by
// its address. Pause menu: last row of the Help Menu; multiplayer menu: above the last row (Quit).
int rt_hook_4581900(Cpu *c) {
    uint64_t list = c->x[1];
    int n = list_n(list);
    if (n < 2 || n > 8) return 0;
    uint64_t first = list_at(list, 0);
    const char *cn = class_name(first);
    int kind = !strcmp(cn, "UIChoicesPauseMenuItemData") ? KIND_SINGLE : !strcmp(cn, "UIChoicesInBattleMenuItemData") ? KIND_MULTI : 0;
    if (!kind) return 0;
    if (kind == KIND_SINGLE) {
        uint64_t menu = g_pause_menu;
        g_pause_menu = 0;
        if (!menu || LD64(menu + PAUSE_MAIN_LIST) != list || !(list = LD64(menu + PAUSE_SUPPORT_LIST))) return 0;
        n = list_n(list);
    }
    uint64_t sx[19], lr = c->x[30];
    memcpy(sx, c->x, sizeof sx);
    int with_row = offered(c, kind);
    if (kind == KIND_MULTI) fit_buttons(c, sx[3], with_row);      // x3: the view's List<UIPartViewSelectableButton>
    if (with_row) {
        rt_call(c, FN(F_GC_DISABLE), 0);      // the copy is only reachable from host locals until it is in the list
        uint64_t obj = rt_call(c, FN(F_OBJECT_NEW), 1, LD64(first));
        if (obj && !c->eh_unwinding) {
            memcpy((void *)(uintptr_t)(obj + ITEM_FIELDS), (const void *)(uintptr_t)(first + ITEM_FIELDS), ITEM_FIELDS_SIZE);
            ST8(obj + ITEM_FIELDS, 0);
            rt_call(c, FN(F_LIST_ADD_WITH_RESIZE), 3, list, obj, LD64(LD64(LD64(list) + KLASS_RGCTX) + 0x70));
            if (!c->eh_unwinding && list_n(list) == n + 1) {
                uint64_t items = LD64(list + LIST_ITEMS) + ARR_DATA;
                if (kind == KIND_MULTI) {
                    ST64(items + 8ull * n, LD64(items + 8ull * (n - 1)));
                    ST64(items + 8ull * (n - 1), obj);
                }
                keep(c, &g_item_h, obj);
            }
        }
        rt_call(c, FN(F_GC_ENABLE), 0);
    } else keep(c, &g_item_h, 0);
    memcpy(c->x, sx, sizeof sx);
    c->x[30] = lr;
    return 0;
}

// onInitSelectableButton(int index, UIChoicesItemData item, UIPartViewSelectableButton view) of both menus: the
// row's text.
static int init_button(Cpu *c) {
    uint64_t item = c->x[2], view = c->x[3], lr = c->x[30];
    if (!g_item_h || !item || !view) return 0;
    uint64_t sx[4];
    memcpy(sx, c->x, sizeof sx);
    int mine = target(c, g_item_h) == item;
    if (mine) rt_call(c, FN(F_SET_TEXT), 3, view, rt_tr_str(c, "Skip Stage"), 0ull);
    memcpy(c->x, sx, sizeof sx);
    c->x[30] = lr;
    return mine;
}
int rt_hook_46287d0(Cpu *c) { return init_button(c); }      // UIStatePauseMenu
int rt_hook_45b0d40(Cpu *c) { return init_button(c); }      // UIStateInBattleMenu

// onDecide(int index, UIChoicesItemData item, UIPartViewSelectableButton view) of both menus: the row asks first,
// in the game's Yes/No dialog (focus on No, like the game's own questions in these menus).
static int decide(Cpu *c, int kind) {
    uint64_t state = c->x[0], item = c->x[2], lr = c->x[30];
    if (!g_item_h || !item || !state) return 0;
    uint64_t sx[4];
    memcpy(sx, c->x, sizeof sx);
    int mine = target(c, g_item_h) == item;
    if (mine && !target(c, g_dialog_h)) {
        uint64_t arg = rt_call(c, FN(F_OBJECT_NEW), 1, class_of_slot(c, M_CLASS_YESNO_ARG));
        uint64_t text = rt_tr_str(c, "Skip this stage?");
        c->x[0] = arg; c->x[1] = text; c->x[2] = 1;
        c->x[3] = 0; c->x[4] = 0;                                           // no callbacks: the handle carries the answer
        c->x[5] = 1; c->x[6] = 0; c->x[7] = 0;
        rt_setf(c, 0, 0.0f);
        rt_call_regs(c, FN(F_YESNO_ARG_CTOR));
        uint64_t handle = rt_call(c, FN(F_STATE_PUSH_UP), 4, state, (uint64_t)STATE_YESNO_DIALOG, arg, 0ull);
        if (handle && !c->eh_unwinding) {
            keep(c, &g_dialog_h, handle);
            keep(c, &g_state_h, state);
            g_kind = kind;
        }
    }
    memcpy(c->x, sx, sizeof sx);
    c->x[30] = lr;
    return mine;
}
int rt_hook_4628a70(Cpu *c) { return decide(c, KIND_SINGLE); }
int rt_hook_45b0df0(Cpu *c) { return decide(c, KIND_MULTI); }

// Single player: on to the next stage of the list, as the result screen's Next goes.
static void skip_single(Cpu *c, uint64_t state) {
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
    if (!list || (rt_call(c, FN(F_LIST_IS_LAST), 2, list, 0ull) & 1)) return;
    int from = (int32_t)LD32(list + STAGELIST_INDEX);
    rt_call(c, FN(F_PAUSE_SET_ENABLED), 2, 0ull, 0ull);
    rt_call(c, FN(F_LIST_INC_INDEX), 2, list, 0ull);
    uint64_t mg = rt_call(c, FN(F_GET_MAIN_GAME), 1, 0ull), user = rt_call(c, FN(F_USER_PARAM), 1, 0ull);
    uint64_t adv = user ? LD64(user + USER_ADVENTURE) : 0;
    if (mg) ST8(mg + MAINGAME_STAGE_TO_STAGE, 1);
    if (adv) rt_call(c, FN(F_SET_STAGE_CONDITION), 6, adv, (uint64_t)LD32(sel + SELECTOR_COURSE), (uint64_t)LD32(list + STAGELIST_INDEX),
                     (uint64_t)CONDITION_OPEN, 0ull, 0ull);
    uint64_t rec = rt_call(c, FN(F_LIST_CURRENT_RECORD), 2, list, 0ull);
    uint32_t scene = rec ? (uint32_t)rt_call(c, FN(F_RECORD_SCENE), 2, rec, 0ull) : 0;
    if (!scene || c->eh_unwinding) return;
    uint64_t arg = rt_call(c, FN(F_OBJECT_NEW), 1, class_of_slot(c, M_CLASS_NEXT_STAGE_ARG));
    rt_call(c, FN(F_NEXT_STAGE_ARG_CTOR), 6, arg, (uint64_t)scene, 0ull, 1ull, 0ull, 0ull);
    rt_call(c, FN(F_SCENE_CHANGE), 3, state, arg, 0ull);
    rt_log("stage skip: stage %d of course %u left for stage %d (scene %u)", from, LD32(sel + SELECTOR_COURSE), from + 1, scene);
}

// Several players: every local player still playing has reached the goal now.
static void goal_local_players(Cpu *c) {
    uint64_t master = adv_master(c, NULL), players = rt_call(c, FN(F_PLAYER_LIST), 1, 0ull);
    if (!master || !players) return;
    float sec = (float)(int32_t)LD32(master + MASTER_ELAPSED_MS) / 1000.0f;
    int n = list_n(players), done = 0;
    for (int i = 0; i < n; i++) {
        uint64_t p = list_at(players, i);
        if (!p || !LD8(p + PLAYER_IS_LOCAL) || LD8(p + PLAYER_IS_GOAL)) continue;
        memcpy((void *)(uintptr_t)(p + PLAYER_GOAL_TIME), &sec, 4);
        ST8(p + PLAYER_IS_GOAL, 1);
        done++;
    }
    rt_log("stage skip: %d local player%s sent to the goal at %.2f s", done, done == 1 ? "" : "s", sec);
}

// online.c: a message of the port's own came in. 1 when it was this one.
int stage_skip_message(const uint8_t *data, uint32_t len, int from_host) {
    if (len != sizeof k_magic + 4 || memcmp(data, k_magic, sizeof k_magic)) return 0;
    uint32_t index;
    memcpy(&index, data + sizeof k_magic, 4);
    if (from_host) InterlockedExchange(&g_net_skip, (LONG)index + 1);
    return 1;
}

void stage_skip_tick(Cpu *c) {      // once per frame; the caller preserves the registers
    LONG net = InterlockedExchange(&g_net_skip, 0);
    if (net) {
        uint64_t list = stage_list(c);
        int here = list ? (int32_t)LD32(list + STAGELIST_INDEX) : -1;
        if (adv_master(c, NULL) && here == net - 1) g_pending = 1;
        rt_log("stage skip: the host skips stage %d (%s)", (int)net - 1, g_pending ? "followed" : "not the stage being played here");
    }
    uint64_t handle = target(c, g_dialog_h);
    if (handle && LD32(handle + HANDLE_STATUS) == 3) {
        int yes = LD32(handle + HANDLE_RESULT) == 2;
        uint64_t state = target(c, g_state_h);
        keep(c, &g_dialog_h, 0);
        keep(c, &g_state_h, 0);
        if (yes && state && rt_call(c, FN(F_MAIN_GAME_STAGE), 1, 0ull)) {
            if (g_kind == KIND_SINGLE) skip_single(c, state);
            else if (adv_master(c, NULL)) {
                uint64_t list = stage_list(c);
                uint8_t msg[sizeof k_magic + 4];
                uint32_t index = list ? LD32(list + STAGELIST_INDEX) : 0;
                memcpy(msg, k_magic, sizeof k_magic);
                memcpy(msg + sizeof k_magic, &index, 4);
                if (online_role() == 1) online_send_port(msg, sizeof msg);
                keep(c, &g_close_h, state);
                g_pending = 1;
            }
        }
    }
    // The menu closes (it refuses the request while the question is still going away). Split screen stands still
    // while the menu is open, so the players are flagged when the game runs again; an online stage never stops.
    uint64_t menu = target(c, g_close_h);
    if (menu && !LD8(menu + STATE_REQUESTED)) {
        rt_call(c, FN(F_STATE_POP), 4, menu, 0ull, 0ull, 0ull);
        keep(c, &g_close_h, 0);
    }
    if (g_pending && (online_role() || !(rt_call(c, FN(F_PAUSE_IS_PAUSE), 1, 0ull) & 1))) {
        g_pending = 0;
        goal_local_players(c);
    }
}
