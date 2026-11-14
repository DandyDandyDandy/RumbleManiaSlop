"""Banana Mania's stage and course tables.

They are MonoBehaviours without type trees in the player's own data file `smbbm_Data\\sharedassets0.assets`; the
class of each is found through the MonoScript objects of `globalgamemanagers.assets`. Field order is the class's
declaration order (from the game's Assembly-CSharp); every decoder here stops exactly at the end of its object.

    MgStageData     one entry per stage: id, prefab path, background name, kind, time limits, ...
    MgCourseDatum   one object per course: game kind, course name, text key, the ordered stage ids
    MgBgData        one entry per background: prefab paths, the BGM cue name
Stage names are in the bundle `text_common_<lang>`, asset `stagename_<lang>`.
"""
import os
import re
import struct

import UnityPy

from maniastage import BUNDLES

LANGS = ('de', 'en', 'es', 'fr', 'it', 'ja', 'ko', 'zh', 'zhs')


class _R:
    def __init__(self, b):
        self.b, self.p = b, 0

    def i32(self):
        v = struct.unpack_from('<i', self.b, self.p)[0]
        self.p += 4
        return v

    def flag(self):
        v = self.b[self.p]
        self.p = (self.p + 4) & ~3
        return v

    def text(self):
        n = self.i32()
        v = self.b[self.p:self.p + n].decode('utf-8', 'replace')
        self.p = (self.p + n + 3) & ~3
        return v

    def pptr(self):
        v = struct.unpack_from('<iq', self.b, self.p)
        self.p += 12
        return v

    def header(self):
        self.pptr(); self.flag(); self.pptr()
        return self.text()

    def done(self):
        return self.p == len(self.b)


class ManiaData:
    def __init__(self, game_dir):
        self.dir = game_dir
        data = os.path.join(game_dir, 'smbbm_Data')
        env = UnityPy.load(os.path.join(data, 'globalgamemanagers.assets'), os.path.join(data, 'sharedassets0.assets'))
        scripts, objs = {}, []
        for f in env.files.values():
            if f.name == 'globalgamemanagers.assets':
                for o in f.objects.values():
                    if o.type.name == 'MonoScript':
                        scripts[o.path_id] = o.read().m_ClassName
            else:
                objs += [o for o in f.objects.values() if o.type.name == 'MonoBehaviour']
        self.stages, self.courses, self.backgrounds = {}, {}, {}
        for o in objs:
            raw = bytes(o.get_raw_data())
            cls = scripts.get(struct.unpack_from('<q', raw, 20)[0])
            r = _R(raw)
            if cls == 'MgStageData':
                r.header()
                for _ in range(r.i32()):
                    e = {'id': r.i32(), 'prefab': r.text(), 'bg': r.text(), 'bgroot': r.text(), 'kind': r.text()}
                    e['limits'] = [r.i32() for _ in range(r.i32())]
                    e['light'], e['bgm'] = r.text(), r.text()
                    e['thumb'] = r.text()                   # 'UI/thumbnail/Common/t_tmb_st1001.tga'
                    for _ in range(3):                      # the guide assets
                        r.text()
                    e['anim_start'] = r.text()
                    e['anim_shift'] = r.i32()
                    self.stages[e['id']] = e
                assert r.done(), 'MgStageData layout'
            elif cls == 'MgCourseDatum':
                r.header()
                c = {'kind': r.text(), 'name': r.text()}
                r.pptr()
                c['text_key'] = r.text()
                c['thumb'] = r.text()                       # 'UI/thumbnail/Common/t_tmb_world_01.tga', or empty
                r.text(); r.text()
                c['next'] = r.text()
                c['stages'] = []
                for _ in range(r.i32()):
                    sid = r.i32(); r.i32(); r.flag(); r.flag()
                    for _ in range(r.i32()):
                        r.text(); r.i32()
                    c['stages'].append(sid)
                assert r.done(), 'MgCourseDatum layout'
                self.courses[c['name']] = c
            elif cls == 'MgBgData':
                r.header()
                for _ in range(r.i32()):
                    e = {'bg': r.text(), 'prefab': r.text(), 'light': r.text(), 'light_scene': r.text(), 'bgm': r.text()}
                    r.text(); r.flag(); r.text(); r.text(); r.text()
                    self.backgrounds[e['bg']] = e
                assert r.done(), 'MgBgData layout'
        if not self.stages or not self.courses:
            raise ValueError(f'{data}: the stage and course tables were not found (another version of the game?)')
        self.bundles = {}
        for n in os.listdir(os.path.join(game_dir, BUNDLES)):
            m = re.match(r'stage_smb\d_\w+?_st(\d+)$', n)
            if m:
                self.bundles[int(m.group(1))] = n
        self._texts = {}

    def texts(self, lang, asset):
        """{key: text} of a text asset (`stagename`, `maingame`, ...) of the bundle text_common_<lang>."""
        key = (lang, asset)
        if key not in self._texts:
            out = {}
            path = os.path.join(self.dir, BUNDLES, f'text_common_{lang}')
            if os.path.exists(path):
                env = UnityPy.load(path)
                for k, o in env.container.items():
                    if k.endswith(f'/{asset}_{lang}.asset'):
                        for d in o.read_typetree()['m_TextDictionary']['list']:
                            out[d['Key']] = d['Value']['m_Text']
            self._texts[key] = out
        return self._texts[key]

    def stage_name(self, stage_id, lang='en'):
        t = self.texts(lang, 'stagename').get(f'stagename_st{stage_id}')
        return t if t else (self.texts('en', 'stagename').get(f'stagename_st{stage_id}') or f'Stage {stage_id}')

    def bgm_cue(self, stage_id):
        """The stage's BGM as Mania names it: '<cue sheet>_<cue>', e.g. 'bgm_smb1_st1_st1'."""
        s = self.stages[stage_id]
        if s['bgm'] and s['bgm'].lower() != 'invalid':
            return s['bgm']
        return self.backgrounds.get(s['bg'], {}).get('bgm', '')

    def time_limit(self, stage_id):
        """Seconds. Stages without their own limit have the game's default of 60; the list is per game mode, the
        second entry being Challenge mode."""
        lim = self.stages[stage_id]['limits']
        if len(lim) > 2 and lim[2] > 0:
            return float(lim[2])
        return 60.0
