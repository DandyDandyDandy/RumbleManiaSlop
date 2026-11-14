// Banana Mania stages as extra Adventure courses (the data is made by mania\build.py and lives in <exe dir>mania\).
//
// The game's tables are open-ended in most places (course ids, stage ids, save entries), and closed in two:
//
//  1. Scene ids. A stage row names its scene (Stage.SceneID), and the name is turned into a value of the compiled
//     enum AppScene.eID through a name dictionary; the value's name is then the Addressables key and the scene's
//     name. An unknown name becomes Invalid. The imported stages use numbers as names ("100123"): the hook on
//     Framework.EnumRuntimeHelper<T>.GetValue(string, default) answers a name of six to nine digits with that
//     number, and Enum.ToString of a value without a name gives the digits back, so key and scene name are "100123".
//
//  2. Stage lists. A course names a stage list (Course.StageListID), and the list's rows are a table of their own
//     (Stage_List_Group_<name>), held in an array with one slot per compiled Stage.List.eID value (40). Ids past it
//     have no table. All imported courses therefore share one real list, the unused test list 12, whose rows are
//     the stages of every imported course one after the other, and each course has a virtual list id (1000 + n).
//     The hook on StageList.Setup builds the real list and keeps the course's own range of it.
//     <exe dir>mania\mania_courses.txt has one line per virtual list: "<list id> <first row> <rows>".
//
//  3. Music. A stage's BGM is the cue the game's background table (MgBgData) names for the stage's scenery, by
//     compiled cue name, so data alone cannot give a stage a new cue. The hook on MainGameBg.calcBgCue answers
//     with the cue of <exe dir>mania\mania_music.txt ("<Stage row id> <Sound_Cue row id>" per line) when the stage
//     being played is listed there.
//
//  4. The co-op world list. Local and online co-op offer the courses from the first one along the NextCourseID
//     chain up to the "highest unlocked" course, which is the last course in display order whose previous course
//     is cleared. The imported courses are always open and come last, so every course before them would be
//     offered, also worlds the player has not reached. The hook on getUnlockedCourseList takes those out again.
//
//  5. The "Mania" tab of Select World. The import adds a third tab next to Story and Special; the hooks on the
//     course picker's set-up fill it with the imported courses (taken out of the Story tab) and add its button.
//
// Without the mania folder none of this changes anything: no stage row has a numeric scene name, no course has
// a virtual list and there is no third tab.
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rt.h"

#define FN(off) (GUEST_BASE + (off))
#define F_STAGELIST_SETUP 0x43287d0ull      // Wonder.StageList.Setup(Stage.List.eID, Course.eID, bool isForce)
#define F_STAGELIST_SET_INDEX 0x4328c90ull  // Wonder.StageList.SetIndex(int)
#define STAGELIST_ID 0x10                   // StageList.m_StageListID
#define STAGELIST_ITEMS 0x18                // StageList.m_StageList: List<StageListItem>
#define STAGELIST_INDEX 0x20
#define ITEM_STAGE_INDEX 0x18               // StageListItem.m_StageIndex, m_StageIndexInList
#define ITEM_INDEX_IN_LIST 0x1c
#define LIST_ITEMS 0x10
#define LIST_SIZE 0x18
#define LIST_VERSION 0x1c
#define ARR_DATA 0x20
#define REAL_LIST 12                        // Stage.List.eID wld97_wldtst: the list that holds every imported row
#define MAX_COURSES 128

static struct { uint32_t list; int first, count; } g_courses[MAX_COURSES];
static int g_ncourses = -1;

#define F_GET_SELECTOR 0x43ad880ull         // Wonder.RuntimeParam.get_selector (static) -> SelectorParam
#define F_CURRENT_STAGE 0x4329320ull        // Wonder.StageList.GetCurrentStage() -> Stage.eID
#define SELECTOR_STAGELIST 0x28             // SelectorParam.m_StageList
#define MAX_MUSIC 1024
static struct { uint32_t stage, cue, classic; } g_music[MAX_MUSIC];   // classic: the Classic Soundtrack's cue row, 0 = none
static int g_nmusic = -1, g_have_classic;

// Which music the imported stages play when the import has both: Banana Mania's own (the default) or the original
// games' (its Classic Soundtrack add-on). The choice is kept in <exe dir>\port_mania.txt as "music=remake" or
// "music=classic"; mania_set_classic_music is for an option row.
static int g_classic = -1;
static void settings_path(char *path, size_t cap) { snprintf(path, cap, "%sport_mania.txt", rt_exe_dir()); }
int mania_classic_music(void) {
    if (g_classic < 0) {
        char path[700], line[64];
        g_classic = 0;
        settings_path(path, sizeof path);
        FILE *f = fopen(path, "r");
        while (f && fgets(line, sizeof line, f))
            if (!strncmp(line, "music=", 6)) g_classic = !strncmp(line + 6, "classic", 7);
        if (f) fclose(f);
    }
    return g_classic;
}
void mania_set_classic_music(int on) {
    char path[700];
    g_classic = on != 0;
    settings_path(path, sizeof path);
    FILE *f = fopen(path, "w");
    if (f) { fprintf(f, "music=%s\n", g_classic ? "classic" : "remake"); fclose(f); }
}
int mania_has_classic_music(void);

static void load_music(void) {
    char path[700], line[128];
    g_nmusic = 0;
    snprintf(path, sizeof path, "%smania\\mania_music.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && g_nmusic < MAX_MUSIC) {
        unsigned stage, cue;
        unsigned classic = 0;
        if (sscanf(line, "%u %u %u", &stage, &cue, &classic) >= 2) {
            g_music[g_nmusic].stage = stage; g_music[g_nmusic].cue = cue; g_music[g_nmusic].classic = classic; g_nmusic++;
            if (classic) g_have_classic = 1;
        }
    }
    fclose(f);
    rt_log("mania: imported music for %d stages", g_nmusic);
}

