"""Read and write Banana Rumble's database tables.

A table is a MonoBehaviour without a type tree (`Wonder.DB.<Name>Object`), each in a bundle of its own:

    MonoBehaviour header (28 bytes), name string, int count, then per record:
        int id, the fields of the table's RawRecord class in declaration order, int empty flag, int display order

Strings are int length + UTF-8 bytes padded to four bytes; a bool is one byte padded to four; an array is an int
count and its elements (bools packed one byte each), padded to four; an AssetReference is three strings (GUID,
sub-object name, sub-object type). An unused id has empty = 1 and order = -1; the game lists records by order.

The field lists below were read from the game's IL2CPP metadata (class Wonder.DB.<...>.RawRecord). Type codes:
    u uint   i int / enum   f float   b bool   s string   a AssetReference   [x] array of x
"""
import copy
import json
import os
import struct

import UnityPy

LANGS = ('de', 'en', 'es', 'es419', 'fr', 'it', 'ja', 'ko', 'ptbr', 'zh', 'zhs')

SCHEMAS = {
    'Stage': [('Name', 'u'), ('SceneID', 's'), ('BaseID', 's'), ('BGSceneID', 's'), ('TimeLimit', 'f'), ('MissionPoint', 'i'),
              ('MissionPointMaster', 'i'), ('MissionTime', 'f'), ('MissionTimeMaster', 'f'), ('MissionBanana', 'i'),
              ('CaptionText', 'u'), ('ThumbnailSpriteID', 'i'), ('MiniThumbnailSpriteID', 'i'), ('LightSceneID', 's'),
              ('MiniMapImageID', 'i'), ('FarSceneID', 's'), ('SkySceneID', 's'), ('EffectSceneID', 's'),
              ('CheckpointStageAnimationFrame', 'i'), ('CheckpointSwitchClass', 'i'), ('CheckpointSwitchAnimationSpeed', 'i'),
              ('CheckpointSwitchAnimationFrame', 'i'), ('ScreenEffectAssetRef', 'a'), ('GoalCameraID', 'i'), ('IsRailGround', 'b'),
              ('StartCameraID', 'i'), ('LightSceneSplitScrenID', 's'), ('FarSceneSplitScreenID', 's'), ('SkySceneSplitScreenID', 's'),
              ('EffectSceneSplitScreenID', 's'), ('ScreenEffectSplitScreenAssetRef', 'a'), ('AnimationType', 'i'),
              ('AnimationSpeedMultiplier', 'f')],
    'Stage_Text': [('Name', 's'), ('CaptionText', 's')],
    'Stage_List_Group': [('StageID', 'i'), ('NextStage', '[i]'), ('StageListID', 'i'), ('OverrideCourseID', 'i')],
    'Stage_DoleDisposition': [('AssetRef', 'a'), ('StartOffsetX', '[f]'), ('StartOffsetY', '[f]'), ('StartOffsetZ', '[f]'),
                              ('StartScaleX', '[f]'), ('StartScaleY', '[f]'), ('StartScaleZ', '[f]'), ('Num', 'i')],
    'Course': [('Name', 'u'), ('StageListID', 'i'), ('CategoryID', 'i'), ('NextCourseID', 'i'), ('PrevCourseID', 'i'), ('SerialName', 'u'),
               ('ThumbnailSpriteID', 'i'), ('CaptionText', 'u'), ('AdventureTimerText', 'u'), ('BeginningTitle', 'a'),
               ('ClearMainMissionID', 'i'), ('BrochureSpriteID', 'i'), ('AssistKind', 'i'), ('IsEnabledCategory', '[b]'),
               ('IsStageMissionEnabled', 'b'), ('IconSpriteID', 'i')],
    'Course_Text': [('Name', 's'), ('SerialName', 's'), ('CaptionText', 's'), ('AdventureTimerText', 's')],
    'MainGame_Story_Progress': [('CourseID', 'i'), ('IsDefaultOpen', 'b'), ('UnlockProgress', '[i]'), ('StageIndex', 'i'),
                                ('MovieIDPrologue', 'i'), ('MovieIDEpilogue', 'i')],
    'MainGame_Adventure_Type_Text': [('DisplayName', '[s]')],
    'Sound_CueSheet': [('acbPath', 's'), ('awbPath', 's'), ('cueSheetName', 's')],
    'Sound_Cue': [('cueSheet', 'i'), ('innerCueName', 's'), ('title', 'u'), ('displayOrderInGallery', 'u'), ('innerCueId', 'i'),
                  ('ThumbnailSpriteID', 'i'), ('IsEnabledTrial', 'b')],
}


