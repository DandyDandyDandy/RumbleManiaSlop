"""Import Banana Mania into the built game: makes the override folder game\\mania\\.

    python build.py <Banana Mania folder> [--no-levels] [--no-classic] [--no-music]
                    [--only COURSE[,COURSE...]] [--jobs N] [--no-stages] [--no-backgrounds] [--bg-option KEY=VALUE ...]

Two things are imported, each optional: the stages with their music (as extra Adventure courses) and the
classic-style monkeys of the Classic Character Pack (as the "Classic Outfit" in the Style menu; classic\\).

What it writes (the game's own files are never changed; deleting game\\mania\\ undoes everything):

    mania\\Switch\\mania\\scene_<n>.bundle     one converted stage scene each (stage.py)
    mania\\Switch\\mania\\bg_<n>.bundle        per Mania background its scenery (200000 + n) and its lighting scene
                                            (210000 + n) (background.py)
    mania\\Switch\\mania\\thumb_<name>.bundle  Banana Mania's thumbnail of each stage and course as a Rumble sprite
                                            (sprites.py)
    mania\\Switch\\...                        changed copies of the game's table bundles (dbtable.py)
    mania\\catalog.json                      the game's Addressables catalog plus the new scenes
    mania\\mania_courses.txt                 per imported course: its stage list id, first row and length in the real list, and
                                            its course id; "bgroot <stage row>
                                            <position> <rotation> <scale>" per stage that places its background
                                            elsewhere; "own <id> <previous id>"
                                            for the game's Adventure worlds
                                            (read by port\\runtime\\mania.c)
    mania\\mania_music.txt                   per stage row: its BGM cue row, and the Classic Soundtrack's cue row (0: none)
    mania\\mania_stages.txt                  course number, stage number, Mania stage, course name, stage name
    mania\\Sound\\*.acb, *.awb               Banana Mania's stage music (CRIWARE cue sheets, copied as they are), and
                                            its title music as mania_adv.acb / .awb (the title screen plays it)
    mania\\Switch\\ui_assets_ui\\...           the title screen's bundles with the pictures of mania\\title\\ (title.py)
    mania\\Switch\\scene_mainmenu3d_night..., db_assets_db\\mainmenu_environment...
                                            the main menu always at night, under the starry sky of mania\\menu_sky\\
                                            (menu_sky.py)
    mania\\mania_music.txt                   the BGM cue of each imported stage

How the stages become courses (docs/MANIA.md has the reasons):

    Stage                   a new row per imported stage; its scene name is the number 100000 + Mania stage id
    Stage_Text_<lang>       the stage's name
    Stage_DoleDisposition   a row per new stage that names no logo (the sponsor logo under the start; the game reads
                            the row without a check)
    Stage_List_Group_wld97_wldtst   the unused test list 12: the stages of every imported course, one after the other
    Course, Course_Text_<lang>      a row per imported course, with a virtual stage list id 1000 + n
    MainGame_Story_Progress         a row per (course, stage) that opens the stage from the start
    Sound_CueSheet, Sound_Cue       a row per copied cue sheet and per stage BGM cue

Banana Mania's bonus stages (stage kind Bonus: collect bananas against the clock) are not imported: the imported
worlds are about reaching the goal and clear times.

What the import cannot know is read from mania\\overrides.json (overrides.py; written by the editor, editor.py):
each stage's Golden Banana and mission values, each world's graphics. A stage whose Golden Banana changed is
converted again even with --no-stages.

A stage whose picture was taken "From the view" in the editor gets its picture from the game itself: the import
starts the game and photographs the stage from that point of view (thumbshot.py; about a minute and a quarter per
new view, three copies of the game at a time, --no-views leaves it out, --retake takes all of them again). With --no-stages and an import already in
the game this happens first; otherwise after the import, which then runs its table part once more.
"""
import argparse
import hashlib
import os
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port'))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port', 'assets'))

import overrides  # noqa: E402
import thumbshot  # noqa: E402
import paths  # noqa: E402
from aacatalog import Catalog  # noqa: E402
from dbtable import LANGS, Database  # noqa: E402
from maniadata import ManiaData  # noqa: E402

RT = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}'
SCENE_BASE = 100000             # scene id of a stage = SCENE_BASE + Mania stage id
LIST_BASE = 1000                # virtual stage list id of imported course n = LIST_BASE + n
REAL_LIST_TABLE = 'Stage_List_Group_wld97_wldtst'
COURSE_CATEGORY = 6             # Course.Category the imported courses are listed under
TAB_NAME = 'Mania'              # the tab of Select World that holds the imported courses
TEMPLATE_STAGE_ROW = 8          # World 1 Stage 1: the model for new stage rows

