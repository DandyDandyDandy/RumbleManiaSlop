"""Convert one Banana Mania stage into a Banana Rumble stage scene bundle.

Rumble's stage code descends from Mania's: a stage root with `MainGameStage`, collision as `CollisionStagePart`
nodes pointing at `CollisionStageData` triangle sets, bananas as empty transforms, a start transform, goals with
`MgGoalColi`. What differs is the packaging (Rumble: a scene bundle, Mania: a prefab bundle), the fields of those
classes, the shaders, and that Rumble's goal is its own arch model with its own trigger shapes.

The new bundle is a copy of one of the game's own stage bundles (the template, World 1 Stage 1), with the template's
stage geometry removed and the Mania stage put in:

    <stage root>            MainGameStage (template's object, fields rewritten)
        mania               new: the Mania prefab's hierarchy
            Behavior        the drawn meshes (new Mesh / Material / Texture2D objects in the bundle's sharedAssets)
            Collision       collision parts, bananas, animated groups
        goal_arch ...       the template's goal, moved to each Mania goal (cloned for further goals)
        START_NULL0         the template's start transform, moved
        ...BeginningBounds  the template's intro-camera bounds, resized
    MainGameInitializer     template

See docs/MANIA.md for the formats and for what is not converted.
"""
import copy
import math
import os
import struct
import zlib

import attrs
import numpy as np
import UnityPy

from maniastage import ManiaStage
from unityfile import Editor, NULL, overlay, pptr, serialized_files

LAYER = 7                       # the layer of stage objects in Rumble's stage scenes
Y180 = (0.0, 1.0, 0.0, 0.0)     # Mania's start and goal face -Z, Rumble's +Z
TAG_STGMOT = 20000              # the tag "StgMot" (the game's first own tag): collision under it follows its transform
TEMPLATE_STAGE = 'bg_stg_w01_001'
MATERIAL_CACHE = os.path.join('manual_additions_assets_maingame', 'stagemiddle', 'w01', 'unitymaterialscache.bundle')
# the template materials (World 1's material cache): name -> what it is used for
MATERIAL_MODELS = {'opaque': 'bg_stg_w01_island02', 'cutout': 'bg_stg_w01_plants01', 'transparent': 'bg_stg_w01_swg02'}
# Script classes the template stage does not use are taken from a stage of the game that does (its type entry with
# the type tree, and its MonoScript object): class -> stage scene
SCRIPT_DONORS = {'CollisionBumper': 'bg_stg_w01_102', 'MgBumper': 'bg_stg_w01_102',
                 'MgStageSwitchController': 'bg_stg_w03_001', 'MgSwitch': 'bg_stg_w03_001', 'CollisionSwitchUpper': 'bg_stg_w03_001',
                 'MgSeesaw': 'bg_stg_w06_218', 'MgConveyer': 'bg_stg_w02_006'}
SWITCH_CLIPS = ('bg_stg_w03_001', 'obj_com_switch_on', 'obj_com_switch_off')   # the clips Rumble's switch names


# ------------------------------------------------------------------------------------------------- small maths

def qmul(a, b):
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def qrot(q, v):
    u = np.array(q[:3], dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    return v + 2.0 * np.cross(u, np.cross(u, v) + q[3] * v)


def trs_matrix(pos, rot, scale):
    x, y, z, w = rot
    m = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w), 0.0],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w), 0.0],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y), 0.0],
                  [0.0, 0.0, 0.0, 1.0]])
    m[:3, :3] *= np.array(scale, dtype=np.float64)[None, :]
    m[:3, 3] = pos
    return m


def world_matrix(node, stop=None):
    m = np.eye(4)
    while node is not None and node is not stop:
        m = trs_matrix(node.pos, node.rot, node.scale) @ m
        node = node.parent
    return m


def world_rotation(node, stop=None):
    q = (0.0, 0.0, 0.0, 1.0)
    while node is not None and node is not stop:
        q = qmul(node.rot, q)
        node = node.parent
    return q