def schema_of(name):
    if name in SCHEMAS:
        return SCHEMAS[name]
    if '_Text_' in name:
        return SCHEMAS[name.split('_Text_')[0] + '_Text']
    if name.startswith('Stage_List_Group_'):
        return SCHEMAS['Stage_List_Group']
    raise KeyError(f'no schema for table {name}')


class _Rd:
    def __init__(self, b, p):
        self.b, self.p = b, p

    def align(self):
        self.p = (self.p + 3) & ~3

    def value(self, t):
        if t[0] == '[':
            self.align()
            n = struct.unpack_from('<i', self.b, self.p)[0]
            self.p += 4
            if t[1:-1] == 'b':
                v = [bool(x) for x in self.b[self.p:self.p + n]]
                self.p += n
            else:
                v = [self.value(t[1:-1]) for _ in range(n)]
            self.align()
            return v
        if t in 'uif':
            self.align()
            v = struct.unpack_from({'u': '<I', 'i': '<i', 'f': '<f'}[t], self.b, self.p)[0]
            self.p += 4
            return v
        if t == 'b':
            v = bool(self.b[self.p])
            self.p += 1
            self.align()
            return v
        if t == 's':
            self.align()
            n = struct.unpack_from('<i', self.b, self.p)[0]
            v = self.b[self.p + 4:self.p + 4 + n].decode('utf-8')
            self.p += 4 + n
            self.align()
            return v
        if t == 'a':
            return [self.value('s'), self.value('s'), self.value('s')]
        raise ValueError(t)


def _write(out, t, v):
    def align():
        out.extend(b'\0' * (-len(out) & 3))
    if t[0] == '[':
        align()
        out += struct.pack('<i', len(v))
        if t[1:-1] == 'b':
            out += bytes(1 if x else 0 for x in v)
        else:
            for x in v:
                _write(out, t[1:-1], x)
        align()
    elif t in 'uif':
        align()
        out += struct.pack({'u': '<I', 'i': '<i', 'f': '<f'}[t], v)
    elif t == 'b':
        out.append(1 if v else 0)
        align()
    elif t == 's':
        align()
        b = v.encode('utf-8')
        out += struct.pack('<i', len(b)) + b
        align()
    elif t == 'a':
        for x in v:
            _write(out, 's', x)
    else:
        raise ValueError(t)