// Wonder.MainGameBg.calcBgCue() -> ValueTuple<Sound.Cue.eID, Sound.Cue.eID> (the BGM cue and its overlay cue, in x0)
int mania_has_classic_music(void) {
    if (g_nmusic < 0) load_music();
    return g_have_classic;
}

int rt_hook_426a180(Cpu *c) {
    if (g_nmusic < 0) load_music();
    if (!g_nmusic) return 0;
    uint64_t self = c->x[0], lr = c->x[30];
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
    uint32_t stage = list ? (uint32_t)rt_call(c, FN(F_CURRENT_STAGE), 2, list, 0ull) : 0;
    c->x[30] = lr;
    for (int i = 0; i < g_nmusic; i++)
        if (g_music[i].stage == stage) {
            static uint32_t said;
            if (said != stage && getenv("BR_MANIA_LOG"))
                rt_log("mania: stage row %u gets BGM cue row %u%s", stage, mania_classic_music() && g_music[i].classic ? g_music[i].classic : g_music[i].cue,
                       mania_classic_music() && g_music[i].classic ? " (Classic Soundtrack)" : "");
            said = stage;
            c->x[0] = mania_classic_music() && g_music[i].classic ? g_music[i].classic : g_music[i].cue;           // no overlay cue
            return 1;
        }
    c->x[0] = self;
    return 0;
}

// Stages that put their background somewhere else than the origin (Mania's BgRoot prefab): position, rotation
// (quaternion) and scale of the far scenery's root for that stage row
#define MAX_BGROOT 64
static struct { uint32_t stage; float v[10]; } g_bgroot[MAX_BGROOT];
static int g_nbgroot;

// Wonder.MainGameBg.Awake(): the root object of a far scenery scene comes to life. For an imported stage whose
// Mania original moves, turns or scales its background (29 stages; "bgroot" lines of mania_courses.txt), the root
// is placed accordingly: the converted scenery scene is one per background, made at the origin.
#define F_GET_TRANSFORM 0x3edc570ull        // UnityEngine.Component.get_transform
#define F_SET_LOCAL_POSITION 0x3eecf80ull   // UnityEngine.Transform.set_localPosition(Vector3): floats in v0..v2
#define F_SET_LOCAL_ROTATION 0x3eef030ull   // UnityEngine.Transform.set_localRotation(Quaternion): floats in v0..v3
#define F_SET_LOCAL_SCALE 0x3eef8c0ull      // UnityEngine.Transform.set_localScale(Vector3)
static void set_floats(Cpu *c, uint64_t fn, uint64_t tr, const float *f, int n) {
    c->x[0] = tr; c->x[1] = 0;
    for (int i = 0; i < n; i++) { uint32_t u; memcpy(&u, &f[i], 4); c->v[i] = u; }
    rt_call_regs(c, FN(fn));
}
static void load_courses(void);
int rt_hook_426a5b0(Cpu *c) {
    if (g_ncourses < 0) load_courses();
    if (!g_nbgroot) return 0;
    uint64_t self = c->x[0], method = c->x[1], lr = c->x[30];
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
    uint32_t stage = list ? (uint32_t)rt_call(c, FN(F_CURRENT_STAGE), 2, list, 0ull) : 0;
    for (int i = 0; i < g_nbgroot; i++)
        if (g_bgroot[i].stage == stage) {
            const float *v = g_bgroot[i].v;
            uint64_t tr = rt_call(c, FN(F_GET_TRANSFORM), 2, self, 0ull);
            if (!tr) break;
            set_floats(c, F_SET_LOCAL_POSITION, tr, v, 3);
            set_floats(c, F_SET_LOCAL_ROTATION, tr, v + 3, 4);
            set_floats(c, F_SET_LOCAL_SCALE, tr, v + 7, 3);
            if (getenv("BR_MANIA_LOG"))
                rt_log("mania: stage row %u: background at (%g, %g, %g), scale %g", stage, v[0], v[1], v[2], v[7]);
            break;
        }
    c->x[0] = self; c->x[1] = method; c->x[30] = lr;
    return 0;
}

// Areas of a stage (Mania's MainGameStageArea; "area <stage row> <kind> x y z radius" lines of mania_courses.txt):
// a goal inside a "goal" area does not count, a ball inside a "wormhole" area is not taken by a wormhole
#define MAX_AREAS 32
#define AREA_GOAL 1
#define AREA_WORMHOLE 2
static struct { uint32_t stage; int kind; float c[3], r; } g_areas[MAX_AREAS];
static int g_nareas;

#define MAX_OWN 64
static struct { uint32_t id, prev; } g_own[MAX_OWN];      // the game's Adventure worlds in display order
static int g_nown;
static uint32_t g_first_id;                               // the lowest course id of the import
static uint32_t g_tab;                                    // MainGame.Adventure.Type row of the "Mania" tab, 0 = none