# (Mania course, numbering prefix, name; None = the course's own name in Mania's text)
COURSES = [
    ('Smb1Org_Shokyu', 'SMB1 B', 'SMB1 Beginner'), ('Smb1Org_Chukyu', 'SMB1 A', 'SMB1 Advanced'),
    ('Smb1Org_Jyokyu', 'SMB1 E', 'SMB1 Expert'), ('Smb1Org_JyokyuEx2', 'SMB1 M', 'SMB1 Master'),
] + [(f'Smb2_StoryWorld{i:02d}', f'SMB2 W{i}', None) for i in range(1, 11)] + [
    ('Smb2Org_Shokyu', 'SMB2 B', 'SMB2 Beginner'), ('Smb2Org_Chukyu', 'SMB2 A', 'SMB2 Advanced'),
    ('Smb2Org_Jyokyu', 'SMB2 E', 'SMB2 Expert'), ('Smb2Org_Master', 'SMB2 M', 'SMB2 Master'),
    ('SmbDx', 'DX', None), ('SpecialOriginal', 'ORG', None), ('SpecialReverse', 'REV', None),
]
# Stages in none of these courses are not imported: they were a "More Stages" course of leftover and reused stages
# until 2026-11-16 (the user's wish to drop it)
# Mania's Extra courses are not worlds of their own: their stages follow the stages of the course they belong to
# (the user's wish, 2026-11-15)
EXTRAS = {'Smb1Org_Shokyu': 'Smb1Org_ShokyuEx', 'Smb1Org_Chukyu': 'Smb1Org_ChukyuEx', 'Smb1Org_Jyokyu': 'Smb1Org_JyokyuEx',
          'Smb2Org_Shokyu': 'Smb2Org_ShokyuEx', 'Smb2Org_Chukyu': 'Smb2Org_ChukyuEx', 'Smb2Org_Jyokyu': 'Smb2Org_JyokyuEx',
          'Smb2Org_Master': 'Smb2Org_MasterEx'}
# Mania background -> the Rumble world that stands in for it: the look of the course in the world picker, the intro
# graphics, without imported music the BGM, and without imported backgrounds (--no-backgrounds, or one that failed
# to convert) the scenery, sky and lighting of the stage
WORLD_OF_BG = {
    'Smb1_Jungle': 1, 'Smb1_Water': 2, 'Smb1_Night': 6, 'Smb1_Sunset': 4, 'Smb1_Space': 10, 'Smb1_Sands': 5, 'Smb1_Ice': 7,
    'Smb1_Storm': 8, 'Smb1_Masters': 9,
    'Smb2_Jungle': 1, 'Smb2_Lava': 4, 'Smb2_Water': 2, 'Smb2_Whale': 3, 'Smb2_Park': 5, 'Smb2_Pot': 8, 'Smb2_Bubble': 7,
    'Smb2_Gear': 9, 'Smb2_Space': 10, 'Smb2_Electric': 6,
}
# Mania's courses without a thumbnail of their own -> the course whose thumbnail they show
THUMB_COURSE = {'Smb1Org_Shokyu': 'Smb1_Casual', 'Smb1Org_ShokyuEx': 'Smb1_Casual', 'Smb1Org_Chukyu': 'Smb1_Normal',
                'Smb1Org_ChukyuEx': 'Smb1_Normal', 'Smb1Org_Jyokyu': 'Smb1_Expert', 'Smb1Org_JyokyuEx': 'Smb1_Expert',
                'Smb1Org_JyokyuEx2': 'Smb1_Master', 'Smb2Org_Shokyu': 'Smb2_Casual', 'Smb2Org_ShokyuEx': 'Smb2_Casual',
                'Smb2Org_Chukyu': 'Smb2_Normal', 'Smb2Org_ChukyuEx': 'Smb2_Normal', 'Smb2Org_Jyokyu': 'Smb2_Expert',
                'Smb2Org_JyokyuEx': 'Smb2_Expert', 'Smb2Org_Master': 'Smb2_Master', 'Smb2Org_MasterEx': 'Smb2_Master'}
SCENERY_FIELDS = ('LightSceneID', 'FarSceneID', 'SkySceneID', 'EffectSceneID', 'ScreenEffectAssetRef', 'LightSceneSplitScrenID',
                  'FarSceneSplitScreenID', 'SkySceneSplitScreenID', 'EffectSceneSplitScreenID', 'ScreenEffectSplitScreenAssetRef',
                  'MiniMapImageID')
MANIA_LANG = {'es419': 'es', 'ptbr': 'en'}      # Rumble languages Mania has no text for
TITLE_SHEET = 'mania_adv'       # Banana Mania's title music (its adv cue sheet) under a name of its own
TITLE_CUES = {1: 'adv', 2: 'adv_e'}             # Rumble's title cue rows -> the cue of Mania's sheet


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def scene_id(stage_id):
    return SCENE_BASE + stage_id


def bundle_rel(stage_id):
    return f'Switch/mania/scene_{scene_id(stage_id)}.bundle'


def course_thumb(mania, name):
    """The path of the Mania thumbnail of an imported course ('' when Mania has none for it)."""
    for n in (name, THUMB_COURSE.get(name)):
        c = mania.courses.get(n)
        if c and c.get('thumb'):
            return c['thumb']
    return ''


def default_world(mania, stage_ids):
    """The Rumble world an imported course borrows its graphics from when nobody chose one."""
    return WORLD_OF_BG.get(mania.stages[stage_ids[0]]['bg'], 1)


