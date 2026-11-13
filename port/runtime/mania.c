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
// Without the mania folder none of this changes anything: no stage row has a numeric scene name and no course has
// a virtual list.
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
static struct { uint32_t stage, cue; } g_music[MAX_MUSIC];
static int g_nmusic = -1;

static void load_music(void) {
    char path[700], line[128];
    g_nmusic = 0;
    snprintf(path, sizeof path, "%smania\\mania_music.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && g_nmusic < MAX_MUSIC) {
        unsigned stage, cue;
        if (sscanf(line, "%u %u", &stage, &cue) == 2) { g_music[g_nmusic].stage = stage; g_music[g_nmusic].cue = cue; g_nmusic++; }
    }
    fclose(f);
    rt_log("mania: imported music for %d stages", g_nmusic);
}

// Wonder.MainGameBg.calcBgCue() -> ValueTuple<Sound.Cue.eID, Sound.Cue.eID> (the BGM cue and its overlay cue, in x0)
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
            if (said != stage && getenv("BR_MANIA_LOG")) rt_log("mania: stage row %u gets BGM cue row %u", stage, g_music[i].cue);
            said = stage;
            c->x[0] = g_music[i].cue;           // no overlay cue
            return 1;
        }
    c->x[0] = self;
    return 0;
}

#define MAX_OWN 64
static struct { uint32_t id, prev; } g_own[MAX_OWN];      // the game's Adventure worlds in display order
static int g_nown;
static uint32_t g_first_id;                               // the lowest course id of the import

static void load_courses(void) {
    char path[700], line[128];
    g_ncourses = 0;
    snprintf(path, sizeof path, "%smania\\mania_courses.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f)) {
        unsigned list, id = 0, prev = 0;
        int first, count;
        if (sscanf(line, "own %u %u", &id, &prev) == 2) {
            if (g_nown < MAX_OWN) { g_own[g_nown].id = id; g_own[g_nown].prev = prev; g_nown++; }
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