static void load_courses(void) {
    char path[700], line[256];
    g_ncourses = 0;
    snprintf(path, sizeof path, "%smania\\mania_courses.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f)) {
        unsigned list, id = 0, prev = 0;
        int first, count;
        float v[10];
        char kind[16];
        if (sscanf(line, "bgroot %u %f %f %f %f %f %f %f %f %f %f", &id, v, v + 1, v + 2, v + 3, v + 4, v + 5, v + 6, v + 7, v + 8, v + 9) == 11) {
            if (g_nbgroot < MAX_BGROOT) { g_bgroot[g_nbgroot].stage = id; memcpy(g_bgroot[g_nbgroot].v, v, sizeof v); g_nbgroot++; }
        } else if (sscanf(line, "area %u %15s %f %f %f %f", &id, kind, v, v + 1, v + 2, v + 3) == 6) {
            int k = !strcmp(kind, "goal") ? AREA_GOAL : !strcmp(kind, "wormhole") ? AREA_WORMHOLE : 0;
            if (k && g_nareas < MAX_AREAS) {
                g_areas[g_nareas].stage = id; g_areas[g_nareas].kind = k;
                memcpy(g_areas[g_nareas].c, v, sizeof g_areas[0].c); g_areas[g_nareas].r = v[3];
                g_nareas++;
            }
        } else if (sscanf(line, "own %u %u", &id, &prev) == 2) {
            if (g_nown < MAX_OWN) { g_own[g_nown].id = id; g_own[g_nown].prev = prev; g_nown++; }
        } else if (sscanf(line, "tab %u", &id) == 1) {
            g_tab = id;
        } else if (g_ncourses < MAX_COURSES && sscanf(line, "%u %d %d %u", &list, &first, &count, &id) >= 3 && count > 0 && first >= 0) {
            g_courses[g_ncourses].list = list;
            g_courses[g_ncourses].first = first;
            g_courses[g_ncourses].count = count;
            if (id && (!g_first_id || id < g_first_id)) g_first_id = id;
            g_ncourses++;
        }
    }
    fclose(f);
    // online rooms: only players with the same imported courses meet (see np_set_content_tag)
    uint32_t tag = 2166136261u;
    for (int i = 0; i < g_ncourses; i++) {
        uint32_t v[3] = {g_courses[i].list, (uint32_t)g_courses[i].first, (uint32_t)g_courses[i].count};
        for (int k = 0; k < 12; k++) tag = (tag ^ ((const uint8_t *)v)[k]) * 16777619u;
    }
    extern void np_set_content_tag(uint32_t tag);
    np_set_content_tag(g_ncourses ? (tag | 1) : 0);
    rt_log("mania: %d imported courses", g_ncourses);
}

// called once per frame (display_opt.c): the course list is read at the start, before a room can be opened,
// because it sets the content tag of online play
void mania_tick(void) {
    if (g_ncourses < 0) load_courses();
}

// Wonder.SaveUserParam.AdventureParam.GetAdvModeHighestUnlockID(): the last world, in display order, whose previous
// world is cleared. An imported course has no previous world, which counts as cleared, so with an import the answer
// was always the last imported course; the world pickers and the value sent to other players in a room then
// treated every one of the game's worlds as open. The answer is worked out over the game's own worlds instead.
#define F_IS_COURSE_CLEARED 0x43c3530ull    // AdventureParam.IsCourseCleared(Course.eID)
int rt_hook_43c37d0(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    if (g_ncourses < 0) load_courses();
    if (!g_ncourses || !g_first_id || !g_nown) return 0;
    uint64_t lr = c->x[30], self = c->x[0], x1 = c->x[1];
    inside = 1;
    uint32_t best = (uint32_t)rt_call(c, FN(0x43c37d0ull), 2, self, x1);
    inside = 0;
    if (best >= g_first_id) {
        best = g_own[0].id;
        for (int i = 0; i < g_nown; i++)
            if (!g_own[i].prev || (rt_call(c, FN(F_IS_COURSE_CLEARED), 3, self, (uint64_t)g_own[i].prev, 0ull) & 1)) best = g_own[i].id;
    }
    c->x[0] = best;
    c->x[30] = lr;
    return 1;
}

// Play statistics (Wonder.CRM: what the Switch game uploads to the publisher). AdventureSaveData keeps one flag
// per stage in bool[Course.eID count * 10] arrays and one counter object per course in arrays of that count, and
// the four AdventureUtil functions below index them with course * 10 + stage (or the course) without a check:
// the game is built without array bounds checks. An imported course has an id past the enum, so finishing an
// imported stage wrote a byte into whatever followed the array in the heap - usually the next array's class
// pointer, which the engine's next unused-asset sweep (il2cpp's liveness walk between scenes) then followed
// into unmapped memory. It only happened with a new best time (UpdateBestTimeStatus), hence "now and then".
// The statistics are not sent anywhere on PC; for an imported course the call is dropped (BR_MANIA_LOG logs it).
//   UpdateMissionStatus(course, stage, save), UpdateBestTimeStatus(course, stage, kind, save),
//   StartTimeAttack(course, kind), FinishTimeAttack(course, kind)   (all static; x0 = course)
static int crm_imported(Cpu *c, const char *what) {
    static int on = -1;
    if (g_ncourses < 0) load_courses();
    if (!g_first_id || (uint32_t)c->x[0] < g_first_id) return 0;
    if (on < 0) on = getenv("BR_MANIA_LOG") != NULL;
    if (on) rt_log("mania: play statistics: %s dropped for imported course %u (second argument %d)", what, (unsigned)c->x[0], (int)c->x[1]);
    return 1;
}
int rt_hook_446c3f0(Cpu *c) { return crm_imported(c, "UpdateMissionStatus"); }
int rt_hook_446c4d0(Cpu *c) { return crm_imported(c, "UpdateBestTimeStatus"); }
int rt_hook_446c610(Cpu *c) { return crm_imported(c, "StartTimeAttack"); }
int rt_hook_446c730(Cpu *c) { return crm_imported(c, "FinishTimeAttack"); }

