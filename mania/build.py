"""Import Banana Mania into the built game: makes the override folder game\\mania\\.

    python build.py <Banana Mania folder> [--only COURSE[,COURSE...]] [--jobs N] [--no-stages]

What it writes (the game's own files are never changed; deleting game\\mania\\ undoes everything):

    mania\\Switch\\mania\\scene_<n>.bundle     one converted stage scene each (stage.py)
    mania\\Switch\\...                        changed copies of the game's table bundles (dbtable.py)
    mania\\catalog.json                      the game's Addressables catalog plus the new scenes
    mania\\mania_courses.txt                 the stage range of each imported course (read by port\\runtime\\mania.c)

How the stages become courses (docs/MANIA.md has the reasons):

    Stage                   a new row per imported stage; its scene name is the number 100000 + Mania stage id
    Stage_Text_<lang>       the stage's name
    Stage_DoleDisposition   a row per new stage (the sponsor logo under the start; the game reads it without a check)
    Stage_List_Group_wld97_wldtst   the unused test list 12: the stages of every imported course, one after the other
    Course, Course_Text_<lang>      a row per imported course, with a virtual stage list id 1000 + n
    MainGame_Story_Progress         a row per (course, stage) that opens the stage from the start
"""
import argparse
import hashlib
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port'))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port', 'assets'))

import paths  # noqa: E402
from aacatalog import Catalog  # noqa: E402
from dbtable import LANGS, Database  # noqa: E402
from maniadata import ManiaData  # noqa: E402

RT = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}'
SCENE_BASE = 100000             # scene id of a stage = SCENE_BASE + Mania stage id
LIST_BASE = 1000                # virtual stage list id of imported course n = LIST_BASE + n
REAL_LIST_TABLE = 'Stage_List_Group_wld97_wldtst'
COURSE_CATEGORY = 6             # Course.Category the imported courses are listed under
TEMPLATE_STAGE_ROW = 8          # World 1 Stage 1: the model for new stage rows

# (Mania course, numbering prefix, name; None = the course's own name in Mania's text)
COURSES = [
    ('Smb1Org_Shokyu', 'SMB1 B', 'SMB1 Beginner'), ('Smb1Org_ShokyuEx', 'SMB1 BX', 'SMB1 Beginner Extra'),
    ('Smb1Org_Chukyu', 'SMB1 A', 'SMB1 Advanced'), ('Smb1Org_ChukyuEx', 'SMB1 AX', 'SMB1 Advanced Extra'),
    ('Smb1Org_Jyokyu', 'SMB1 E', 'SMB1 Expert'), ('Smb1Org_JyokyuEx', 'SMB1 EX', 'SMB1 Expert Extra'),
    ('Smb1Org_JyokyuEx2', 'SMB1 M', 'SMB1 Master'),
] + [(f'Smb2_StoryWorld{i:02d}', f'SMB2 W{i}', None) for i in range(1, 11)] + [
    ('Smb2Org_Shokyu', 'SMB2 B', 'SMB2 Beginner'), ('Smb2Org_ShokyuEx', 'SMB2 BX', 'SMB2 Beginner Extra'),
    ('Smb2Org_Chukyu', 'SMB2 A', 'SMB2 Advanced'), ('Smb2Org_ChukyuEx', 'SMB2 AX', 'SMB2 Advanced Extra'),
    ('Smb2Org_Jyokyu', 'SMB2 E', 'SMB2 Expert'), ('Smb2Org_JyokyuEx', 'SMB2 EX', 'SMB2 Expert Extra'),
    ('Smb2Org_Master', 'SMB2 M', 'SMB2 Master'), ('Smb2Org_MasterEx', 'SMB2 MX', 'SMB2 Master Extra'),
    ('SmbDx', 'DX', None), ('SpecialOriginal', 'ORG', None), ('SpecialReverse', 'REV', None),
    ('*', 'ETC', 'More Stages'),            # every stage that is in none of the courses above
]
# Mania background -> the Rumble world whose scenery, sky, lighting (and, without imported music, BGM) the stage gets
WORLD_OF_BG = {
    'Smb1_Jungle': 1, 'Smb1_Water': 2, 'Smb1_Night': 6, 'Smb1_Sunset': 4, 'Smb1_Space': 10, 'Smb1_Sands': 5, 'Smb1_Ice': 7,
    'Smb1_Storm': 8, 'Smb1_Masters': 9, 'Smb1_Bonus': 3,
    'Smb2_Jungle': 1, 'Smb2_Lava': 4, 'Smb2_Water': 2, 'Smb2_Whale': 3, 'Smb2_Park': 5, 'Smb2_Pot': 8, 'Smb2_Bubble': 7,
    'Smb2_Gear': 9, 'Smb2_Space': 10, 'Smb2_Electric': 6, 'Smb2_Bonus': 3,
}
SCENERY_FIELDS = ('LightSceneID', 'FarSceneID', 'SkySceneID', 'EffectSceneID', 'ScreenEffectAssetRef', 'LightSceneSplitScrenID',
                  'FarSceneSplitScreenID', 'SkySceneSplitScreenID', 'EffectSceneSplitScreenID', 'ScreenEffectSplitScreenAssetRef',
                  'MiniMapImageID')
