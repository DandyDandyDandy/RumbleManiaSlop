"""Read one stage of Super Monkey Ball Banana Mania (Unity 2020.2.7, Windows) into plain Python data.

A stage is the asset bundle `stage_<smb1|smb2>_<bg>_st<ID>`: a prefab `st<ID>` whose root carries `MainGameStage`,
with two children:

    Behavior    what is drawn: mesh renderers, the goal models, bumpers, ...
    Collision   what is played on: `colN` nodes with `CollisionStagePart` (triangles in a `CollisionStageData`),
                `bananaset`, `START`, `GOALnn`, and the animated `MOT_*` groups (an Animator on `Collision`)

The bundles carry type trees, so every object is read as a dict. The game's script classes are recognised by their
field names (the MonoScript objects are in the player's own files, not in the bundles).
"""
import json
import os

import UnityPy
from UnityPy.files import SerializedFile

BUNDLES = os.path.join('smbbm_Data', 'StreamingAssets', 'StandaloneWindows64', 'AssetBundles')

# script class <- a field name only that class has
SIGNATURES = [
    ('MainGameStage', 'm_behaviorTransform'),
    ('CollisionStagePart', 'm_CollisionStage'),
    ('CollisionStageData', 'part'),
    ('MgGoalColi', 'm_GoalKind'),
    ('MgGoalModel', 'm_KusudamaParent'),
    ('BananaPos', 'm_Kind'),
    ('StageMovObjManager', 'm_info'),
    ('MgStageSwitchManager', 'm_ClassIdToParamNameDict'),
    ('MgStageSwitch', 'm_isTurnOnDefault'),
    ('CollisionSwitchUpper', 'm_CylinderRadius'),
    ('CollisionBumper', 'm_BumperPower'),
    ('Bumper', 'm_ring'),
    ('MgWormholeColi', 'm_PairedWormhole'),
    ('MgSeesaw', 'momentFactor'),
    ('CollisionJamabar', 'm_OffsetSpeed'),
    ('MgJamabar', 'JamabarModel'),
    ('MgConveyer', 'm_StaticSpeed'),
    ('CollisionWave', 'STEP_X'),
    ('MgTRSSync', 'm_dstTransformList'),
    ('MgBlurFloor', 'm_LeadingFloor'),
    ('MainGameStageArea', 'm_AttributeToAreaList'),
    ('MgConveyManager', 'm_conveyParamArray'),
    ('GravityTilt', 'm_IsEnableFixedUpdate'),
    ('BgRoot', 'm_trs'),
]


def script_class(tree):
    for name, field in SIGNATURES:
        if field in tree:
            return name
    return None


class Node:
    """A GameObject with its transform and components."""
    __slots__ = ('id', 'name', 'active', 'layer', 'pos', 'rot', 'scale', 'parent', 'children', 'components', 'transform_id')

    def __init__(self):
        self.children, self.components, self.parent = [], [], None

    def component(self, kind):
        """The first component of a Unity class name or script class name: (kind, object key, tree)."""
        for c in self.components:
            if c[0] == kind:
                return c
        return None

    def path(self, root=None):
        parts = []
        n = self
        while n is not None and n is not root:
            parts.append(n.name)
            n = n.parent
        return '/'.join(reversed(parts))

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