// The world picker of local co-op and of online rooms lists the chain of worlds (Course.NextCourseID) from the
// first one up to the "highest unlocked" one: UIChoicesItemData_Factory.getUnlockedCourseList(this, highest).
// Online, `highest` is the lowest of the players' own values. Imported courses hang at the end of the chain and are
// never anyone's highest (GetAdvModeHighestUnlockID wants the course before it cleared, and they have none), so
// the picker never reached them. The hook lets the game answer as before and adds the imported courses.
#define F_UNLOCKED_COURSES 0x45605b0ull     // UIChoicesItemData_Factory.getUnlockedCourseList(this, Course.eID highest) -> List<Course.Record>
#define F_COURSE_STAGELIST 0x4797890ull     // Course.Record.StageListID()
#define LIST_BASE 1000                      // virtual stage list ids start here (mania\build.py)

int rt_hook_45605b0(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    if (g_ncourses < 0) load_courses();
    if (!g_ncourses) return 0;
    uint64_t lr = c->x[30], self = c->x[0], highest = c->x[1], x2 = c->x[2], x3 = c->x[3];
    inside = 1;
    // the game's answer (the chain of worlds from the first one to `highest`), and the whole chain: an id that is
    // never met makes the walk run to the end, where the imported courses hang
    uint64_t own = rt_call(c, FN(F_UNLOCKED_COURSES), 4, self, highest, x2, x3);
    uint64_t all = rt_call(c, FN(F_UNLOCKED_COURSES), 4, self, 0x7fffffffull, x2, x3);
    inside = 0;
    uint64_t own_items = own ? LD64(own + LIST_ITEMS) : 0, items = all ? LD64(all + LIST_ITEMS) : 0;
    int own_n = own ? (int)LD32(own + LIST_SIZE) : 0, n = all ? (int)LD32(all + LIST_SIZE) : 0, kept = 0;
    if (!items) {
        c->x[0] = own;
        c->x[30] = lr;
        return 1;
    }
    for (int i = 0; i < n; i++) {
        uint64_t rec = LD64(items + ARR_DATA + 8 * (uint64_t)i);
        if (!rec) continue;
        int keep = (uint32_t)rt_call(c, FN(F_COURSE_STAGELIST), 2, rec, 0ull) >= LIST_BASE;     // an imported course
        for (int k = 0; !keep && own_items && k < own_n; k++) keep = LD64(own_items + ARR_DATA + 8 * (uint64_t)k) == rec;
        if (keep) ST64(items + ARR_DATA + 8 * (uint64_t)kept++, rec);
    }
    for (int i = kept; i < n; i++) ST64(items + ARR_DATA + 8 * (uint64_t)i, 0);
    ST32(all + LIST_SIZE, (uint32_t)kept);
    ST32(all + LIST_VERSION, LD32(all + LIST_VERSION) + 1);
    if (getenv("BR_MANIA_LOG")) {
        char ids[400];
        int len = 0;
        ids[0] = 0;
        for (int i = 0; i < kept && len < 380; i++)
            len += snprintf(ids + len, sizeof ids - (size_t)len, " %u", LD32(LD64(items + ARR_DATA + 8 * (uint64_t)i) + 0x18));
        rt_log("mania: world picker: highest %u, the game lists %d, the chain has %d, kept %d:%s", (uint32_t)highest, own_n, n, kept, ids);
    }
    c->x[0] = all;
    c->x[30] = lr;
    return 1;
}

// The "Mania" tab of Select World. The tabs are the rows of the table MainGame_Adventure_Type (Story, Special); each
// tab holds the MainGame_Category rows of its type (Story: the plain game; Special: the time attacks and rules), and
// each of those the courses enabled for it. The import adds a third row (mania\build.py; "tab <row id>" in
// mania_courses.txt) but no category: a new category id would be a new game mode to everything that reads it.
// Instead, once the game has built its lists, the imported courses are taken out of the Story tab's list and put
// into a second item of the same category under the new tab, so a course chosen there starts exactly as before.
//   FlowCourseSelect: +0x48 m_AdvTypeDataList, +0x68 m_SelectedTabIndex, +0x6c m_SelectedCourseIndex
//   UiMainGameAdvTypeItemData: +0x28 record, +0x30 categoryList     UiMainGameCategoryItemData: +0x20 record, +0x28 courseList
//   CourseData: +0x20 record                                         IDRecord: +0x18 id
#define F_COURSE_SETUP_NEXT 0x46a17d0ull    // FlowCourseSelect.<SetupCourseSelect>d__19.MoveNext (+0x20: the FlowCourseSelect)
#define F_TAB_SELECTED 0x46a08b0ull         // FlowCourseSelectModeBase.onUpdateTabSelectedIdx(int, UIChoicesItemData, button)
#define F_OBJECT_NEW 0x44c4a0ull            // il2cpp_codegen_object_new(class)
#define F_CATEGORY_ITEM_CTOR 0x469ed70ull   // UiMainGameCategoryItemData..ctor(MainGame.Category.Record)
#define F_LIST_ADD 0x3397800ull             // List<object>.AddWithResize(item), method from the list class's rgctx
#define REC_ID 0x18
#define SELECTOR_CATEGORY 0x10              // SelectorParam: the MainGame.Category and the course last chosen
#define SELECTOR_COURSE 0x20
static uint64_t g_tab_class;                // class of UiMainGameAdvTypeItemData (seen on the first build)
static int g_row_mania, g_row_own;          // the cursor's row in the new tab and in the game's own (see the tab hook)

static int list_n(uint64_t list) { return list ? (int)LD32(list + LIST_SIZE) : 0; }
static uint64_t list_at(uint64_t list, int i) { return LD64(LD64(list + LIST_ITEMS) + ARR_DATA + 8 * (uint64_t)i); }
static uint32_t rec_id(uint64_t item, int off) { uint64_t r = item ? LD64(item + off) : 0; return r ? LD32(r + REC_ID) : 0; }
static void list_add(Cpu *c, uint64_t list, uint64_t item) {
    // as the game's own inlined List.Add does it: the method is an entry of the list class's generic context
    rt_call(c, FN(F_LIST_ADD), 3, list, item, LD64(LD64(LD64(list) + 0xc0) + 0x70));
}