MANIA_LANG = {'es419': 'es', 'ptbr': 'en'}      # Rumble languages Mania has no text for


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def scene_id(stage_id):
    return SCENE_BASE + stage_id


def bundle_rel(stage_id):
    return f'Switch/mania/scene_{scene_id(stage_id)}.bundle'


def _convert(job):
    mania_dir, aa_switch, bundle, out, identity = job
    from stage import Converter
    global _CONV
    try:
        conv = _CONV
    except NameError:
        conv = _CONV = Converter(mania_dir, aa_switch)
    try:
        return bundle, conv.convert(bundle, out, identity), None
    except Exception as e:                      # one broken stage must not stop the import
        import traceback
        return bundle, None, f'{type(e).__name__}: {e} | {traceback.format_exc(limit=3).splitlines()[-2].strip()}'


def plan_courses(mania, only=None):
    """[(Mania course name, prefix, display name, [stage ids])] in import order."""
    out, used = [], set()
    for name, prefix, title in COURSES:
        if name == '*':
            ids = sorted(i for i in mania.stages if i not in used and i in mania.bundles)
        else:
            c = mania.courses.get(name)
            if c is None:
                continue
            ids = [i for i in c['stages'] if i in mania.stages and i in mania.bundles]
            title = title or mania.texts('en', 'maingame').get(c['text_key']) or name
            if name.startswith('Smb2_StoryWorld'):
                title = f'SMB2 {title}'
        if only and name not in only:
            if name != '*':
                used.update(ids)
            continue
        used.update(ids)
        if ids:
            out.append((name, prefix, title, ids))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('mania')
    ap.add_argument('--game', default=str(paths.GAME))
    ap.add_argument('--only', help='import only these Mania courses (comma separated; for testing)')
    ap.add_argument('--jobs', type=int, default=max(1, (os.cpu_count() or 4) - 2))
    ap.add_argument('--no-stages', action='store_true', help='keep the stage bundles that are already there')
    a = ap.parse_args()
    game = a.game
    aa = os.path.join(game, f'{paths.NAME}_Data', 'StreamingAssets', 'aa')
    aa_switch = os.path.join(aa, 'Switch')
    out = os.path.join(game, 'mania')
    out_switch = os.path.join(out, 'Switch')
    os.makedirs(os.path.join(out_switch, 'mania'), exist_ok=True)
    t0 = time.time()

    mania = ManiaData(a.mania)
    courses = plan_courses(mania, set(a.only.split(',')) if a.only else None)
    stage_ids = []
    for _, _, _, ids in courses:
        stage_ids += [i for i in ids if i not in stage_ids]
    print(f'{len(courses)} courses, {len(stage_ids)} stages', flush=True)

    # ---- stage scenes
    failed, reports = {}, {}
    if not a.no_stages:
        jobs = []
        for sid in stage_ids:
            ident = (f'mania_scene_{scene_id(sid)}', f'Assets/Mania/{scene_id(sid)}.unity', 'CAB-' + md5(f'mania scene {sid}'))
            jobs.append((a.mania, aa_switch, mania.bundles[sid], os.path.join(out, bundle_rel(sid).replace('/', os.sep)), ident))
        done = 0
        with ProcessPoolExecutor(a.jobs) as pool:
            for bundle, stats, err in pool.map(_convert, jobs, chunksize=2):
                done += 1
                if err:
                    failed[bundle] = err
                    print(f'  FAILED {bundle}: {err}', flush=True)
                else:
                    reports[bundle] = stats
                if done % 25 == 0 or done == len(jobs):
                    print(f'  {done}/{len(jobs)} stages converted', flush=True)
    stage_ids = [i for i in stage_ids if os.path.exists(os.path.join(out, bundle_rel(i).replace('/', os.sep)))]
    courses = [(n, p, t, [i for i in ids if i in stage_ids]) for n, p, t, ids in courses]
    courses = [c for c in courses if c[3]]

    # ---- tables
    db = Database(aa_switch, cache=str(paths.BUILD / 'mania_table_index.json'))
    stage_t = db.table('Stage')
    model = dict(stage_t.row(TEMPLATE_STAGE_ROW))
    scenery = {}
    for w in range(1, 11):
        row = next((r for r in stage_t.rows if not r['_empty'] and r['SceneID'].startswith(f'bg_stg_w{w:02d}_0')), None)
        scenery[w] = {f: row[f] for f in SCENERY_FIELDS} if row else {f: model[f] for f in SCENERY_FIELDS}
    dole_t = db.table('Stage_DoleDisposition')
    dole_model = dict(dole_t.row(TEMPLATE_STAGE_ROW))
    text_t = {lang: db.table(f'Stage_Text_{lang}') for lang in LANGS}
    row_of = {}
    next_id = len(stage_t.rows)
    for sid in stage_ids:
        rid = next_id
        next_id += 1
        row_of[sid] = rid
        st = mania.stages[sid]
        fields = {k: v for k, v in model.items() if not k.startswith('_')}
        fields.update(scenery[WORLD_OF_BG.get(st['bg'], 1)])
        fields.update(Name=rid, SceneID=str(scene_id(sid)), TimeLimit=mania.time_limit(sid), CaptionText=rid, ThumbnailSpriteID=0,
                      MiniThumbnailSpriteID=0, MissionPoint=0, MissionPointMaster=0, MissionBanana=0, CheckpointStageAnimationFrame=0,
                      CheckpointSwitchClass=-1, CheckpointSwitchAnimationSpeed=0, CheckpointSwitchAnimationFrame=0, AnimationType=0,
                      AnimationSpeedMultiplier=0.0)
        stage_t.use(rid, **fields)
        dole_t.use(rid, **{k: v for k, v in dole_model.items() if not k.startswith('_')})
        for lang, t in text_t.items():
            caption = t.row(TEMPLATE_STAGE_ROW)['CaptionText']
            t.use(rid, Name=mania.stage_name(sid, MANIA_LANG.get(lang, lang)), CaptionText=caption)

    group = db.table(REAL_LIST_TABLE)
    group.rows = []
    course_t = db.table('Course')
    ctext_t = {lang: db.table(f'Course_Text_{lang}') for lang in LANGS}
    prog_t = db.table('MainGame_Story_Progress')
    first_course = len(course_t.rows)
    last_vanilla = max((r for r in course_t.rows if not r['_empty']), key=lambda r: r['_order'])
    lines = []
    for k, (name, prefix, title, ids) in enumerate(courses):
        cid = first_course + k
        first = len(group.rows)
        for sid in ids:
            i = len(group.rows)
            group.rows.append({'_id': i, 'StageID': row_of[sid], 'NextStage': [0, 0], 'StageListID': 0, 'OverrideCourseID': 0,
                               '_empty': 0, '_order': i})
        lines.append(f'{LIST_BASE + k} {first} {len(ids)}')
        world = WORLD_OF_BG.get(mania.stages[ids[0]]['bg'], 1)
        look = course_t.row(world)
        course_t.use(cid, Name=cid, StageListID=LIST_BASE + k, CategoryID=COURSE_CATEGORY,
                     NextCourseID=cid + 1 if k + 1 < len(courses) else 0, PrevCourseID=0, SerialName=cid,
                     ThumbnailSpriteID=look['ThumbnailSpriteID'], CaptionText=cid, AdventureTimerText=cid,
                     BeginningTitle=list(look['BeginningTitle']), ClearMainMissionID=0, BrochureSpriteID=look['BrochureSpriteID'],
                     AssistKind=2, IsEnabledCategory=[False, True, False, False, False, False, False], IsStageMissionEnabled=False,
                     IconSpriteID=0)
        for lang, t in ctext_t.items():
            t.use(cid, Name=title, SerialName=prefix, CaptionText=t.row(1)['CaptionText'], AdventureTimerText=title.upper())
        for i in range(len(ids)):
            prog_t.use(len(prog_t.rows), CourseID=cid, IsDefaultOpen=True, UnlockProgress=[0, 0], StageIndex=i, MovieIDPrologue=0,
                       MovieIDEpilogue=0)
    if courses:
        last_vanilla['NextCourseID'] = first_course
    written = db.save(out_switch)
    with open(os.path.join(out, 'mania_courses.txt'), 'w', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')

    # ---- catalog
    cat = Catalog(os.path.join(aa, 'catalog.json'))
    tmpl = cat.locations('bg_stg_w01_001')[0]
    deps = cat.buckets[tmpl['dep']]
    asm, cls, opts = cat.extra_json(cat.entries[deps[0]][4])
    prov_bundle, rt_bundle = cat.entries[deps[0]][1], cat.entries[deps[0]][6]
    for sid in stage_ids:
        rel = bundle_rel(sid)
        f = os.path.join(out, rel.replace('/', os.sep))
        name = str(scene_id(sid))
        o = dict(opts, m_Hash=md5('mania ' + name), m_Crc=0, m_BundleName=f'mania_scene_{name}', m_BundleSize=os.path.getsize(f))
        primary = rel[len('Switch/'):]
        depkey = 'mania-deps-' + name
        cat.add_entry(RT + '/' + rel, prov_bundle, None, cat.add_extra_json(asm, cls, o), primary, rt_bundle, [primary, depkey])
        cat.buckets[cat.add_key(depkey)] += deps[1:]
        cat.add_entry(f'Assets/Mania/{name}.unity', tmpl['prov'], depkey, -1, name, tmpl['rt'], [name])
    cat.save(os.path.join(out, 'catalog.json'))

    # what each stage has and what was left out, for whoever looks into a stage that plays wrong
    skipped = {}
    with open(os.path.join(out, 'import_report.txt'), 'w', encoding='utf-8') as f:
        for bundle, st in sorted(reports.items()):
            print(bundle, st, sep='\t', file=f)
            for k in st.get('skipped', {}):
                skipped[k] = skipped.get(k, 0) + 1
        for bundle, e in sorted(failed.items()):
            print(bundle, 'FAILED ' + e, sep='\t', file=f)
    if skipped:
        print('not converted (stages that have it): ' + ', '.join(f'{k} {n}' for k, n in sorted(skipped.items(), key=lambda x: -x[1])))
    print(f'imported {len(stage_ids)} stages in {len(courses)} courses ({len(failed)} stages failed), {len(written)} tables, '
          f'{int(time.time() - t0)} s -> {out}')
    for b, e in failed.items():
        print('  failed:', b, e)
    return 0


if __name__ == '__main__':
    sys.exit(main())