class ManiaStage:
    def __init__(self, game_dir, stage_bundle):
        """game_dir: the Banana Mania folder; stage_bundle: e.g. 'stage_smb1_jungle_st1001'."""
        self.dir = os.path.join(game_dir, BUNDLES)
        self.bundle = stage_bundle
        deps = self._dependencies(stage_bundle)
        self.env = UnityPy.load(*[os.path.join(self.dir, b) for b in [stage_bundle] + deps])
        self.files = {}                 # internal file name (lower case) -> SerializedFile
        for f in self.env.files.values():
            for name, sf in getattr(f, 'files', {}).items():
                if isinstance(sf, SerializedFile):
                    self.files[name.lower()] = sf
        self.main = [sf for name, sf in self.files.items()
                     if any(o.type.name == 'AssetBundle' and o.read_typetree()['m_Name'] == stage_bundle
                            for o in sf.objects.values())][0]
        self._trees = {}
        self._build()

    def _dependencies(self, name):
        man = os.path.join(self.dir, 'asset_bundle_manifest.json')
        try:
            data = json.load(open(man, encoding='utf-8'))
        except (OSError, ValueError):
            return []
        for e in data.get('assetBundleInfoList', []):
            if e.get('name') == name:
                return list(e.get('dependencyList') or [])
        return []

    # ---- objects ------------------------------------------------------------------------------------------
    def resolve(self, sf, ref):
        """(SerializedFile, ObjectReader) a PPtr of file `sf` points at, or None."""
        pid = ref.get('m_PathID', 0)
        if not pid:
            return None
        target = sf
        if ref.get('m_FileID'):
            ext = sf.externals[ref['m_FileID'] - 1]
            target = self.files.get(ext.path.replace('\\', '/').rsplit('/', 1)[-1].lower())
            if target is None:
                return None
        obj = target.objects.get(pid)
        return (target, obj) if obj is not None else None

    def tree(self, sf, obj):
        key = (id(sf), obj.path_id)
        if key not in self._trees:
            self._trees[key] = obj.read_typetree()
        return self._trees[key]

    def get(self, sf, ref):
        """(key, tree) of the object a PPtr points at; the key identifies the object across files."""
        r = self.resolve(sf, ref)
        if r is None:
            return None
        return (id(r[0]), r[1].path_id), self.tree(*r), r[0], r[1]

    def resource(self, sf, stream):
        """The bytes a StreamingInfo / StreamedResource of file `sf` refers to."""
        if not stream.get('size'):
            return b''
        base = stream['path'].replace('\\', '/').rsplit('/', 1)[-1]
        holder = sf.parent
        res = holder.files.get(base)
        if res is None:
            for name, f in holder.files.items():
                if name.lower() == base.lower():
                    res = f
        if res is None:
            raise KeyError(f'resource file {base} not found for {self.bundle}')
        pos = res.Position
        res.Position = stream['offset']
        data = res.read_bytes(stream['size'])
        res.Position = pos
        return bytes(data)

    # ---- hierarchy ----------------------------------------------------------------------------------------
    def _build(self):
        sf = self.main
        nodes = {}
        by_transform = {}
        for o in sf.objects.values():
            if o.type.name != 'GameObject':
                continue
            g = self.tree(sf, o)
            n = Node()
            n.id, n.name, n.active, n.layer = o.path_id, g['m_Name'], bool(g['m_IsActive']), g['m_Layer']
            for comp in g['m_Component']:
                c = sf.objects.get(comp['component']['m_PathID'])
                if c is None:
                    continue
                t = self.tree(sf, c)
                kind = c.type.name
                if kind == 'Transform':
                    p, r, s = t['m_LocalPosition'], t['m_LocalRotation'], t['m_LocalScale']
                    n.pos, n.rot, n.scale = (p['x'], p['y'], p['z']), (r['x'], r['y'], r['z'], r['w']), (s['x'], s['y'], s['z'])
                    n.transform_id = c.path_id
                    by_transform[c.path_id] = (n, t)
                elif kind == 'MonoBehaviour':
                    kind = script_class(t) or 'MonoBehaviour'
                n.components.append((kind, c.path_id, t))
            nodes[o.path_id] = n
        for n, t in by_transform.values():
            n.children = [by_transform[c['m_PathID']][0] for c in t['m_Children'] if c['m_PathID'] in by_transform]
            for c in n.children:
                c.parent = n
        self.nodes = nodes
        self.by_transform = {tid: n for tid, (n, _) in by_transform.items()}
        roots = [n for n in nodes.values() if n.parent is None and n.component('MainGameStage')]
        if not roots:
            raise ValueError(f'{self.bundle}: no MainGameStage root')
        self.root = roots[0]
        mgs = self.root.component('MainGameStage')[2]
        self.info = mgs
        self.behavior = self.by_transform.get(mgs['m_behaviorTransform']['m_PathID'])
        self.collision = self.by_transform.get(mgs['m_collisionTransform']['m_PathID'])