static void fill_mania_tab(Cpu *c, uint64_t flow) {
    uint64_t tabs = flow ? LD64(flow + 0x48) : 0, story = 0, tab = 0;
    int ntabs = list_n(tabs), tab_index = -1;
    for (int i = 0; i < ntabs; i++) {
        uint64_t t = list_at(tabs, i);
        uint32_t id = rec_id(t, 0x28);
        if (id == 1) story = t;
        if (id == g_tab) { tab = t; tab_index = i; }
    }
    if (!tab || !story || list_n(LD64(tab + 0x30))) return;          // not built yet, or already filled
    g_tab_class = LD64(tab);
    uint64_t cats = LD64(story + 0x30), cat = 0;
    for (int i = 0; i < list_n(cats) && !cat; i++)
        if (rec_id(list_at(cats, i), 0x20) == 1) cat = list_at(cats, i);
    uint64_t courses = cat ? LD64(cat + 0x28) : 0;
    int n = list_n(courses), imported = 0;
    for (int i = 0; i < n; i++) imported += rec_id(list_at(courses, i), 0x20) >= g_first_id;
    if (!imported) {                                                 // nothing to show: no tab (it is the last one)
        if (tab_index == ntabs - 1) {
            ST64(LD64(tabs + LIST_ITEMS) + ARR_DATA + 8 * (uint64_t)tab_index, 0);
            ST32(tabs + LIST_SIZE, (uint32_t)(ntabs - 1));
            ST32(tabs + LIST_VERSION, LD32(tabs + LIST_VERSION) + 1);
        }
        return;
    }
    uint64_t item = rt_call(c, FN(F_OBJECT_NEW), 1, LD64(cat));
    rt_call(c, FN(F_CATEGORY_ITEM_CTOR), 3, item, LD64(cat + 0x20), 0ull);
    list_add(c, LD64(tab + 0x30), item);                             // reachable from here on
    uint64_t mine = LD64(item + 0x28), items = LD64(courses + LIST_ITEMS);
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull);
    uint32_t sel_course = sel && LD32(sel + SELECTOR_CATEGORY) == 1 ? LD32(sel + SELECTOR_COURSE) : 0;
    int kept = 0, moved = 0;
    g_row_mania = g_row_own = 0;
    for (int i = 0; i < n; i++) {
        uint64_t cd = LD64(items + ARR_DATA + 8 * (uint64_t)i);
        uint32_t id = rec_id(cd, 0x20);
        if (id >= g_first_id) {
            if (id == sel_course) { ST32(flow + 0x68, (uint32_t)tab_index); ST32(flow + 0x6c, (uint32_t)moved); }
            list_add(c, mine, cd);
            moved++;
        } else {
            if (id == sel_course) ST32(flow + 0x6c, (uint32_t)kept);
            ST64(items + ARR_DATA + 8 * (uint64_t)kept++, cd);
        }
    }
    for (int i = kept; i < n; i++) ST64(items + ARR_DATA + 8 * (uint64_t)i, 0);
    ST32(courses + LIST_SIZE, (uint32_t)kept);
    ST32(courses + LIST_VERSION, LD32(courses + LIST_VERSION) + 1);
    if (getenv("BR_MANIA_LOG"))
        rt_log("mania: Select World: %d imported worlds moved to tab %d, %d stay under Story; opens on tab %d, world %d", moved, tab_index, kept,
               (int)LD32(flow + 0x68), (int)LD32(flow + 0x6c));
}

// The tab bar of Select World (ui_PartView_WorldSelect_TabGroup, a UIPartViewTabGroup_Explicit) has two buttons at
// fixed places (its layout group does not move them). A button for the third tab is a copy of the second one, and
// all three are made smaller and spread over the room the two had, between the L and R marks. The button images
// are plain sprites (not sliced), so a button is scaled as a whole; its text is scaled back up to stay readable.
//   UIStateMainGameSelect +0xd0 -> +0x10 -> +0xa0: the world select view; +0x48 its tab group; +0x58 the buttons
#define F_INSTANTIATE 0x3ee5e00ull          // UnityEngine.Object.Instantiate(Object original, Transform parent)
#define F_GET_PARENT 0x3eee6b0ull           // Transform.get_parent
#define F_GET_ANCHORED_POS 0x3eec8d0ull     // RectTransform.get_anchoredPosition -> Vector2 in v0, v1
#define F_SET_ANCHORED_POS 0x3eec9a0ull     // RectTransform.set_anchoredPosition(Vector2)
#define TAB_DRAWN_WIDTH 280.0f              // ImageBackGround of a tab button
static const float g_tab_gap = 22.0f, g_tab_margin = 12.0f, g_tab_text = 0.85f;    // between buttons; added room at each end; text size

static void get_floats(Cpu *c, uint64_t fn, uint64_t tr, float *f, int n) {
    c->x[0] = tr; c->x[1] = 0;
    rt_call_regs(c, FN(fn));
    for (int i = 0; i < n; i++) { uint32_t u = (uint32_t)c->v[i]; memcpy(&f[i], &u, 4); }
}