def _convert(job):
    mania_dir, aa_switch, bundle, out, identity, gold = job
    from stage import Converter
    global _CONV
    try:
        conv = _CONV
    except NameError:
        conv = _CONV = Converter(mania_dir, aa_switch)
    try:
        return bundle, conv.convert(bundle, out, identity, gold=gold), None
    except Exception as e:                      # one broken stage must not stop the import
        import traceback
        return bundle, None, f'{type(e).__name__}: {e} | {traceback.format_exc(limit=3).splitlines()[-2].strip()}'


def _convert_bg(job):
    mania_dir, aa_switch, name, out, tunables = job
    from background import BackgroundConverter
    try:
        return name, BackgroundConverter(mania_dir, aa_switch).convert(name, out, **tunables), None
    except Exception as e:                      # the stages of a broken background keep a Rumble world's scenery
        import traceback
        return name, None, f'{type(e).__name__}: {e} | {traceback.format_exc(limit=3).splitlines()[-2].strip()}'


def plan_courses(mania, only=None):
    """[(Mania course name, prefix, display name, [stage ids])] in import order. Bonus stages are left out; an Extra
    course's stages are appended to its main course (EXTRAS)."""
    out, used = [], set()
    if only:
        base_of = {e: b for b, e in EXTRAS.items()}
        only = {base_of.get(n, n) for n in only}

    def wanted(i):
        return i in mania.stages and i in mania.bundles and mania.stages[i]['kind'] != 'Bonus'

    for name, prefix, title in COURSES:
        c = mania.courses.get(name)
        if c is None:
            continue
        ids = [i for i in c['stages'] if wanted(i)]
        ex = mania.courses.get(EXTRAS.get(name))
        if ex is not None:
            ids += [i for i in ex['stages'] if wanted(i) and i not in ids]
        title = title or mania.texts('en', 'maingame').get(c['text_key']) or name
        if name.startswith('Smb2_StoryWorld'):
            title = f'SMB2 {title}'
        if only and name not in only:
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
    ap.add_argument('--no-levels', action='store_true', help='do not import the stages')
    ap.add_argument('--no-classic', action='store_true', help='do not import the classic characters')
    ap.add_argument('--no-music', action='store_true', help='leave the stages with the music of the Rumble world they borrow')
    ap.add_argument('--no-backgrounds', action='store_true',
                    help='leave the stages with the scenery, sky and lighting of the Rumble world they borrow')
    ap.add_argument('--bg-option', action='append', default=[], metavar='KEY=VALUE',
                    help='a tunable of background.py in lower case, the value as JSON (for testing): --bg-option light_exposure=0.5')
    ap.add_argument('--no-views', action='store_true',
                    help='do not start the game to take the stage pictures of the editor\'s views (they keep the editor\'s picture)')
    ap.add_argument('--retake', action='store_true', help='take the stage pictures of all views again')
    a = ap.parse_args()
    game = a.game
    aa = os.path.join(game, f'{paths.NAME}_Data', 'StreamingAssets', 'aa')
    aa_switch = os.path.join(aa, 'Switch')
    out = os.path.join(game, 'mania')
    out_switch = os.path.join(out, 'Switch')
    os.makedirs(os.path.join(out_switch, 'mania'), exist_ok=True)
    t0 = time.time()

    mania = ManiaData(a.mania)
    courses = [] if a.no_levels else plan_courses(mania, set(a.only.split(',')) if a.only else None)
    stage_ids = []
    for _, _, _, ids in courses:
        stage_ids += [i for i in ids if i not in stage_ids]
    print(f'{len(courses)} courses, {len(stage_ids)} stages', flush=True)

    # what the tables and the catalog need to know about a converted stage (the stages of the game whose bundles it
    # uses, its areas, what its bananas are worth, its Golden Banana): kept in a file, because --no-stages leaves
    # the stage bundles of an earlier import in place
    import json
    ov = overrides.load()
    extras_path, extras = os.path.join(out, 'stage_extras.json'), {}
    if os.path.exists(extras_path):
        with open(extras_path, encoding='utf-8') as f:
            extras = {int(k): v for k, v in json.load(f).items()}

    def fits(sid):
        """Whether the stage's bundle of an earlier import is what this import would make."""
        e = extras.get(sid)
        return (os.path.exists(os.path.join(out, bundle_rel(sid).replace('/', os.sep))) and e is not None and 'banana_count' in e
                and e.get('gold') == overrides.gold(ov, sid))

    # ---- stage pictures from the game, of the stages that are in the game as this import would make them
    views = {sid: ov['stages'][str(sid)]['view'] for sid in stage_ids if ov['stages'].get(str(sid), {}).get('view')}
    if a.retake:
        for sid, v in views.items():
            if os.path.exists(thumbshot.kept(sid, v)):
                os.remove(thumbshot.kept(sid, v))
    tried = set()
    if views and not a.no_views and a.no_stages:
        ready = {sid: v for sid, v in views.items() if fits(sid) and not os.path.exists(thumbshot.kept(sid, v))}
        tried = set(ready)
        thumbshot.take_all(ready, game=game)

    # ---- stage scenes
    failed, reports = {}, {}
    todo = [sid for sid in stage_ids if not (a.no_stages and fits(sid))]
    if todo:
        jobs = []
        for sid in todo:
            ident = (f'mania_scene_{scene_id(sid)}', f'Assets/Mania/{scene_id(sid)}.unity', 'CAB-' + md5(f'mania scene {sid}'))
            jobs.append((a.mania, aa_switch, mania.bundles[sid], os.path.join(out, bundle_rel(sid).replace('/', os.sep)), ident,
                         overrides.gold(ov, sid)))
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
    # files of an earlier import that are not part of this one (the bonus stages and their two backgrounds, which
    # older versions imported)
    if not a.only and not a.no_levels:
        keep = {os.path.basename(bundle_rel(i)) for i in stage_ids}
        for name in os.listdir(os.path.join(out_switch, 'mania')):
            if name.startswith('scene_') and name not in keep or name.startswith(('bg_', 'thumb_')):
                os.remove(os.path.join(out_switch, 'mania', name))
    stage_ids = [i for i in stage_ids if os.path.exists(os.path.join(out, bundle_rel(i).replace('/', os.sep)))]
    sid_of = {mania.bundles[i]: i for i in stage_ids}
    for bundle, st in reports.items():
        if bundle in sid_of:
            sid = sid_of[bundle]
            extras[sid] = {'donor_stages': st.get('donor_stages', []), 'areas': st.get('areas', []), 'intro': st.get('intro'),
                           'banana_count': st.get('banana_count', 0), 'gold': overrides.gold(ov, sid)}
            if overrides.gold(ov, sid) and not st.get('gold'):
                print(f'  st{sid}: overrides.json names a Golden Banana the stage does not have ({overrides.gold(ov, sid)})', flush=True)
    extras = {i: extras[i] for i in stage_ids if i in extras}
    with open(extras_path, 'w', encoding='utf-8', newline='\n') as f:
        json.dump(extras, f, indent=0, sort_keys=True)
    courses = [(n, p, t, [i for i in ids if i in stage_ids]) for n, p, t, ids in courses]
    courses = [c for c in courses if c[3]]

    # ---- backgrounds: scenery and lighting scenes of the Mania backgrounds the stages use (always redone: seconds)
    backgrounds, bg_failed = {}, {}
    if stage_ids and not a.no_backgrounds:
        import json
        tunables = {}
        for kv in a.bg_option:
            k, _, v = kv.partition('=')
            try:
                tunables[k] = json.loads(v)
            except ValueError:
                tunables[k] = v
        names = sorted({mania.stages[i]['bg'] for i in stage_ids})
        with ProcessPoolExecutor(min(a.jobs, len(names))) as pool:
            for name, info, err in pool.map(_convert_bg, [(a.mania, aa_switch, n, out, tunables) for n in names]):
                if err:
                    bg_failed[name] = err
                    print(f'  FAILED background {name}: {err}', flush=True)
                else:
                    backgrounds[name] = info
        print(f'  {len(backgrounds)}/{len(names)} backgrounds converted', flush=True)

    written, music_lines, lines, sprites = [], [], [], None
    cat = Catalog(os.path.join(aa, 'catalog.json'))
    if courses:
        written, music_lines, lines, sprites = import_tables(a, mania, courses, stage_ids, aa, out, out_switch, backgrounds, extras,
                                                              ov, cat)
        add_scenes(cat, stage_ids, out, extras)
        from background import add_to_catalog
        for info in backgrounds.values():
            add_to_catalog(cat, info, out)
    with open(os.path.join(out, 'mania_courses.txt'), 'w', newline='\n') as f:
        f.write(''.join(x + '\n' for x in lines))
    with open(os.path.join(out, 'mania_music.txt'), 'w', newline='\n') as f:
        f.write(''.join(x + '\n' for x in music_lines))
    with open(os.path.join(out, 'mania_stages.txt'), 'w', encoding='utf-8', newline='\n') as f:     # for people and try_stage.py
        for ci, (_, _, title, ids) in enumerate(courses):
            for si, i in enumerate(ids):
                f.write(f'{ci}\t{si}\tst{i}\t{title}\t{mania.stage_name(i)}\n')

    # ---- classic characters
    classic = False
    if not a.no_classic:
        sys.path.insert(0, os.path.join(HERE, 'classic'))
        import classic_chara
        import classic_outfit
        if classic_chara.available(a.mania):
            print('classic characters:', flush=True)
            classic_outfit.configure(aa, a.mania, out, str(paths.BUILD / 'mania_work'))
            classic_outfit.build(cat)
            classic = True
        else:
            print('classic characters: this Banana Mania install has no Classic Character Pack; skipped')
    if sprites:         # after the Classic Outfit, which takes a row of the sprite table too (from the game's own table)
        from sprites import TABLE_REL
        sprites.write_table(out_switch, os.path.join(out_switch, TABLE_REL.replace('/', os.sep)) if classic else None)
    cat.save(os.path.join(out, 'catalog.json'))

    # ---- the fork's title screen (mania\title; title.py)
    import title
    title.apply(aa, out)
    # ---- the main menu at night under the stars (mania\menu_sky, overridden by input\menu_sky; menu_sky.py)
    import menu_sky
    menu_sky.apply(aa, out)

    # what each stage has and what was left out, for whoever looks into a stage that plays wrong
    skipped = {}
    with open(os.path.join(out, 'import_report.txt'), 'w', encoding='utf-8') as f:
        for bundle, st in sorted(reports.items()):
            print(bundle, st, sep='\t', file=f)
            for k in st.get('skipped', {}):
                skipped[k] = skipped.get(k, 0) + 1
        for bundle, e in sorted(failed.items()):
            print(bundle, 'FAILED ' + e, sep='\t', file=f)
        for name, info in sorted(backgrounds.items()):
            print('background ' + name, info, sep='\t', file=f)
        for name, e in sorted(bg_failed.items()):
            print('background ' + name, 'FAILED ' + e, sep='\t', file=f)
    if skipped:
        print('not converted (stages that have it): ' + ', '.join(f'{k} {n}' for k, n in sorted(skipped.items(), key=lambda x: -x[1])))
    print(f'imported {len(stage_ids)} stages in {len(courses)} courses ({len(failed)} stages failed), {len(backgrounds)} backgrounds'
          f'{f" ({len(bg_failed)} failed)" if bg_failed else ""}, {len(written)} tables, {int(time.time() - t0)} s -> {out}')
    for b, e in failed.items():
        print('  failed:', b, e)
    # ---- stage pictures from the game of stages that were not in the game before this import
    late = {sid: v for sid, v in views.items() if sid in stage_ids and sid not in tried}
    if not a.no_views and thumbshot.take_all(late, game=game):
        import subprocess
        print('The new pictures go into the game:', flush=True)
        return subprocess.call([sys.executable, '-u', os.path.abspath(__file__), *sys.argv[1:], '--no-stages', '--no-views'])
    return 0