def quat_from_axes(x, y, z):
    """Quaternion of the rotation whose columns are the unit vectors x, y, z."""
    m = np.array([x, y, z]).T
    t = m[0, 0] + m[1, 1] + m[2, 2]
    if t > 0:
        s = math.sqrt(t + 1.0) * 2
        q = ((m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s)
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = (0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s)
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = ((m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s)
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = ((m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s)
    return tuple(float(c) for c in q)


def v3(v):
    return {'x': float(v[0]), 'y': float(v[1]), 'z': float(v[2])}


def v2(v):
    return {'x': float(v[0]), 'y': float(v[1])}


def q4(q):
    return {'x': float(q[0]), 'y': float(q[1]), 'z': float(q[2]), 'w': float(q[3])}


def is_pptr(d):
    return isinstance(d, dict) and len(d) == 2 and 'm_FileID' in d and 'm_PathID' in d


def walk_pptrs(v, fn):
    """Call fn(pptr dict) for every PPtr in a type tree value; fn may change it in place."""
    if isinstance(v, dict):
        if is_pptr(v):
            fn(v)
        else:
            for x in v.values():
                walk_pptrs(x, fn)
    elif isinstance(v, (list, tuple)):
        for x in v:
            walk_pptrs(x, fn)


# -------------------------------------------------------------------------------------------- the Rumble scene

class Scene:
    """The template bundle being turned into a new stage."""

    def __init__(self, template_bundle):
        self.env = UnityPy.load(template_bundle)
        files = serialized_files(self.env)
        self.shared_name = [n for n in files if n.endswith('.sharedAssets')][0]
        self.scene_name = self.shared_name[:-len('.sharedAssets')]
        self.scene = Editor(files[self.scene_name])
        self.shared = Editor(files[self.shared_name])
        self.shared_fid = 1 + [i for i, e in enumerate(self.scene.sf.externals) if e.path.endswith(self.shared_name)][0]
        s = self.scene
        self.go_of_tr, self.tr_of_go = {}, {}
        self._imported = {}
        for o in s.objects('Transform'):
            t = s.get(o.path_id)
            self.go_of_tr[o.path_id] = t['m_GameObject']['m_PathID']
            self.tr_of_go[t['m_GameObject']['m_PathID']] = o.path_id
        # models for new objects, taken before anything is removed
        for cls in ('GameObject', 'Transform', 'MeshFilter'):
            s.donor(cls)
        for o in s.objects('MeshRenderer'):
            if s.get(o.path_id)['m_StaticBatchInfo']['subMeshCount'] == 0:
                s._donors[('MeshRenderer', None)] = (o, copy.deepcopy(s.get(o.path_id)))
                break
        s.donor('MonoBehaviour', 'CollisionStagePart')
        s.donor('MonoBehaviour', 'ReplayTracker')
        s.donor('Animator')
        for cls in ('Mesh', 'Material', 'Texture2D', 'AnimationClip', 'AnimatorController'):
            self.shared.donor(cls)
        self.shared.donor('MonoBehaviour', 'CollisionStageData')

    # ---- hierarchy helpers
    def name(self, go):
        return self.scene.get(go)['m_Name']

    def children(self, go):
        return [self.go_of_tr[c['m_PathID']] for c in self.scene.get(self.tr_of_go[go])['m_Children']]

    def find(self, go, name):
        for c in self.children(go):
            if self.name(c) == name:
                return c
        return None

    def roots(self):
        return [g for g, t in self.tr_of_go.items() if self.scene.get(t)['m_Father']['m_PathID'] == 0]

    def components(self, go):
        return [c['component']['m_PathID'] for c in self.scene.get(go)['m_Component']]

    def component(self, go, cls, script=None):
        for c in self.components(go):
            o = self.scene.sf.objects[c]
            if o.type.name == cls and (script is None or self.scene.script_class(o) == script):
                return c
        return None

    def subtree(self, go):
        """Every object id of a GameObject subtree: GameObjects and their components."""
        out = [go] + self.components(go)
        for c in self.children(go):
            out += self.subtree(c)
        return out

    def delete(self, go):
        tr = self.tr_of_go[go]
        father = self.scene.get(tr)['m_Father']['m_PathID']
        if father:
            ft = self.scene.get(father)
            ft['m_Children'] = [c for c in ft['m_Children'] if c['m_PathID'] != tr]
        for g in [x for x in self.subtree(go) if x in self.tr_of_go]:
            t = self.tr_of_go.pop(g)
            self.go_of_tr.pop(t, None)
        for pid in self.subtree_ids_cached if False else []:
            pass
        self._delete_ids(go, tr)

    def _delete_ids(self, go, tr):
        # the maps were already cleared for this subtree: walk the trees directly
        stack = [go]
        while stack:
            g = stack.pop()
            gt = self.scene.get(g)
            for c in gt['m_Component']:
                pid = c['component']['m_PathID']
                o = self.scene.sf.objects.get(pid)
                if o is not None and o.type.name == 'Transform':
                    for ch in self.scene.get(pid)['m_Children']:
                        stack.append(self.scene.get(ch['m_PathID'])['m_GameObject']['m_PathID'])
                if o is not None:
                    self.scene.remove(pid)
            self.scene.remove(g)

    def new_object(self, name, parent_go, pos=(0, 0, 0), rot=(0, 0, 0, 1), scale=(1, 1, 1), active=True):
        """A new GameObject with a Transform under parent_go; returns its id."""
        s = self.scene
        go = s.add('GameObject', {'m_Component': [], 'm_Layer': LAYER, 'm_Name': name, 'm_Tag': 0, 'm_IsActive': bool(active)})
        ptr = self.tr_of_go[parent_go] if parent_go else 0
        tr = s.add('Transform', {'m_GameObject': pptr(go), 'm_LocalRotation': q4(rot), 'm_LocalPosition': v3(pos),
                                 'm_LocalScale': v3(scale), 'm_Children': [], 'm_Father': pptr(ptr)})
        s.get(go)['m_Component'].append({'component': pptr(tr)})
        if ptr:
            s.get(ptr)['m_Children'].append(pptr(tr))
        self.tr_of_go[go], self.go_of_tr[tr] = tr, go
        return go

    def add_component(self, go, cls, tree, script=None):
        tree['m_GameObject'] = pptr(go)
        pid = self.scene.add(cls, tree, script)
        self.scene.get(go)['m_Component'].append({'component': pptr(pid)})
        return pid

    def set_transform(self, go, pos=None, rot=None, parent=None, scale=None):
        t = self.scene.get(self.tr_of_go[go])
        if scale is not None:
            t['m_LocalScale'] = v3(scale)
        if pos is not None:
            t['m_LocalPosition'] = v3(pos)
        if rot is not None:
            t['m_LocalRotation'] = q4(rot)
        if parent is not None:
            old = t['m_Father']['m_PathID']
            me = self.tr_of_go[go]
            if old:
                ot = self.scene.get(old)
                ot['m_Children'] = [c for c in ot['m_Children'] if c['m_PathID'] != me]
            t['m_Father'] = pptr(self.tr_of_go[parent])
            self.scene.get(self.tr_of_go[parent])['m_Children'].append(pptr(me))

    def clone(self, go, parent_go):
        """A deep copy of a GameObject subtree under parent_go; returns the copy's root id."""
        s = self.scene
        ids = self.subtree(go)
        remap = {}
        for pid in ids:
            o = s.sf.objects[pid]
            cls = o.type.name
            script = s.script_class(o) if cls == 'MonoBehaviour' else None
            s._donors.setdefault((cls, script), (o, copy.deepcopy(s.get(pid))))
            remap[pid] = s.add(cls, copy.deepcopy(s.get(pid)), script)

        def fix(p):
            if p['m_FileID'] == 0 and p['m_PathID'] in remap:
                p['m_PathID'] = remap[p['m_PathID']]
        for old, new in remap.items():
            walk_pptrs(s.get(new), fix)
            if s.sf.objects[new].type.name == 'Transform':
                g = s.get(new)['m_GameObject']['m_PathID']
                self.tr_of_go[g], self.go_of_tr[new] = new, g
        root = remap[go]
        rt = s.get(self.tr_of_go[root])
        rt['m_Father'] = pptr(self.tr_of_go[parent_go])
        s.get(self.tr_of_go[parent_go])['m_Children'].append(pptr(self.tr_of_go[root]))
        return root

    def import_script(self, aa_switch, cls):
        """Make the script class `cls` usable in this scene: copy its MonoScript and its type entry from a stage of
        the game that has an object of it. Afterwards scene.template('MonoBehaviour', cls) and add(...) work."""
        s, sh = self.scene, self.shared
        if ('MonoBehaviour', cls) in s._donors:
            return
        try:
            s.donor('MonoBehaviour', cls)
            return
        except KeyError:
            pass
        donor = _donor_stage(os.path.join(aa_switch, f'scene_{SCRIPT_DONORS[cls]}_scenes_all.bundle'))
        obj, tree, script_tree = donor[cls]
        script = sh.add('MonoScript', copy.deepcopy(script_tree))
        ident = copy.copy(s.sf.script_types[0])
        ident.local_serialized_file_index = self.shared_fid
        ident.local_identifier_in_file = script
        s.sf.script_types.append(ident)
        typ = copy.copy(obj.serialized_type)
        typ.script_type_index = len(s.sf.script_types) - 1
        s.sf.types.append(typ)
        model = attrs.evolve(next(o for o in s.sf.objects.values() if o.type.name == 'MonoBehaviour'),
                             type_id=len(s.sf.types) - 1, serialized_type=typ, data=None)
        tree = copy.deepcopy(tree)
        tree['m_Script'] = pptr(script, self.shared_fid)
        s._donors[('MonoBehaviour', cls)] = (model, tree)

    def import_asset(self, aa_switch, stage, cls, name):
        """Copy the object of class `cls` named `name` from the sharedAssets of another stage of the game; its id."""
        key = (stage, cls, name)
        if key not in self._imported:
            shared = _donor_stage(os.path.join(aa_switch, f'scene_{stage}_scenes_all.bundle'), want_shared=True)
            src = next(o for o in shared.objects.values() if o.type.name == cls and o.peek_name() == name)
            self._imported[key] = self.shared.add(cls, src.read_typetree())
        return self._imported[key]

    def shared_ref(self, pid):
        """A PPtr, as written in the scene file, to an object of the sharedAssets file."""
        return pptr(pid, self.shared_fid) if pid else dict(NULL)

    # ---- finishing
    def collect_garbage(self):
        """Remove the objects of the sharedAssets file that nothing refers to any more (the template's own meshes,
        materials, textures and collision data), and rebuild the preload list."""
        sh, sc = self.shared, self.scene
        live = set()
        todo = []

        def from_scene(p):
            if p['m_FileID'] == self.shared_fid and p['m_PathID'] in sh.sf.objects and p['m_PathID'] not in live:
                live.add(p['m_PathID'])
                todo.append(p['m_PathID'])

        def from_shared(p):
            if p['m_FileID'] == 0 and p['m_PathID'] in sh.sf.objects and p['m_PathID'] not in live:
                live.add(p['m_PathID'])
                todo.append(p['m_PathID'])
        for pid in list(sc.sf.objects):
            walk_pptrs(sc.get(pid), from_scene)
        for o in sh.objects():
            if o.type.name in ('MonoScript', 'AssetBundle', 'PreloadData'):
                live.add(o.path_id)
        while todo:
            walk_pptrs(sh.get(todo.pop()), from_shared)
        for pid in [p for p in sh.sf.objects if p not in live]:
            sh.remove(pid)
        for o in sh.objects('PreloadData'):
            t = sh.get(o.path_id)
            keep = [p for p in t['m_Assets'] if p['m_FileID'] != 0]
            mine = [pptr(x.path_id) for x in sh.objects() if x.type.name in ('Material', 'Mesh', 'Texture2D', 'AnimationClip',
                                                                           'AnimatorController', 'Avatar', 'PhysicMaterial')]
            t['m_Assets'] = keep + mine

    def add_external(self, cab):
        """Index (1-based file id) of the external file `cab` in the sharedAssets file, adding it when new."""
        sf = self.shared.sf
        low = cab.lower()
        for i, e in enumerate(sf.externals):
            if e.path.replace('\\', '/').rsplit('/', 1)[-1].lower() == low:
                return i + 1
        e = copy.copy(sf.externals[0])
        e.path = f'archive:/{cab}/{cab}'
        sf.externals.append(e)
        for o in self.shared.objects():
            if o.type.name in ('AssetBundle', 'PreloadData'):
                deps = self.shared.get(o.path_id)['m_Dependencies']
                if low not in deps:
                    deps.append(low)
        return len(sf.externals)

    def save(self, out_path, bundle_name=None, scene_path=None, cab=None):
        """Write the bundle. With bundle_name / scene_path / cab the bundle gets an identity of its own (a new
        stage); without them it keeps the template's (it then replaces the template stage)."""
        self.collect_garbage()
        if scene_path:
            for o in self.shared.objects('AssetBundle'):
                t = self.shared.get(o.path_id)
                t['m_Name'] = t['m_AssetBundleName'] = bundle_name
                t['m_Container'] = [[scene_path, t['m_Container'][0][1]]]
                t['m_SceneHashes'] = [[scene_path, cab]]
        if cab:
            # data that stays in the bundle's resource file (the goal's meshes and textures) is found by path
            for o in self.shared.objects():
                if o.type.name in ('Mesh', 'Texture2D'):
                    t = self.shared.get(o.path_id)
                    sd = t.get('m_StreamData')
                    if sd and self.scene_name in sd.get('path', ''):
                        sd['path'] = sd['path'].replace(self.scene_name, cab)
        self.scene.commit()
        self.shared.commit()
        if cab:
            from unityfile import rename_cabs
            rename_cabs(self.env, {self.scene_name: cab})
        data = self.env.file.save(packer='lz4')
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path + '.tmp', 'wb') as f:
            f.write(data)
        os.replace(out_path + '.tmp', out_path)
        return len(data)


_donor_cache = {}


def _donor_stage(bundle, want_shared=False):
    """{script class: (object, its type tree dict, its MonoScript's dict)} of the MonoBehaviours of a stage scene."""
    if bundle not in _donor_cache:
        env = UnityPy.load(bundle)
        files = serialized_files(env)
        shared_name = [n for n in files if n.endswith('.sharedAssets')][0]
        scene, shared = files[shared_name[:-len('.sharedAssets')]], files[shared_name]
        out = {}
        for o in scene.objects.values():
            if o.type.name != 'MonoBehaviour':
                continue
            t = o.read_typetree()
            ref = t['m_Script']
            so = shared.objects.get(ref['m_PathID']) if ref['m_FileID'] else scene.objects.get(ref['m_PathID'])
            if so is None:
                continue
            st = so.read_typetree()
            out.setdefault(st['m_ClassName'], (o, t, st))
        _donor_cache[bundle] = (env, out, shared)
    return _donor_cache[bundle][2 if want_shared else 1]


# ------------------------------------------------------------------------------------------------- conversion

class MaterialModels:
    """The template materials: World 1's material cache holds materials of the shaders the converted stages use."""

    def __init__(self, aa_switch):
        env = UnityPy.load(os.path.join(aa_switch, MATERIAL_CACHE))
        self.models = {}
        want = {v: k for k, v in MATERIAL_MODELS.items()}
        for name, sf in serialized_files(env).items():
            for o in sf.objects.values():
                if o.type.name != 'Material':
                    continue
                t = o.read_typetree()
                if t['m_Name'] in want:
                    sh = t['m_Shader']
                    cab = sf.externals[sh['m_FileID'] - 1].path.replace('\\', '/').rsplit('/', 1)[-1]
                    self.models[want[t['m_Name']]] = (t, cab, sh['m_PathID'])
        missing = set(MATERIAL_MODELS) - set(self.models)
        if missing:
            raise ValueError(f'template materials not found in {MATERIAL_CACHE}: {sorted(missing)}')


def merged_part(pieces):
    """One Mania collision part out of several: pieces is [(part, 4x4 matrix that takes the part into the common
    frame)]. The triangles are carried into the frame, the edge ids of each further part are moved past those of
    the parts before it, and the grid is a single cell that lists every triangle (which is what Mania itself
    stores for small parts)."""
    tris, base = [], 0
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for part, mat in pieces:
        top = -1
        for t in part['triangle']:
            top = max([top] + list(t['edgeIndices']))
            p = np.array([t['pos']['x'], t['pos']['y'], t['pos']['z']], dtype=np.float64)
            rot = (t['rot']['x'], t['rot']['y'], t['rot']['z'], t['rot']['w'])
            a = p + qrot(rot, (t['lpos'][0]['x'], t['lpos'][0]['y'], 0.0))
            b = p + qrot(rot, (t['lpos'][1]['x'], t['lpos'][1]['y'], 0.0))
            p, a, b = [(mat @ np.append(v, 1.0))[:3] for v in (p, a, b)]
            e1, e2 = a - p, b - p
            n = np.cross(e1, e2)
            ln, l1 = np.linalg.norm(n), np.linalg.norm(e1)
            if ln < 1e-12 or l1 < 1e-9:
                continue
            n, x = n / ln, e1 / l1
            y = np.cross(n, x)
            new = copy.deepcopy(t)
            new['pos'], new['rot'] = v3(p), q4(quat_from_axes(x, y, n))
            new['lpos'] = [v2((float(l1), 0.0)), v2((float(np.dot(e2, x)), float(np.dot(e2, y))))]
            new['edgeIndices'] = [e if e < 0 else e + base for e in t['edgeIndices']]
            tris.append(new)
            lo, hi = np.minimum(lo, np.minimum(np.minimum(p, a), b)), np.maximum(hi, np.maximum(np.maximum(p, a), b))
        base += top + 1
    if not tris:
        lo = hi = np.zeros(3)
    size = np.maximum(hi - lo, 1e-3)
    return {'triangle': tris, 'gridTriangleList': {'X': [{'Y': [{'Z': [{'indexList': list(range(len(tris)))}]}]}]},
            'gridMin': v3(lo), 'intervalX': float(size[0]), 'intervalY': float(size[1]), 'intervalZ': float(size[2]),
            'gridSizeX': 1, 'gridSizeY': 1, 'gridSizeZ': 1}


def collision_part(part, proto):
    """Rumble's CollisionStageData.part from Mania's.

    A triangle is stored as its first corner `pos`, a rotation `rot` whose z axis is the normal and whose x axis runs
    along the first edge, the other two corners in that frame (`lpos`), the 2D normals of the second and third edge
    (`lnml`), and an id per edge (`edgeIndices`, -1 where the edge needs no test of its own). Rumble adds a bounding
    box per triangle and for the whole part (with an orientation matrix) in place of Mania's bounding spheres.
    The frame values are recomputed from the corners, so nothing depends on the two games agreeing on them."""
    tris = []
    tri_proto = proto['triangle'][0]
    lo_all, hi_all = np.full(3, np.inf), np.full(3, -np.inf)
    for t in part['triangle']:
        p = np.array([t['pos']['x'], t['pos']['y'], t['pos']['z']], dtype=np.float64)
        rot = (t['rot']['x'], t['rot']['y'], t['rot']['z'], t['rot']['w'])
        a = p + qrot(rot, (t['lpos'][0]['x'], t['lpos'][0]['y'], 0.0))
        b = p + qrot(rot, (t['lpos'][1]['x'], t['lpos'][1]['y'], 0.0))
        e1, e2 = a - p, b - p
        n = np.cross(e1, e2)
        ln = np.linalg.norm(n)
        l1 = np.linalg.norm(e1)
        if ln < 1e-12 or l1 < 1e-9:                 # degenerate: keep the stored frame
            x = qrot(rot, (1, 0, 0)); n = qrot(rot, (0, 0, 1)); y = np.cross(n, x); q = rot
        else:
            n = n / ln
            x = e1 / l1
            y = np.cross(n, x)
            q = quat_from_axes(x, y, n)
        la = (float(np.dot(e1, x)), 0.0)
        lb = (float(np.dot(e2, x)), float(np.dot(e2, y)))
        ex, ey = lb[0] - la[0], lb[1] - la[1]
        le = math.hypot(ex, ey) or 1.0
        l2 = math.hypot(lb[0], lb[1]) or 1.0
        lo, hi = np.minimum(np.minimum(p, a), b), np.maximum(np.maximum(p, a), b)
        lo_all, hi_all = np.minimum(lo_all, lo), np.maximum(hi_all, hi)
        tris.append({'pos': v3(p), 'normal': v3(n), 'rot': q4(q), 'flag': t['flag'],
                     'lpos': [v2(la), v2(lb)], 'lnml': [v2((-ey / le, ex / le)), v2((lb[1] / l2, -lb[0] / l2))],
                     'edgeIndices': list(t['edgeIndices']), 'bounds': {'min': v3(lo), 'max': v3(hi)}})
        assert set(tris[-1]) == set(tri_proto), (set(tris[-1]) ^ set(tri_proto))
    if not tris:
        lo_all = hi_all = np.zeros(3)
    centre = (lo_all + hi_all) / 2
    ident = {f'e{r}{c}': (1.0 if r == c else 0.0) for r in range(4) for c in range(4)}
    out = {'triangle': tris,
           'gridTriangleList': copy.deepcopy(part['gridTriangleList']),
           'gridMin': copy.deepcopy(part['gridMin']),
           'intervalX': part['intervalX'], 'intervalY': part['intervalY'], 'intervalZ': part['intervalZ'],
           'gridSizeX': part['gridSizeX'], 'gridSizeY': part['gridSizeY'], 'gridSizeZ': part['gridSizeZ'],
           'culling': {'pos': v3(centre), 'rad': float(np.linalg.norm(hi_all - centre))},
           'bounds': {'min': v3(lo_all), 'max': v3(hi_all)}, 'boundsOrient': ident}
    assert set(out) == set(proto), (set(out) ^ set(proto))
    return out, lo_all, hi_all


class Converter:
    def __init__(self, mania_dir, aa_switch):
        """mania_dir: the Banana Mania install; aa_switch: <Rumble>_Data/StreamingAssets/aa/Switch (converted tree)."""
        self.mania_dir, self.aa = mania_dir, aa_switch
        self.template = os.path.join(aa_switch, f'scene_{TEMPLATE_STAGE}_scenes_all.bundle')
        self.materials = MaterialModels(aa_switch)

    def convert(self, stage_bundle, out_path, identity=None, log=None):
        """Convert Mania's `stage_bundle` and write the Rumble bundle to out_path.

        identity: None to keep the template's names (the result replaces World 1 Stage 1: a test aid), or
        (bundle name, scene path, internal file name) for a new stage. Returns a dict of facts about the stage."""
        say = log or (lambda *a: None)
        m = ManiaStage(self.mania_dir, stage_bundle)
        sc = Scene(self.template)
        s, sh = sc.scene, sc.shared
        root = [g for g in sc.roots() if sc.component(g, 'MonoBehaviour', 'MainGameStage')][0]
        mgs = s.get(sc.component(root, 'MonoBehaviour', 'MainGameStage'))

        # ---- the template's own stage content goes
        for name in (TEMPLATE_STAGE, 'checkpoint01'):
            g = sc.find(root, name)
            if g:
                sc.delete(g)
        arrows = sc.find(root, 'GuideArrows')
        for c in sc.children(arrows) if arrows else []:
            sc.delete(c)
        goal0 = sc.find(root, 'goal_arch')
        start = sc.find(root, 'START_NULL0')
        bounds_holder = [g for g in sc.children(root) if sc.name(g).endswith('_BeginningBounds')]

        # ---- assets
        tex_ids, mat_ids, mesh_ids = {}, {}, {}

        def texture(sf, ref):
            got = m.get(sf, ref)
            if got is None:
                return dict(NULL)
            key, t, tsf, _ = got
            if key not in tex_ids:
                new = overlay(sh.template('Texture2D'), t)
                data = bytes(t.get('image data') or b'')
                if not data and t.get('m_StreamData', {}).get('size'):
                    data = m.resource(tsf, t['m_StreamData'])
                new['image data'] = data
                new['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
                new['m_IsReadable'] = False
                if 'm_PlatformBlob' in new:
                    new['m_PlatformBlob'] = []
                tex_ids[key] = sh.add('Texture2D', new)
            return pptr(tex_ids[key])

        def material(sf, ref):
            got = m.get(sf, ref)
            if got is None:
                return dict(NULL)
            key, t, msf, _ = got
            if key not in mat_ids:
                props = t['m_SavedProperties']
                texs = dict(props['m_TexEnvs'])
                cols = dict(props['m_Colors'])
                floats = dict(props['m_Floats'])
                shader = m.get(msf, t['m_Shader'])
                sname = shader[1]['m_ParsedForm']['m_Name'] if shader else ''
                tags = dict(t.get('stringTagMap') or [])
                kind = 'opaque'
                low = sname.lower()
                if tags.get('RenderType') == 'Transparent' or 'transparent' in low or low.endswith(('trvc', 'rimtr', 'tr', 'va')) \
                        or t.get('m_CustomRenderQueue', -1) >= 3000:
                    kind = 'transparent'
                elif tags.get('RenderType') == 'TransparentCutout' or 2450 <= t.get('m_CustomRenderQueue', -1) < 3000:
                    kind = 'cutout'
                model, cab, shader_pid = self.materials.models[kind]
                new = copy.deepcopy(model)
                new['m_Name'] = 'mania_' + t['m_Name']
                new['m_Shader'] = pptr(shader_pid, sc.add_external(cab))
                main = texs.get('_MainTex') or {}
                ntex = []
                for k, v in new['m_SavedProperties']['m_TexEnvs']:
                    v = copy.deepcopy(v)
                    v['m_Texture'] = dict(NULL)
                    if k == '_Albedo' and main:
                        v['m_Texture'] = texture(msf, main['m_Texture'])
                        v['m_Scale'], v['m_Offset'] = copy.deepcopy(main['m_Scale']), copy.deepcopy(main['m_Offset'])
                    ntex.append((k, v))
                new['m_SavedProperties']['m_TexEnvs'] = ntex
                tint = cols.get('_Color')
                ncol = []
                for k, v in new['m_SavedProperties']['m_Colors']:
                    if k in ('_Color', '_BaseColor') and tint:
                        v = {'r': tint['r'], 'g': tint['g'], 'b': tint['b'], 'a': tint['a'] if kind == 'transparent' else 1.0}
                    ncol.append((k, v))
                new['m_SavedProperties']['m_Colors'] = ncol
                cull = floats.get('_Cull')
                if cull is not None:
                    new['m_SavedProperties']['m_Floats'] = [(k, float(cull) if k == '_Cull' else v)
                                                            for k, v in new['m_SavedProperties']['m_Floats']]
                mat_ids[key] = sh.add('Material', new)
            return pptr(mat_ids[key])

        def mesh(sf, ref):
            got = m.get(sf, ref)
            if got is None:
                return dict(NULL)
            key, t, msf, _ = got
            if key not in mesh_ids:
                new = overlay(sh.template('Mesh'), t)
                vd = new['m_VertexData']
                if not vd.get('m_DataSize') and t.get('m_StreamData', {}).get('size'):
                    vd['m_DataSize'] = m.resource(msf, t['m_StreamData'])
                new['m_StreamData'] = {'offset': 0, 'size': 0, 'path': ''}
                new['m_BakedConvexCollisionMesh'] = b''
                new['m_BakedTriangleCollisionMesh'] = b''
                mesh_ids[key] = sh.add('Mesh', new)
            return pptr(mesh_ids[key])

        clip_ids = {}

        animated_paths = set()          # hashes of the object paths (from the Animator's object) the clips move

        def clip(sf, ref):
            got = m.get(sf, ref)
            if got is None:
                return dict(NULL), 0
            key, t, _, _ = got
            if key not in clip_ids:
                clip_ids[key] = sh.add('AnimationClip', overlay(sh.template('AnimationClip'), t))
            animated_paths.update(b['path'] for b in t['m_ClipBindingConstant']['genericBindings'])
            return pptr(clip_ids[key]), len(t['m_ClipBindingConstant']['genericBindings'])

        def controller(sf, ref):
            """The stage's AnimatorController (one layer and one state per clip, each state's speed a float
            parameter named like the state) with its clips; (path id, number of animated bindings)."""
            got = m.get(sf, ref)
            if got is None:
                return 0, 0
            _, t, csf, _ = got
            new = overlay(sh.template('AnimatorController'), t)
            clips = [clip(csf, c) for c in t['m_AnimationClips']]
            new['m_AnimationClips'] = [c[0] for c in clips]
            bound = sum(c[1] for c in clips)
            return (sh.add('AnimatorController', new) if bound else 0), bound

        def animator(go, ctrl):
            a = s.template('Animator')
            a.update(m_Enabled=1, m_Avatar=dict(NULL), m_Controller=sc.shared_ref(ctrl), m_CullingMode=0, m_UpdateMode=1,
                     m_ApplyRootMotion=False)
            aid = sc.add_component(go, 'Animator', a)
            tracker = s.template('MonoBehaviour', 'ReplayTracker')
            tracker['m_RecordProperties']['m_AnimatorProperty'] = {'m_Animator': pptr(aid), 'm_isSelfUpdate': 0}
            sc.add_component(go, 'MonoBehaviour', tracker, 'ReplayTracker')
            return aid

        # ---- the Mania hierarchy
        holder = sc.new_object('mania', root)
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        bananas, goals, start_node = [], [], None
        stats = {'renderers': 0, 'collision_parts': 0, 'triangles': 0, 'skipped': {}}

        def skip(what):
            stats['skipped'][what] = stats['skipped'].get(what, 0) + 1

        # a node with a LODGroup has one child per detail level: only the nearest one is drawn here
        far_levels = set()
        for n in m.nodes.values():
            lod = n.component('LODGroup')
            if lod:
                for level in lod[2].get('m_LODs', [])[1:]:
                    for r in level.get('renderers', []):
                        far_levels.add(r['renderer']['m_PathID'])
        bumpers, go_of = [], {}
        seesaws, seesaw_parts, conveyors = [], {}, []
        has_part, moving_roots = set(), set()

        def add_part(go, n, data, flags):
            """Rumble's CollisionStagePart on go, from the Mania part data `data` (in node n's frame)."""
            nonlocal lo, hi
            conv, plo, phi = collision_part(data, sh.template('MonoBehaviour', 'CollisionStageData')['part'])
            d = sh.template('MonoBehaviour', 'CollisionStageData')
            d['m_Name'], d['part'] = 'mania_' + n.name, conv
            did = sh.add('MonoBehaviour', d, 'CollisionStageData')
            p = s.template('MonoBehaviour', 'CollisionStagePart')
            p.update(isPhysical=1, isTrigger=int(bool(flags.get('isTrigger', 0))), isDynamic=int(bool(flags.get('isDynamic', 0))),
                     priority=0, layerMask=10, isDebugSelected=0, isItem=0, m_CollisionStage=sc.shared_ref(did), m_CullingScale=1.0)
            sc.add_component(go, 'MonoBehaviour', p, 'CollisionStagePart')
            has_part.add(go)
            stats['collision_parts'] += 1
            stats['triangles'] += len(conv['triangle'])
            w = world_matrix(n, m.root)
            for cx in (plo[0], phi[0]):
                for cy in (plo[1], phi[1]):
                    for cz in (plo[2], phi[2]):
                        p3 = (w @ np.array([cx, cy, cz, 1.0]))[:3]
                        lo, hi = np.minimum(lo, p3), np.maximum(hi, p3)

        def copy_node(n, parent, visual):
            nonlocal lo, hi, start_node
            kinds = {c[0] for c in n.components}
            if 'MgGoalModel' in kinds:              # Mania's goal model: Rumble's own goal stands there instead
                return
            if 'MgGoalColi' in kinds:
                goals.append((n, parent))
                return
            if not visual and n.name == 'START' and start_node is None:
                start_node = n
            if n.name in ('NODISP_FALL', 'RINGOUT'):
                return
            go = sc.new_object(n.name, parent, n.pos, n.rot, n.scale, n.active)
            go_of[n.id] = go
            mf, mr = n.component('MeshFilter'), n.component('MeshRenderer')
            if visual and mf and mr and mf[2]['m_Mesh']['m_PathID'] and mr[1] not in far_levels:
                sc.add_component(go, 'MeshFilter', {'m_Mesh': sc.shared_ref(mesh(m.main, mf[2]['m_Mesh'])['m_PathID'])})
                r = s.template('MeshRenderer')
                r['m_Enabled'] = bool(mr[2]['m_Enabled'])
                r['m_CastShadows'], r['m_ReceiveShadows'] = 0, 1
                r['m_Materials'] = [sc.shared_ref(material(m.main, x)['m_PathID']) for x in mr[2]['m_Materials']]
                r['m_StaticBatchInfo'] = {'firstSubMesh': 0, 'subMeshCount': 0}
                r['m_StaticBatchRoot'] = dict(NULL)
                sc.add_component(go, 'MeshRenderer', r)
                stats['renderers'] += 1
            part = n.component('CollisionStagePart')
            above = n.parent
            if part and not visual and above is not None and above.component('MgSeesaw') and not above.component('CollisionStagePart'):
                seesaw_parts.setdefault(above.id, []).append(n)     # becomes one part on the seesaw itself (below)
            elif part and not visual:
                data = m.get(m.main, part[2]['m_CollisionStage'])
                if data is not None and data[1]['part']['triangle']:
                    add_part(go, n, data[1]['part'], part[2])
            if not visual and n.component('CollisionBumper'):
                bumpers.append((n, go))
            if not visual and n.component('MgSeesaw'):
                seesaws.append((n, go))
            if not visual and n.component('MgConveyer'):
                conveyors.append((n, go))
            banana = n.component('BananaPos')
            if banana and not visual:
                bananas.append((go, banana[2]['m_Kind']))
            for kind in kinds - {'Transform', 'MeshFilter', 'MeshRenderer', 'CollisionStagePart', 'BananaPos', 'Animator', 'GravityTilt',
                                 'MonoBehaviour', 'CollisionBumper', 'Bumper', 'LODGroup', 'MgStageSwitch', 'CollisionSwitchUpper',
                                 'MgTRSSync', 'StageMovObjManager', 'MgStageSwitchManager', 'MainGameStage', 'MgSeesaw', 'MgConveyer'}:
                skip(kind)
            for c in n.children:
                copy_node(c, go, visual)
            return go

        behavior_go = copy_node(m.behavior, holder, True) if m.behavior is not None else None
        collision_go = copy_node(m.collision, holder, False) if m.collision is not None else None
        # other children of the stage root are drawn things kept apart from the stage's tilt group (the bumper models)
        for c in m.root.children:
            if c is not m.behavior and c is not m.collision:
                copy_node(c, holder, True)

        # ---- bumpers: the same sphere and push as in Mania, on Rumble's bumper classes; the drawn bumper is the
        # node named <collision node>_INS under Behavior
        if bumpers:
            sc.import_script(self.aa, 'CollisionBumper')
            sc.import_script(self.aa, 'MgBumper')
            drawn = {s.get(g)['m_Name']: g for g in list(sc.tr_of_go)}
            for n, go in bumpers:
                src = n.component('CollisionBumper')[2]
                cb = s.template('MonoBehaviour', 'CollisionBumper')
                cb.update(isPhysical=1, isTrigger=0, isDynamic=0, priority=0, layerMask=4, isDebugSelected=0, isItem=0,
                          m_Globe=copy.deepcopy(src['m_Globe']), m_BumperPower=src['m_BumperPower'])
                sc.add_component(go, 'MonoBehaviour', cb, 'CollisionBumper')
                mb = s.template('MonoBehaviour', 'MgBumper')
                mb['m_RotationRoot'] = pptr(sc.tr_of_go[drawn.get(n.name + '_INS', go)])
                sc.add_component(go, 'MonoBehaviour', mb, 'MgBumper')
                tr = s.template('MonoBehaviour', 'ReplayTracker')         # Rumble's bumpers carry one (on the model)
                tr['m_RecordProperties']['m_AnimatorProperty'] = {'m_Animator': dict(NULL), 'm_isSelfUpdate': 0}
                sc.add_component(go, 'MonoBehaviour', tr, 'ReplayTracker')
            stats['bumpers'] = len(bumpers)

        def tracker(go):                                         # Rumble's gimmicks carry a ReplayTracker
            tr = s.template('MonoBehaviour', 'ReplayTracker')
            tr['m_RecordProperties']['m_AnimatorProperty'] = {'m_Animator': dict(NULL), 'm_isSelfUpdate': 0}
            sc.add_component(go, 'MonoBehaviour', tr, 'ReplayTracker')

        # ---- seesaws. Rumble's MgSeesaw turns its own object and is told about a hit by the collision part of
        # that same object (MgSeesaw.OnPostCollide looks for hits whose shape is on its GameObject). Mania's seesaw
        # is an empty node over two parts (the plank and the axle), so the two are made one part on the node.
        made = 0
        for n, go in seesaws:
            inv = np.linalg.inv(world_matrix(n, m.root))
            pieces = []
            for ch in seesaw_parts.get(n.id, []):
                data = m.get(m.main, ch.component('CollisionStagePart')[2]['m_CollisionStage'])
                if data is not None and data[1]['part']['triangle']:
                    pieces.append((data[1]['part'], inv @ world_matrix(ch, m.root)))
            if pieces:
                add_part(go, n, merged_part(pieces), {})
            if go not in has_part:
                skip('MgSeesaw')
                continue
            if not made:
                sc.import_script(self.aa, 'MgSeesaw')
            src = n.component('MgSeesaw')[2]
            ms = s.template('MonoBehaviour', 'MgSeesaw')
            ms.update(momentFactor=src['momentFactor'], frictionFactor=src['frictionFactor'], restoreFactor=src['restoreFactor'])
            sc.add_component(go, 'MonoBehaviour', ms, 'MgSeesaw')
            tracker(go)
            moving_roots.add(go)
            made += 1
        if seesaws:
            stats['seesaws'] = made

        # ---- conveyors: MgConveyer next to its collision part, the same speed vector
        made = 0
        for n, go in conveyors:
            if go not in has_part:
                skip('MgConveyer')
                continue
            if not made:
                sc.import_script(self.aa, 'MgConveyer')
            mc = s.template('MonoBehaviour', 'MgConveyer')
            mc['m_StaticSpeed'] = copy.deepcopy(n.component('MgConveyer')[2]['m_StaticSpeed'])
            sc.add_component(go, 'MonoBehaviour', mc, 'MgConveyer')
            moving_roots.add(go)
            made += 1
        if conveyors:
            stats['conveyors'] = made

        # ---- moving parts. Mania animates the Collision tree only and copies each moving node's transform to other
        # objects every frame: to its drawn twin (StageMovObjManager.m_info: animationTRS -> meshTRS) and to things
        # that ride on it (MgTRSSync: source -> targets; a switch on a moving floor). Here each such target is hung
        # under its source instead, keeping its place, so one Animator on the Collision tree moves everything.
        pairs = []
        mov = m.root.component('StageMovObjManager')
        for info in (mov[2].get('m_info', []) if mov else []):
            pairs.append((info['animationTRS']['m_PathID'], info['meshTRS']['m_PathID']))
        for n in m.nodes.values():
            sync = n.component('MgTRSSync')
            if sync:
                pairs += [(sync[2]['m_srcTransform']['m_PathID'], d['m_PathID']) for d in sync[2]['m_dstTransformList']]
        attached = set()
        for src_tr, dst_tr in pairs:
            a, b = m.by_transform.get(src_tr), m.by_transform.get(dst_tr)
            if a is None or b is None or a is b or a.id not in go_of or b.id not in go_of or b.id in attached:
                continue
            up = a
            while up is not None and up is not b:
                up = up.parent
            if up is b:                              # the target is above its source: leave it
                continue
            rel = np.linalg.inv(world_matrix(a, m.root)) @ world_matrix(b, m.root)
            scale = np.linalg.norm(rel[:3, :3], axis=0)
            if (scale < 1e-9).any():
                continue
            axes = rel[:3, :3] / scale
            sc.set_transform(go_of[b.id], rel[:3, 3], quat_from_axes(axes[:, 0], axes[:, 1], axes[:, 2]), go_of[a.id], scale)
            attached.add(b.id)
        stats['attached'] = len(attached)
        animators = []
        man = m.collision.component('Animator') if m.collision is not None else None
        if man and collision_go:
            ctrl, bound = controller(m.main, man[2]['m_Controller'])
            if ctrl:
                animators.append(animator(collision_go, ctrl))
            stats['animated_bindings'] = bound

        # ---- switches. Rumble's switch classes are Mania's with other names: MgStageSwitchManager ->
        # MgStageSwitchController (the Animator, the switches, switch class -> the animator parameters it drives),
        # MgStageSwitch -> MgSwitch (what the switch does: StageAnimation.eState 1 fast rewind, 2 reverse, 3 stop,
        # 4 play, 5 fast forward; its class), CollisionSwitchUpper (the cylinder that is pressed). Rumble's
        # controller reads the class of each animator layer from the layer's name with the same pattern Mania's
        # names have (class<N>_<A>to<B>_...).
        mgr = m.root.component('MgStageSwitchManager')
        switches = [n for n in m.nodes.values() if n.id in go_of and n.component('MgStageSwitch')
                    and n.component('MgStageSwitch')[2]['m_StageSwitchManager']['m_PathID']]
        if mgr and switches and animators:
            for cls in ('MgStageSwitchController', 'MgSwitch', 'CollisionSwitchUpper'):
                sc.import_script(self.aa, cls)
            on = sc.import_asset(self.aa, SWITCH_CLIPS[0], 'AnimationClip', SWITCH_CLIPS[1])
            off = sc.import_asset(self.aa, SWITCH_CLIPS[0], 'AnimationClip', SWITCH_CLIPS[2])
            ctl = s.template('MonoBehaviour', 'MgStageSwitchController')
            ctl['m_Animator'] = pptr(animators[0])
            ctl['m_SwitchList'] = []
            ctl['m_ClassIdToParamNameDict'] = {'m_EntryList': [{'m_Key': e['Key'], 'm_Value': list(e['Value'])}
                                                                for e in mgr[2]['m_ClassIdToParamNameDict']['list']]}
            ctl_id = sc.add_component(collision_go, 'MonoBehaviour', ctl, 'MgStageSwitchController')
            for n in switches:
                src = n.component('MgStageSwitch')[2]
                sw = s.template('MonoBehaviour', 'MgSwitch')
                sw.update(m_SwitchType=src['m_State'], m_ClassId=src['m_ClassId'], m_SerialId=src['m_SerialId'],
                          m_isTurnOnDefault=src['m_isTurnOnDefault'], m_StageSwitchController=pptr(ctl_id), m_Animators=[],
                          m_OnClip=sc.shared_ref(on), m_OffClip=sc.shared_ref(off), m_TrsFollow=dict(NULL))
                ctl['m_SwitchList'].append(pptr(sc.add_component(go_of[n.id], 'MonoBehaviour', sw, 'MgSwitch')))
                cyl = n.component('CollisionSwitchUpper')
                rad, height = (cyl[2]['m_CylinderRadius'], cyl[2]['m_CylinderHeight']) if cyl else (0.9, 0.7)
                cu = s.template('MonoBehaviour', 'CollisionSwitchUpper')
                cu.update(isPhysical=0, isTrigger=1, isDynamic=0, priority=0, layerMask=1, isDebugSelected=0, isItem=0)
                cu['m_Cylinder'] = {'pos': v3((0.0, 0.4, 0.0)), 'rad': float(rad), 'height': float(max(height, 0.7)), 'rot': q4((0, 0, 0, 1))}
                sc.add_component(go_of[n.id], 'MonoBehaviour', cu, 'CollisionSwitchUpper')
                # MgSwitch.Awake takes the ReplayTracker of its own object and registers with it
                tr = s.template('MonoBehaviour', 'ReplayTracker')
                tr['m_RecordProperties']['m_RecordFlags'] = [1] + [0] * (len(tr['m_RecordProperties']['m_RecordFlags']) - 1)
                tr['m_RecordProperties']['m_AnimatorProperty'] = {'m_Animator': dict(NULL), 'm_isSelfUpdate': 0}
                sc.add_component(go_of[n.id], 'MonoBehaviour', tr, 'ReplayTracker')
            mgs['m_StageSwitchControllers'] = [pptr(ctl_id)]
            stats['switches'] = len(switches)
        if not np.isfinite(lo).all():
            lo, hi = np.zeros(3), np.zeros(3)

        # ---- goals: the template's goal at each Mania goal
        goal_colis = []
        for i, (n, parent) in enumerate(goals):
            g = goal0 if i == 0 else sc.clone(goal0, root)
            sc.set_transform(g, n.pos, qmul(n.rot, Y180), parent)
            goal_colis.append(pptr(sc.component(g, 'MonoBehaviour', 'MgGoalColi')))
        if not goals:
            sc.delete(goal0)

        # ---- what the Animator moves, seesaws and conveyors get the tag "StgMot", with everything under them. Rumble's collision shapes look
        # for that tag on their parents when they wake (CollisionShapeBase.Awake); without it a shape is taken for
        # a still one and keeps colliding where it stood when the stage was loaded.
        tagged = 0
        if collision_go and (animators or moving_roots):
            def tag(go, path, moving):
                nonlocal tagged
                moving = (moving or go in moving_roots
                          or bool(animators) and (zlib.crc32(path.encode('utf-8')) & 0xffffffff) in animated_paths)
                if moving:
                    s.get(go)['m_Tag'] = TAG_STGMOT
                    tagged += 1
                for c in sc.children(go):
                    tag(c, (path + '/' if path else '') + sc.name(c), moving)
            tag(collision_go, '', False)
        stats['moving_objects'] = tagged

        # ---- start: Mania's START is the ball's centre, Rumble's the ground under it
        if start_node is not None:
            w = world_matrix(start_node, m.root)
            pos = w[:3, 3] - np.array([0.0, 0.5, 0.0])
            sc.set_transform(start, pos, qmul(world_rotation(start_node, m.root), Y180))

        # ---- MainGameStage
        centre, extent = (lo + hi) / 2, (hi - lo) / 2
        mgs['m_GoalColiList'] = goal_colis
        mgs['m_StageAnimators'] = [pptr(a) for a in animators]
        mgs['m_BananaTransformList'] = [{'transform': pptr(sc.tr_of_go[g]), 'kind': int(k), 'isBotIgnore': 0, 'isNoShadow': 0}
                                        for g, k in bananas if k in (0, 1)]
        mgs['m_MeshBounds'] = {'m_Center': v3(centre), 'm_Extent': v3(extent)}
        fb = m.info.get('m_FalloutBounds')
        ring = float(m.info.get('m_ringoutY', lo[1] - 10.0))
        if ring < -1e5:                              # some stages have no fall-out height (-FLT_MAX): below the lowest floor
            ring = float(lo[1] - 15.0)
        if fb and max(fb['m_Extent'].values()) > 0:
            mgs['m_FalloutBounds'] = {'m_Center': copy.deepcopy(fb['m_Center']), 'm_Extent': copy.deepcopy(fb['m_Extent'])}
        else:
            mgs['m_FalloutBounds'] = {'m_Center': v3(centre + np.array([0, 100.0, 0])), 'm_Extent': v3(extent + np.array([80.0, 150.0, 80.0]))}
        mgs['m_RingoutY'] = ring
        for g in bounds_holder:
            for c in sc.children(g):
                b = sc.component(c, 'MonoBehaviour', 'BeginningBounds')
                if b:
                    sc.set_transform(c, centre)
                    s.get(b)['m_Bounds'] = {'m_Center': v3((0, 0, 0)), 'm_Extent': v3(np.maximum(extent, 1.0))}

        size = sc.save(out_path, *(identity or (None, None, None)))
        stats.update(goals=len(goals), bananas=len(mgs['m_BananaTransformList']), textures=len(tex_ids), materials=len(mat_ids),
                     meshes=len(mesh_ids), bytes=size, bounds=(lo.round(2).tolist(), hi.round(2).tolist()), ringout=ring,
                     has_start=start_node is not None)
        say(stats)
        return stats


if __name__ == '__main__':
    import sys
    conv = Converter(sys.argv[1], sys.argv[2])
    print(conv.convert(sys.argv[3], sys.argv[4]))