static void fit_tab_buttons(Cpu *c, uint64_t flow) {
    uint64_t tabs = flow ? LD64(flow + 0x48) : 0, state = flow ? LD64(flow + 0x40) : 0, acc = state ? LD64(state + 0xd0) : 0;
    uint64_t views = acc ? LD64(acc + 0x10) : 0, view = views ? LD64(views + 0xa0) : 0;
    uint64_t group = view && LD64(view + 0x10) ? LD64(view + 0x48) : 0, buttons = group ? LD64(group + 0x58) : 0;
    int want = list_n(tabs), have = list_n(buttons);
    if (have < 2 || have >= want) return;
    uint64_t rgctx = LD64(LD64(buttons) + 0xc0), last = list_at(buttons, have - 1);
    if (!last || !LD64(last + 0x10) || !rgctx || !LD64(rgctx + 0x70)) return;
    uint64_t parent = rt_call(c, FN(F_GET_PARENT), 2, rt_call(c, FN(F_GET_TRANSFORM), 2, last, 0ull), 0ull);
    while (have < want) {
        uint64_t copy = rt_call(c, FN(F_INSTANTIATE), 3, last, parent, 0ull);
        if (!copy) return;
        list_add(c, buttons, copy);
        have++;
    }
    // the two buttons' centres give the room there is: from the left end of the first to the right end of the second
    float first[2], second[2];
    get_floats(c, F_GET_ANCHORED_POS, rt_call(c, FN(F_GET_TRANSFORM), 2, list_at(buttons, 0), 0ull), first, 2);
    get_floats(c, F_GET_ANCHORED_POS, rt_call(c, FN(F_GET_TRANSFORM), 2, list_at(buttons, 1), 0ull), second, 2);
    float left = first[0] - TAB_DRAWN_WIDTH / 2 - g_tab_margin, room = second[0] + TAB_DRAWN_WIDTH / 2 + g_tab_margin - left;
    float s = (room - (float)(have - 1) * g_tab_gap) / ((float)have * TAB_DRAWN_WIDTH);
    if (s > 1.0f) s = 1.0f;
    for (int i = 0; i < have; i++) {
        uint64_t button = list_at(buttons, i), tr = rt_call(c, FN(F_GET_TRANSFORM), 2, button, 0ull);
        float pos[2] = {left + s * TAB_DRAWN_WIDTH * ((float)i + 0.5f) + g_tab_gap * (float)i, first[1]};
        float scale[3] = {s, s, 1.0f}, text_scale[3] = {g_tab_text / s, g_tab_text / s, 1.0f};
        set_floats(c, F_SET_ANCHORED_POS, tr, pos, 2);
        set_floats(c, F_SET_LOCAL_SCALE, tr, scale, 3);
        uint64_t text = LD64(button + 0x68);                         // UIPartViewSelectableButton.m_Text
        if (text && g_tab_text > s) set_floats(c, F_SET_LOCAL_SCALE, rt_call(c, FN(F_GET_TRANSFORM), 2, text, 0ull), text_scale, 3);
    }
    rt_log("mania: Select World: the tab bar has %d buttons now (scale %.2f)", have, s);
}

// the coroutine that builds the lists and then the views: after each step, move the courses if the lists are new
int rt_hook_46a17d0(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    if (g_ncourses < 0) load_courses();
    if (!g_tab || !g_first_id) return 0;
    uint64_t lr = c->x[30], self = c->x[0], x1 = c->x[1];
    fit_tab_buttons(c, LD64(self + 0x20));          // the view can turn up in the very step that reads the buttons
    inside = 1;
    uint64_t more = rt_call(c, FN(F_COURSE_SETUP_NEXT), 2, self, x1);
    inside = 0;
    fill_mania_tab(c, LD64(self + 0x20));
    fit_tab_buttons(c, LD64(self + 0x20));
    c->x[0] = more;
    c->x[30] = lr;
    return 1;
}

// A tab was chosen. The game starts the plain course picker for type 1 (Story) and the time attack one for type 2,
// and for any other type leaves the picker of the tab before it running. The new tab is a second Story tab: its
// record carries Story's id for the length of the call.
//
// The game keeps the cursor on the same world when the tab changes (Story and Special list the same worlds) and
// otherwise on the same row. The new tab shares no world with the others, so the row is remembered per side:
// going back to Story returns to the world the cursor was on, not to row n of a list that may be locked there.
int rt_hook_46a08b0(Cpu *c) {
    static __thread int inside;
    uint64_t self = c->x[0], item = c->x[2], flow = self ? LD64(self + 0x38) : 0;
    if (inside || !g_tab || !flow || !item || LD64(item) != g_tab_class) return 0;
    uint64_t tabs = LD64(flow + 0x48);
    int from = (int)LD32(flow + 0x68), to_mania = rec_id(item, 0x28) == g_tab;
    int from_mania = from >= 0 && from < list_n(tabs) && rec_id(list_at(tabs, from), 0x28) == g_tab;
    if (from_mania != to_mania) {
        *(from_mania ? &g_row_mania : &g_row_own) = (int)LD32(flow + 0x6c);
        ST32(flow + 0x6c, (uint32_t)(to_mania ? g_row_mania : g_row_own));
    }
    if (!to_mania) return 0;
    uint64_t lr = c->x[30], rec = LD64(item + 0x28);
    inside = 1;
    ST32(rec + REC_ID, 1);
    rt_call(c, FN(F_TAB_SELECTED), 5, self, c->x[1], item, c->x[3], c->x[4]);
    ST32(rec + REC_ID, g_tab);
    inside = 0;
    c->x[30] = lr;
    return 1;
}

