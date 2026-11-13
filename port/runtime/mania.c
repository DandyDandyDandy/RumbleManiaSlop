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

static void load_courses(void) {
    char path[700], line[128];
    g_ncourses = 0;
    snprintf(path, sizeof path, "%smania\\mania_courses.txt", rt_exe_dir());
    FILE *f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof line, f) && g_ncourses < MAX_COURSES) {
        unsigned list;
        int first, count;
        if (sscanf(line, "%u %d %d", &list, &first, &count) == 3 && count > 0 && first >= 0) {
            g_courses[g_ncourses].list = list;
            g_courses[g_ncourses].first = first;
            g_courses[g_ncourses].count = count;
            g_ncourses++;
        }
    }
    fclose(f);
    rt_log("mania: %d imported courses", g_ncourses);
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
    if (lst) { ST32(lst + LIST_SIZE, (uint32_t)count); ST32(lst + LIST_VERSION, LD32(lst + LIST_VERSION) + 1); }
    ST32(self + STAGELIST_ID, list);
    ST32(self + STAGELIST_INDEX, 0);
    if (count > 0) rt_call(c, FN(F_STAGELIST_SET_INDEX), 3, self, 0ull, 0ull);
    c->x[30] = lr;
    return 1;
}