def own_picture(entry, key):
    """(name for the sprite, picture) of the mod's picture an entry of the overrides names, or None. The name
    holds a hash of the picture and its use, so another picture is another asset to the game."""
    img = overrides.picture(entry, key)
    if img is None:
        if entry.get(key):
            print(f'  picture {entry[key]} is not in mania\\pictures: passed over', flush=True)
        return None
    return 'user_' + hashlib.md5(img.tobytes() + f'{img.size} {key}'.encode()).hexdigest()[:12], overrides.fit_picture(img, key)


def keep_render(entry, img):
    """The game's render of a stage's view becomes the mod's picture of the stage (the file its entry names), when it
    differs from it: the picture committed with the fork follows what the editor's author sees in the game."""
    name = entry.get('picture')
    if not name or not overrides.PICTURE_NAME.fullmatch(name):
        return
    old = overrides.picture(entry, 'picture')
    from PIL import ImageChops, ImageStat
    if old is not None and old.size == img.size:
        if sum(ImageStat.Stat(ImageChops.difference(old.convert('RGB'), img.convert('RGB'))).mean) / 3 < 4:
            return                                      # the same picture (a JPEG copy of it differs by about 3)
    overrides.save_picture(img, name)


def view_picture(sid, entry):
    """(name for the sprite, picture) of the picture the game took of the stage from the view its entry of the
    overrides names (thumbshot.py), or None: no view, or not taken yet."""
    view = entry.get('view')
    path = thumbshot.kept(sid, view) if view else None
    if not path or not os.path.exists(path):
        return None
    from PIL import Image
    with Image.open(path) as f:
        img = f.convert('RGB')
    return 'view_' + hashlib.md5(img.tobytes()).hexdigest()[:12], overrides.fit_picture(img, 'picture')