// Wonder.Util.Adventure.GetCourseCategory(): the Course.Category of the course last chosen. The tab names are
// arrays indexed by it (the first tab reads Story, Extra or Ultimate with the world under the cursor), and the
// imported courses are listed as Ultimate ones. For the two callers that name the tabs an imported course counts
// as a Story one, so the tabs read Story / Special / Mania while the cursor is in the new tab.
int rt_hook_440c2f0(Cpu *c) {
    uint64_t lr = c->x[30], x0 = c->x[0];
    if (!g_tab || (lr != FN(0x469dc30ull) && lr != FN(0x469dfb8ull))) return 0;     // onUpdateCourseFocusIndex, onInitTabGroupSelectableButton
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull);
    int imported = sel && LD32(sel + SELECTOR_COURSE) >= g_first_id;
    c->x[0] = imported ? 1 : x0;
    c->x[30] = lr;
    return imported;
}

// Wonder.MgStageSwitchController.Request(eState switchType, int classId, int serialId, bool playSound, float time):
// a switch was pressed. BR_MANIA_LOG=1 logs it (a test aid for imported switch stages).
int rt_hook_4308520(Cpu *c) {
    static int on = -1;
    if (on < 0) on = getenv("BR_MANIA_LOG") != NULL;
    if (on) rt_log("mania: switch request: state %d, class %d, serial %d", (int)c->x[1], (int)c->x[2], (int)c->x[3]);
    return 0;
}

// Wonder.MgSwitch.OnTriggerEnterPlayer(PhysicsBall): a ball has rolled onto a switch. Outside battles the switch
// queues its request on the controller itself, so this is the one place every press passes.
int rt_hook_430b0a0(Cpu *c) {
    static int on = -1;
    if (on < 0) on = getenv("BR_MANIA_LOG") != NULL;
    if (on && c->x[0]) rt_log("mania: switch pressed: type %d, class %d, serial %d", (int)LD32(c->x[0] + 0x20), (int)LD32(c->x[0] + 0x24), (int)LD32(c->x[0] + 0x28));
    return 0;
}

// Wonder.MgSeesaw.OnPostCollide(GameObject sphereGO): a ball touches a seesaw's collision part (BR_MANIA_LOG)
int rt_hook_4305d30(Cpu *c) {
    static int on = -1, calls;
    if (on < 0) on = getenv("BR_MANIA_LOG") != NULL;
    if (on && c->x[0] && calls++ % 15 == 0) {
        float angle, speed;
        uint32_t a = LD32(c->x[0] + 0x30), s = LD32(c->x[0] + 0x2c);
        memcpy(&angle, &a, 4);
        memcpy(&speed, &s, 4);
        rt_log("mania: seesaw touched (call %d): angle %.3f, angular speed %.4f", calls, angle, speed);
    }
    return 0;
}

// Is the object `component` (anything with a Transform) of the stage being played inside an area of this kind?
#define F_GET_POSITION 0x3eee800ull         // UnityEngine.Transform.get_position -> Vector3 in v0..v2
static int in_area(Cpu *c, int kind, uint64_t component, const char *what) {
    if (g_ncourses < 0) load_courses();
    int any = 0;
    for (int i = 0; i < g_nareas; i++) any |= g_areas[i].kind == kind;
    if (!any || !component) return 0;
    uint64_t sel = rt_call(c, FN(F_GET_SELECTOR), 1, 0ull), list = sel ? LD64(sel + SELECTOR_STAGELIST) : 0;
    uint32_t stage = list ? (uint32_t)rt_call(c, FN(F_CURRENT_STAGE), 2, list, 0ull) : 0;
    float p[3];
    int hit = 0, mine = 0;
    for (int i = 0; i < g_nareas; i++) mine |= g_areas[i].kind == kind && g_areas[i].stage == stage;
    if (!mine) return 0;
    get_floats(c, F_GET_POSITION, rt_call(c, FN(F_GET_TRANSFORM), 2, component, 0ull), p, 3);
    for (int i = 0; i < g_nareas && !hit; i++) {
        if (g_areas[i].kind != kind || g_areas[i].stage != stage) continue;
        float dx = p[0] - g_areas[i].c[0], dy = p[1] - g_areas[i].c[1], dz = p[2] - g_areas[i].c[2];
        hit = dx * dx + dy * dy + dz * dz < g_areas[i].r * g_areas[i].r;
    }
    if (getenv("BR_MANIA_LOG"))
        rt_log("mania: %s at (%.1f, %.1f, %.1f) is %s of stage row %u", what, p[0], p[1], p[2], hit ? "inside an area: ignored" : "outside the areas", stage);
    return hit;
}

// Wonder.MgGoalColi.OnTriggerEnterPlayer(PhysicsBall): a ball enters a goal. Not when the goal stands in an
// "inactive goal" area of an imported stage (Factory's goals travel on a belt and are parked in such an area).
int rt_hook_4301e40(Cpu *c) {
    uint64_t self = c->x[0], ball = c->x[1], x2 = c->x[2], lr = c->x[30];
    int skip = in_area(c, AREA_GOAL, self, "a goal");
    c->x[0] = self; c->x[1] = ball; c->x[2] = x2; c->x[30] = lr;
    return skip;
}

// Wonder.MgWormhole.OnTriggerEnterPlayer(PhysicsBall): a ball touches a wormhole. Not when the ball is in a
// "no wormhole" area of an imported stage.
int rt_hook_430cc30(Cpu *c) {
    uint64_t self = c->x[0], ball = c->x[1], x2 = c->x[2], lr = c->x[30];
    int skip = in_area(c, AREA_WORMHOLE, ball, "a ball at a wormhole");
    if (!skip && getenv("BR_MANIA_LOG")) rt_log("mania: a ball enters a wormhole (pair %d)", (int)LD32(self + 0x54));
    c->x[0] = self; c->x[1] = ball; c->x[2] = x2; c->x[30] = lr;
    return skip;
}