class Table:
    """One table: `rows` is a list of dicts (`_id`, the fields, `_empty`, `_order`) in id order."""

    def __init__(self, name, raw):
        self.name, self.schema = name, schema_of(name)
        n = struct.unpack_from('<i', raw, 28)[0]
        p = (32 + n + 3) & ~3
        self.head = bytes(raw[:p])
        count = struct.unpack_from('<i', raw, p)[0]
        r = _Rd(raw, p + 4)
        self.rows = []
        for _ in range(count):
            row = {'_id': r.value('i')}
            for f, t in self.schema:
                row[f] = r.value(t)
            row['_empty'], row['_order'] = r.value('i'), r.value('i')
            self.rows.append(row)
        if (r.p + 3) & ~3 != (len(raw) + 3) & ~3:
            raise ValueError(f'table {name}: {len(raw) - r.p} bytes left over (the schema does not fit this game version)')

    def encode(self):
        out = bytearray(self.head)
        out += struct.pack('<i', len(self.rows))
        for row in self.rows:
            _write(out, 'i', row['_id'])
            for f, t in self.schema:
                _write(out, t, row[f])
            _write(out, 'i', row['_empty'])
            _write(out, 'i', row['_order'])
        return bytes(out)

    def row(self, rid):
        r = self.rows[rid] if rid < len(self.rows) and self.rows[rid]['_id'] == rid else None
        if r is None:
            r = next((x for x in self.rows if x['_id'] == rid), None)
        return r

    def blank(self, rid):
        """An unused row with id `rid`, modelled on the first row."""
        row = {'_id': rid, '_empty': 1, '_order': -1}
        for f, t in self.schema:
            v = self.rows[0][f] if self.rows else None
            row[f] = [] if t[0] == '[' and v is None else (['', '', ''] if t == 'a' else ('' if t == 's' else (False if t == 'b' else
                     (0.0 if t == 'f' else ([type(x)() for x in v] if t[0] == '[' else 0)))))
        return row

    def ensure(self, rid):
        """The row with id `rid`, adding unused rows up to it when the table is shorter."""
        while len(self.rows) <= rid:
            self.rows.append(self.blank(len(self.rows)))
        return self.row(rid)

    def next_order(self):
        return max([r['_order'] for r in self.rows] + [-1]) + 1

    def use(self, rid, **fields):
        """Fill row `rid` (added when missing) and mark it used, listed after every used row."""
        row = self.ensure(rid)
        row.update(fields)
        if row['_empty'] or row['_order'] < 0:
            row['_order'] = self.next_order()
        row['_empty'] = 0
        return row


class Database:
    """The tables of a game tree, with changed ones written into an override tree of the same layout."""

    def __init__(self, aa_switch, cache=None):
        self.aa = aa_switch
        self.cache = cache
        self._index = None
        self._open = {}

    def index(self):
        """{table object name: bundle path relative to the Switch folder}."""
        if self._index is None:
            if self.cache and os.path.exists(self.cache):
                self._index = json.load(open(self.cache, encoding='utf-8'))
            else:
                idx = {}
                files = [os.path.join('db_assets_db', f) for f in sorted(os.listdir(os.path.join(self.aa, 'db_assets_db')))]
                files += [f for f in sorted(os.listdir(self.aa)) if f.endswith('.bundle') and not f.startswith('scene_')]
                for rel in files:
                    try:
                        env = UnityPy.load(os.path.join(self.aa, rel))
                    except Exception:
                        continue
                    for o in env.objects:
                        if o.type.name == 'MonoBehaviour':
                            try:
                                idx[o.peek_name()] = rel.replace('\\', '/')
                            except Exception:
                                pass
                self._index = idx
                if self.cache:
                    os.makedirs(os.path.dirname(self.cache), exist_ok=True)
                    json.dump(idx, open(self.cache, 'w', encoding='utf-8'))
        return self._index

    def table(self, name):
        if name not in self._open:
            rel = self.index()[name]
            env = UnityPy.load(os.path.join(self.aa, rel))
            obj = next(o for o in env.objects if o.type.name == 'MonoBehaviour' and o.peek_name() == name)
            self._open[name] = (Table(name, bytes(obj.get_raw_data())), env, obj, rel)
        return self._open[name][0]

    def save(self, out_switch):
        """Write every opened table into the override tree; returns the relative paths written."""
        done = []
        for name, (table, env, obj, rel) in self._open.items():
            obj.set_raw_data(table.encode())
            dst = os.path.join(out_switch, rel.replace('/', os.sep))
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(env.file.save(packer='lz4'))
            done.append(rel)
        return done


if __name__ == '__main__':
    import sys
    db = Database(sys.argv[1])
    for n in sys.argv[2:]:
        t = db.table(n)
        raw = bytes(db._open[n][2].get_raw_data())
        print(n, db._open[n][3], len(t.rows), 'rows; re-encoding is identical:', t.encode() == raw[:len(t.encode())] and len(raw) - len(t.encode()) < 4)