def import_tables(a, mania, courses, stage_ids, aa, out, out_switch, backgrounds, extras, ov, cat):
    """The table rows, the pictures and the music of the imported courses; returns (tables written, music lines,
    course lines, the Sprites object with the new pictures).
    backgrounds: {Mania background name: what background.py's convert returned} of the converted backgrounds;
    extras: {stage id: {'areas': [[kind, x, y, z, radius]], 'banana_count': n, ...}} from the stage converter;
    ov: the overrides (overrides.py); cat: the catalog, which gets the new pictures."""
    from background import stage_fields
    from sprites import ManiaThumbnails, Sprites
    aa_switch = os.path.join(aa, 'Switch')
    db = Database(aa_switch, cache=str(paths.BUILD / 'mania_table_index.json'))
    sprites, thumbs = Sprites(aa, cat, db), ManiaThumbnails(a.mania)
    with_missions = {i for name, _, _, ids in courses if overrides.has_missions(ov, name, ids) for i in ids}
    stage_t = db.table('Stage')
    model = dict(stage_t.row(TEMPLATE_STAGE_ROW))
    scenery = {}
    for w in range(1, 11):
        row = next((r for r in stage_t.rows if not r['_empty'] and r['SceneID'].startswith(f'bg_stg_w{w:02d}_0')), None)
        scenery[w] = {f: row[f] for f in SCENERY_FIELDS} if row else {f: model[f] for f in SCENERY_FIELDS}
    dole_t = db.table('Stage_DoleDisposition')
    dole_model = dict(next((r for r in dole_t.rows if not r['_empty'] and not r['AssetRef'][0]), dole_t.row(TEMPLATE_STAGE_ROW)))
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
        if st['bg'] in backgrounds:
            fields.update(stage_fields(backgrounds[st['bg']]))
        # the picture in Select Stage: the game's own render of the editor's view, else the mod's picture
        # (mania\pictures, overrides.json), else Banana Mania's thumbnail of the stage (0 = "no image"). A render is
        # copied over the mod's picture, so the committed picture is what this game shows and every copy gets it.
        entry = ov['stages'].get(str(sid), {})
        picture = view_picture(sid, entry)
        if picture:
            keep_render(entry, picture[1])
        picture = picture or own_picture(entry, 'picture')
        if picture:
            thumb = sprites.add(*picture, out)
        else:
            picture = thumbs.square(st.get('thumb'))
            thumb = sprites.add(f'st{sid}', picture, out) if picture else 0
        fields.update(Name=rid, SceneID=str(scene_id(sid)), TimeLimit=mania.time_limit(sid), CaptionText=rid, ThumbnailSpriteID=thumb,
                      MiniThumbnailSpriteID=thumb, MissionPoint=0, MissionPointMaster=0, MissionBanana=0, CheckpointStageAnimationFrame=0,
                      CheckpointSwitchClass=-1, CheckpointSwitchAnimationSpeed=0, CheckpointSwitchAnimationFrame=0, AnimationType=0,
                      AnimationSpeedMultiplier=0.0)
        # Rumble's stage missions for the stages of a course that has them (overrides.json): of the three only the
        # Golden Banana; the port hides the time and banana missions on imported stages (mania.c), so they have no
        # values. The points are those of the game's own stages.
        fields.update(MissionTime=0.0, MissionTimeMaster=0.0)
        if sid in with_missions:
            fields.update(MissionPoint=model['MissionPoint'], MissionPointMaster=model['MissionPointMaster'])
        stage_t.use(rid, **fields)
        # no sponsor logo under the start: a row as the game's own stages without one have it (the game reads the
        # row without a check, so there must be one)
        dole_t.use(rid, **dict({k: v for k, v in dole_model.items() if not k.startswith('_')}, AssetRef=['', '', ''], Num=0))
        for lang, t in text_t.items():
            caption = t.row(TEMPLATE_STAGE_ROW)['CaptionText']
            t.use(rid, Name=mania.stage_name(sid, MANIA_LANG.get(lang, lang)), CaptionText=caption)

    group = db.table(REAL_LIST_TABLE)
    group.rows = []
    course_t = db.table('Course')
    ctext_t = {lang: db.table(f'Course_Text_{lang}') for lang in LANGS}
    prog_t = db.table('MainGame_Story_Progress')
    first_course = len(course_t.rows)
    # The world picker of co-op and online rooms walks Course.NextCourseID from the first Adventure world
    # (Util.Stage.GetAdvFirstStageID: first in display order, category 1, 4 or 6, enabled for category 1, no
    # previous course) to the end; the imported courses are hung on the end of that chain (the last Ultimate EX
    # world), not on the last row of the table, which is the No Miss Challenge and belongs to no chain.
    own = sorted((r for r in course_t.rows if not r['_empty']), key=lambda r: r['_order'])
    by_id = {r['_id']: r for r in own}
    last_vanilla = next((r for r in own if r['CategoryID'] in (1, 4, 6) and r['IsEnabledCategory'][1] and not r['PrevCourseID']), None)
    seen = set()
    while last_vanilla is not None and last_vanilla['NextCourseID'] in by_id and last_vanilla['_id'] not in seen:
        seen.add(last_vanilla['_id'])
        last_vanilla = by_id[last_vanilla['NextCourseID']]
    lines = []
    for k, (name, prefix, title, ids) in enumerate(courses):
        cid = first_course + k
        first = len(group.rows)
        for sid in ids:
            i = len(group.rows)
            group.rows.append({'_id': i, 'StageID': row_of[sid], 'NextStage': [0, 0], 'StageListID': 0, 'OverrideCourseID': 0,
                               '_empty': 0, '_order': i})
        lines.append(f'{LIST_BASE + k} {first} {len(ids)} {cid}')
        # The course's graphics are a Rumble world's (overrides.json; without a choice the world that stands in for
        # the first stage's background): the picture beside the list, the title card of a loading stage, and when
        # asked for the world icon. Its small picture is Banana Mania's thumbnail of the course when there is one.
        co = ov['courses'].get(name, {})

        def look(key, default):
            r = by_id.get(co.get(key, default))
            return r if r is not None and r['_id'] < first_course else None

        theme = look('theme', None) or by_id[default_world(mania, ids)]
        brochure, icon, card = look('brochure', theme['_id']) or theme, look('icon', 0), look('title', theme['_id'])
        small = co.get('thumbnail', 'mania')
        picture = thumbs.square(course_thumb(mania, name)) if small == 'mania' else None
        mine = {key: own_picture(co, key) for key in ('picture', 'big_picture', 'icon_picture')}
        if mine['picture']:
            small = sprites.add(*mine['picture'], out)
        elif picture:
            small = sprites.add('course_' + ''.join(ch if ch.isalnum() else '_' for ch in name), picture, out)
        else:
            small = (look('thumbnail', None) or theme)['ThumbnailSpriteID']
        # the user's big picture and icon: copies of World 1's, which give them size and format
        big, icon_id = brochure['BrochureSpriteID'], icon['IconSpriteID'] if icon else 0
        if mine['big_picture']:
            big = sprites.add(*mine['big_picture'], out, template=by_id[1]['BrochureSpriteID'])
        if mine['icon_picture']:
            icon_id = sprites.add(*mine['icon_picture'], out, template=by_id[1]['IconSpriteID'])
        course_t.use(cid, Name=cid, StageListID=LIST_BASE + k, CategoryID=COURSE_CATEGORY,
                     NextCourseID=cid + 1 if k + 1 < len(courses) else 0, PrevCourseID=0, SerialName=cid,
                     ThumbnailSpriteID=small, CaptionText=cid, AdventureTimerText=cid,
                     BeginningTitle=list(card['BeginningTitle']) if card else ['', '', ''], ClearMainMissionID=0,
                     BrochureSpriteID=big, AssistKind=2,
                     IsEnabledCategory=[False, True, False, False, False, False, False],
                     IsStageMissionEnabled=overrides.has_missions(ov, name, ids), IconSpriteID=icon_id)
        for lang, t in ctext_t.items():
            t.use(cid, Name=title, SerialName=prefix, CaptionText=t.row(1)['CaptionText'], AdventureTimerText=title.upper())
        for i in range(len(ids)):
            prog_t.use(len(prog_t.rows), CourseID=cid, IsDefaultOpen=True, UnlockProgress=[0, 0], StageIndex=i, MovieIDPrologue=0,
                       MovieIDEpilogue=0)
    if courses and last_vanilla is not None:
        last_vanilla['NextCourseID'] = first_course
    # A tab of their own in Select World, after Story and Special. The tabs are the rows of MainGame_Adventure_Type;
    # a row's name is an array indexed by the category of the focused course. The game fills a tab with the
    # MainGame_Category rows of its type and has none for this one: the port moves the imported courses from the
    # Story tab into it ("tab" line, mania.c).
    if courses:
        type_t = db.table('MainGame_Adventure_Type')
        tab_id = len(type_t.rows)
        type_t.use(tab_id, DisplayName=tab_id)
        for lang in LANGS:
            t = db.table(f'MainGame_Adventure_Type_Text_{lang}')
            t.use(tab_id, DisplayName=[TAB_NAME] * len(t.row(1)['DisplayName']))
        lines.append(f'tab {tab_id}')
    # stages whose Mania original places the background elsewhere (BgRoot): the port moves the scenery's root
    for info in backgrounds.values():
        for sid, p in sorted((info.get('moved_stages') or {}).items()):
            if sid in row_of:
                pos = [a + b for a, b in zip(p['root'], p.get('pos', [0, 0, 0]))]
                nums = pos + list(p.get('rot', [0, 0, 0, 1])) + list(p.get('scale', [1, 1, 1]))
                lines.append(f'bgroot {row_of[sid]} ' + ' '.join(f'{x:g}' for x in nums))
    # areas of a stage in which a goal does not count or a wormhole does not take the ball (stage.py): the port
    # applies them
    for sid in stage_ids:
        for kind, x, y, z, radius in extras.get(sid, {}).get('areas', []):
            lines.append(f'area {row_of[sid]} {kind} {x:g} {y:g} {z:g} {radius:g}')
    # Banana Mania's intro camera of a stage (stage.py mania_intro): the port flies it (mania_intro.c)
    for sid in stage_ids:
        intro = extras.get(sid, {}).get('intro')
        if intro:
            lines.append(f'intro {row_of[sid]} ' + ' '.join(f'{x:g}' for x in intro))
    # when a stage's motion starts in Mania (MgStageDatum: 1 OnInitialize = running through the intro, 2 OnReadyGo =
    # still until GO) and where it is at GO (frames of 1/60 s): the port follows it (mania_intro.c)
    for sid in stage_ids:
        s = mania.stages[sid]
        lines.append(f"anim {row_of[sid]} {2 if s.get('anim_start') == 'OnReadyGo' else 1} {s.get('anim_shift', 0)}")
    # the game's own Adventure worlds in display order with the world each one follows: the port works out the
    # "highest unlocked world" from these when the game's own answer is an imported course (mania.c)
    for r in own:
        if r['CategoryID'] in (1, 4, 6) and r['IsEnabledCategory'][1] and r['_id'] < first_course:
            lines.append(f"own {r['_id']} {r['PrevCourseID']}")

    # ---- music: Mania names a stage's BGM '<cue sheet>_<cue>'; the cue sheet is a pair of files in its Sound folder
    music_lines = []
    if not a.no_music:
        sound = os.path.join(a.mania, 'smbbm_Data', 'StreamingAssets', 'Sound')
        # The Classic Soundtrack add-on (the original games' music), when the install has it: for every cue sheet
        # <sheet> a sheet <sheet>_dx with the same cue names. Mania pairs them in code (Sound.GetDeluxeCue, the
        # option BGMMode Remake / Original); here every stage gets a second cue and the port's option chooses.
        classic = os.path.join(a.mania, 'smbbm_Data', 'StreamingAssets', 'DlcRoot', 'DlcDxOriginalBgm', 'Sound')
        sheet_t, cue_t = db.table('Sound_CueSheet'), db.table('Sound_Cue')
        sheets, cues, classic_cues = {}, {}, {}
        os.makedirs(os.path.join(out, 'Sound'), exist_ok=True)
        for sid in stage_ids:
            name = mania.bgm_cue(sid)
            if name not in cues:
                parts = name.split('_')
                sheet = next(('_'.join(parts[:i]) for i in range(len(parts) - 1, 0, -1)
                              if os.path.exists(os.path.join(sound, '_'.join(parts[:i]) + '.acb'))), None)
                if sheet is None:
                    cues[name] = None
                    continue
                if sheet not in sheets:
                    awb = os.path.exists(os.path.join(sound, sheet + '.awb'))
                    for ext in ('.acb', '.awb') if awb else ('.acb',):
                        shutil.copyfile(os.path.join(sound, sheet + ext), os.path.join(out, 'Sound', sheet + ext))
                    sheets[sheet] = len(sheet_t.rows)
                    sheet_t.use(sheets[sheet], acbPath=f'Sound/{sheet}.acb', awbPath=f'Sound/{sheet}.awb' if awb else '',
                                cueSheetName=sheet)
                cues[name] = len(cue_t.rows)
                cue_t.use(cues[name], cueSheet=sheets[sheet], innerCueName=name[len(sheet) + 1:], title=0, displayOrderInGallery=0,
                          innerCueId=0, ThumbnailSpriteID=0, IsEnabledTrial=False)
                dx = sheet + '_dx'
                if os.path.exists(os.path.join(classic, dx + '.acb')):
                    if dx not in sheets:
                        awb = os.path.exists(os.path.join(classic, dx + '.awb'))
                        for ext in ('.acb', '.awb') if awb else ('.acb',):
                            shutil.copyfile(os.path.join(classic, dx + ext), os.path.join(out, 'Sound', dx + ext))
                        sheets[dx] = len(sheet_t.rows)
                        sheet_t.use(sheets[dx], acbPath=f'Sound/{dx}.acb', awbPath=f'Sound/{dx}.awb' if awb else '', cueSheetName=dx)
                    classic_cues[name] = len(cue_t.rows)
                    cue_t.use(classic_cues[name], cueSheet=sheets[dx], innerCueName=name[len(sheet) + 1:], title=0,
                              displayOrderInGallery=0, innerCueId=0, ThumbnailSpriteID=0, IsEnabledTrial=False)
            if cues[name] is not None:
                music_lines.append(f'{row_of[sid]} {cues[name]} {classic_cues.get(name, 0)}')
        if classic_cues:
            print(f'Classic Soundtrack: {sum(1 for s in sheets if s.endswith("_dx"))} cue sheets, the original music is on offer')
        # The title screen plays Banana Mania's title music. Rumble's title prepares cue row 1 (sheet "adv", cue
        # "adv"; row 2 is its "adv_e"); Mania's title scene lists "adv_adv" and "adv_adv_e" (SelTitleSequence
        # m_BgmCueNameArray), the same cue names in its own adv sheet. That sheet is copied under another name,
        # because Rumble's adv sheet also holds the title call and must stay.
        if os.path.exists(os.path.join(sound, 'adv.acb')):
            awb = os.path.exists(os.path.join(sound, 'adv.awb'))
            for ext in ('.acb', '.awb') if awb else ('.acb',):
                shutil.copyfile(os.path.join(sound, 'adv' + ext), os.path.join(out, 'Sound', TITLE_SHEET + ext))
            sid_sheet = len(sheet_t.rows)
            sheet_t.use(sid_sheet, acbPath=f'Sound/{TITLE_SHEET}.acb', awbPath=f'Sound/{TITLE_SHEET}.awb' if awb else '',
                        cueSheetName=TITLE_SHEET)
            for row, cue in TITLE_CUES.items():
                cue_t.row(row).update(cueSheet=sid_sheet, innerCueName=cue)
            print("title music: Banana Mania's", flush=True)
    # ---- the user's postcards: loading screen tips of their own (overrides.json, postcards.py)
    import postcards
    n = postcards.add(db, sprites, ov, out, own_picture)
    if n:
        print(f'postcards: {n} of your own', flush=True)
    written = db.save(out_switch)
    return written, music_lines, lines, sprites


def add_scenes(cat, stage_ids, out, extras):
    """Catalog entries of the stage scenes: a bundle and a scene each, depending on what the template stage's scene
    depends on (the shader and material bundles the converted materials use), and on what the stages of the game
    depend on whose objects or materials the stage carries (extras[stage]['donor_stages']: a wormhole, a belt)."""
    tmpl = cat.locations('bg_stg_w01_001')[0]
    deps = cat.buckets[tmpl['dep']]
    donor_deps = {}
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
        more = []
        for donor in extras.get(sid, {}).get('donor_stages', []):
            if donor not in donor_deps:
                donor_deps[donor] = cat.buckets[cat.locations(donor)[0]['dep']][1:]
            more += [d for d in donor_deps[donor] if d not in deps and d not in more]
        cat.buckets[cat.add_key(depkey)] += deps[1:] + more
        cat.add_entry(f'Assets/Mania/{name}.unity', tmpl['prov'], depkey, -1, name, tmpl['rt'], [name])


if __name__ == '__main__':
    sys.exit(main())