// Wonder.CollisionJamabar.move(): a jamabar (the sliding bars of SMB1's Stoppers) takes a step. The bar slides with
// the gravity of the player whose MgGravityController it was given (+0x168), and without one it does not move.
// Nothing in Rumble's code gives it one (the game has the class but no stage with a bar), so the port does: the
// first local player's. With several players each machine moves the bars by its own player.
#define F_PLAYER_LIST 0x42a1880ull          // Wonder.MainGame.get_playerList -> List<MgPlayer> (static, through the singleton)
#define F_OBJ_ALIVE 0x3ee4c20ull            // UnityEngine.Object.op_Implicit (static)
#define PLAYER_IS_LOCAL 0x1b8               // MgPlayer.m_IsLocal
#define PLAYER_GRAVITY 0x68                 // MgPlayer.m_GravityController
#define JAMABAR_GRAVITY 0x168               // CollisionJamabar.<gravityController>k__BackingField
int rt_hook_4282ca0(Cpu *c) {
    uint64_t self = c->x[0], x1 = c->x[1], lr = c->x[30];
    uint64_t have = self ? LD64(self + JAMABAR_GRAVITY) : 0;
    if (self && !(have && (rt_call(c, FN(F_OBJ_ALIVE), 2, have, 0ull) & 1))) {
        uint64_t players = rt_call(c, FN(F_PLAYER_LIST), 1, 0ull), found = 0;
        int n = list_n(players);
        for (int i = 0; i < n && !found; i++) {
            uint64_t p = list_at(players, i);
            if (p && LD8(p + PLAYER_IS_LOCAL)) found = LD64(p + PLAYER_GRAVITY);
        }
        if (found && (rt_call(c, FN(F_OBJ_ALIVE), 2, found, 0ull) & 1)) {
            static int said;
            ST64(self + JAMABAR_GRAVITY, found);
            if (!said++ && getenv("BR_MANIA_LOG")) rt_log("mania: jamabars follow the local player's gravity");
        } else if (have) ST64(self + JAMABAR_GRAVITY, 0);
    }
    c->x[0] = self; c->x[1] = x1; c->x[30] = lr;
    return 0;
}

// Framework.EnumRuntimeHelper<Int32Enum>.GetValue(string name, T defaultValue) (static, shared by every enum)
int rt_hook_2e6be10(Cpu *c) {
    uint64_t s = c->x[0];
    if (!s) return 0;
    int n = (int)LD32(s + 0x10);
    if (n < 6 || n > 9) return 0;
    uint32_t v = 0;
    for (int i = 0; i < n; i++) {
        uint16_t ch = LD16(s + 0x14 + 2 * (uint64_t)i);
        if (ch < '0' || ch > '9') return 0;
        v = v * 10 + (uint32_t)(ch - '0');
    }
    c->x[0] = v;
    return 1;
}

#define ITEM_NEXT 0x20                      // StageListItem.m_NextStage -> StageListNextArray {+0x10 Stage.eID[]}
// Wonder.StageList.Setup(Stage.List.eID stageListID, Course.eID courseID, bool isForce)
int rt_hook_43287d0(Cpu *c) {
    static __thread int inside;
    if (inside) return 0;
    if (g_ncourses < 0) load_courses();
    uint64_t self = c->x[0], lr = c->x[30];
    uint32_t list = (uint32_t)c->x[1], course = (uint32_t)c->x[2];
    int k = -1;
    for (int i = 0; i < g_ncourses; i++)
        if (g_courses[i].list == list) k = i;
    if (k < 0) return 0;
    inside = 1;
    rt_call(c, FN(F_STAGELIST_SETUP), 5, self, (uint64_t)REAL_LIST, (uint64_t)course, 1ull, 0ull);
    inside = 0;
    uint64_t lst = LD64(self + STAGELIST_ITEMS), items = lst ? LD64(lst + LIST_ITEMS) : 0;
    int n = lst ? (int)LD32(lst + LIST_SIZE) : 0, first = g_courses[k].first, count = g_courses[k].count;
    if (first > n) first = n;
    if (first + count > n) count = n - first;
    if (!items) count = 0;
    for (int i = 0; i < count; i++) {
        uint64_t item = LD64(items + ARR_DATA + 8 * (uint64_t)(first + i));
        ST64(items + ARR_DATA + 8 * (uint64_t)i, item);
        if (item) { ST32(item + ITEM_STAGE_INDEX, (uint32_t)i); ST32(item + ITEM_INDEX_IN_LIST, (uint32_t)i); }
    }
    for (int i = count; i < n; i++) ST64(items + ARR_DATA + 8 * (uint64_t)i, 0);
    // Each item carries the stage that follows it (StageListItem.m_NextStage, read by StageList.GetNextStage when a
    // stage is cleared). In the one real list the last stage of a course is followed by the first stage of the
    // next course; here it is the end of the world, as on the last stage of one of the game's own lists.
    if (count > 0) {
        uint64_t last = LD64(items + ARR_DATA + 8 * (uint64_t)(count - 1));
        uint64_t next = last ? LD64(last + ITEM_NEXT) : 0, arr = next ? LD64(next + 0x10) : 0;
        int len = arr ? (int)LD32(arr + 0x18) : 0;
        for (int i = 0; i < len && i < 8; i++) ST32(arr + 0x20 + 4 * (uint64_t)i, 0);
    }
    if (lst) { ST32(lst + LIST_SIZE, (uint32_t)count); ST32(lst + LIST_VERSION, LD32(lst + LIST_VERSION) + 1); }
    ST32(self + STAGELIST_ID, list);
    ST32(self + STAGELIST_INDEX, 0);
    if (count > 0) rt_call(c, FN(F_STAGELIST_SET_INDEX), 3, self, 0ull, 0ull);
    c->x[30] = lr;
    return 1;
}
