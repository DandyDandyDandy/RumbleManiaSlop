"""classic_chara.py - classic-style monkeys from the user's Banana Mania install, fitted to Banana Rumble's rig.

Banana Mania's "Classic Character Pack" holds classic-look models of the six monkeys (bundle
player_chara_<id><name>cstyle: meshes, skeleton, eye textures; the other textures are PNG files under
DlcRoot/DlcDxClassicStyle). The two games share nothing at run time (different skeleton, animations, shaders), so
each classic model is rebuilt as an alternative set of the Rumble character's own asset bundles:

  * every classic vertex is put into its rest pose in Rumble's space (the classic rig faces -Z, Rumble's +Z, same
    scale; the neck joints are made to coincide), limb joints are shifted onto Rumble's joints, and the vertex is
    re-bound to the matching Rumble bones with Rumble's bind poses. Rumble's animations then drive the geometry.
  * the classic body goes into the Mesh objects used by the `*_cstm_body01` renderers, the classic head into the
    `headNN` / `*_LOD_head` ones; all other renderers of the prefabs (hands, shoes, ears, mouths, ...) lose
    their mesh. Rumble's material objects keep their shader and get the classic textures.

Output: work\\unity\\classic\\<name>\\<same relative path as in the aa tree>; `install` copies that to
run\\classic\\<name>\\, where the runtime (port\\runtime\\classic.c) picks it up for the characters switched to
classic. The game's own files are never modified.
usage: python classic_chara.py build [name ...]     names: aiai meemee baby gongon yanyan doctor (default all)
       python classic_chara.py install
"""
import os, sys, glob, shutil, struct, zlib
import numpy as np
import UnityPy
from UnityPy.enums import TextureFormat
from UnityPy.helpers.MeshHelper import MeshHandler
from PIL import Image

# Folders, set by configure(): AA is the built game's StreamingAssets\aa folder (read only; ORIG is the same folder,
# kept as a name of its own because the code reads the game's unchanged bundles through it), OUT a work folder for
# the per-prefab builds of this file's own `build` command, MANIA Banana Mania's StreamingAssets folder.
AA = ORIG = OUT = RUN = MANIA = MANIA_AB = MANIA_TEX = None


def configure(aa, mania_dir, work):
    global AA, ORIG, OUT, RUN, MANIA, MANIA_AB, MANIA_TEX
    AA = ORIG = aa
    OUT = os.path.join(work, 'classic')
    RUN = os.path.join(work, 'classic_run')
    MANIA = os.path.join(mania_dir, 'smbbm_Data', 'StreamingAssets')
    MANIA_AB = os.path.join(MANIA, 'StandaloneWindows64', 'AssetBundles')
    MANIA_TEX = os.path.join(MANIA, 'DlcRoot', 'DlcDxClassicStyle', 'Textures')


def configure_from_env():
    """For the stand-alone tools of this folder: the built game's asset folder and the Banana Mania install the
    setup would use (input\\mania.txt, BANANA_MANIA, or the Steam library)."""
    repo = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    sys.path.insert(0, os.path.join(repo, 'port'))
    sys.path.insert(0, os.path.join(repo, 'setup'))
    import paths
    import setup as rs_setup
    mania = rs_setup.find_mania(rs_setup.mania_config())
    if mania is None:
        raise SystemExit('Banana Mania was not found: name its folder in input\\mania.txt (path=...)')
    configure(os.path.join(str(paths.GAME), paths.NAME + '_Data', 'StreamingAssets', 'aa'), str(mania),
              str(paths.BUILD / 'mania_work'))


def available(mania_dir):
    """True when the install has the Classic Character Pack (its models and textures)."""
    sa = os.path.join(mania_dir, 'smbbm_Data', 'StreamingAssets')
    return (os.path.isdir(os.path.join(sa, 'DlcRoot', 'DlcDxClassicStyle', 'Textures'))
            and all(os.path.exists(os.path.join(sa, 'StandaloneWindows64', 'AssetBundles', c[0])) for c in CHARS.values()))

# classic bone -> Rumble bone. `{s}` is the side (classic _l/_r -> Rumble _L/_R). Finger a/b/c joints follow the
# Rumble finger chain as deep as it goes. Bones not listed inherit their parent's mapping.
BONE_MAP = {
    'hara': 'Hips', 'kosi': 'Hips', 'mune': 'Chest', 'rucksack': 'Chest', 'tail': 'TailRoot', 'tail_a': 'TailRoot', 'kao': 'Head',
    'waki_{s}': 'Shoulder_{S}', 'kata_{s}': 'UpperArm_{S}', 'nino_{s}': 'UpperArm_{S}', 'ude_{s}': 'LowerArm_{S}', 'te_{s}': 'Hand_{S}',
    'momo_{s}': 'UpperLeg_{S}', 'sune_{s}': 'LowerLeg_{S}', 'asi_{s}': 'Foot_{S}', 'toe_{s}': 'Toes_{S}',
}
FINGERS = {'hit': 'Index', 'nak': 'Middle', 'kus': 'Ring', 'koy': 'Ring', 'oya': 'Thumb'}
# classic bones whose joint is moved onto the mapped Rumble joint (the others keep the shift of their parent)
JOINT_FIT = ('kata', 'ude', 'te', 'momo', 'sune', 'asi', 'toe', 'tail', 'tail_a')

# name: (Banana Mania bundle, classic texture prefix, Rumble character number, Rumble folder/asset name)
CHARS = {
    'aiai': ('player_chara_0102aiaicstyle', 'cs_aiai', 1, 'aiai'),
    'meemee': ('player_chara_0202meemeecstyle', 'cs_meemee', 2, 'meemee'),
    'baby': ('player_chara_0303babycstyle', 'cs_baby', 3, 'baby'),
    'gongon': ('player_chara_0402gongoncstyle', 'cs_gongon', 4, 'gongon'),
    'yanyan': ('player_chara_0502yanyancstyle', 'cs_annan', 5, 'yanyan'),
    'doctor': ('player_chara_0602doctorcstyle', 'cs_dr', 6, 'doctor'),
}

def config(name):
    mania, tex, num, br = CHARS[name]
    pdir = os.path.join('Switch', 'chara_model_assets_chara', 'model', '%02d%s' % (num, br))
    src = os.path.join(ORIG, pdir) if os.path.isdir(os.path.join(ORIG, pdir)) else os.path.join(AA, pdir)
    return dict(name=name, mania=mania, tex=tex,
                prefabs=[os.path.join(pdir, f) for f in sorted(os.listdir(src)) if f.endswith('.prefab.bundle')],
                design=os.path.join('Switch', 'manual_additions_assets_design', 'chara', 'ch_%03d_%s.bundle' % (num, br)))

# ------------------------------------------------------------------------------------------------ helpers
def trs(t):
    p, q, s = t.m_LocalPosition, t.m_LocalRotation, t.m_LocalScale
    x, y, z, w = q.x, q.y, q.z, q.w
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * np.array([s.x, s.y, s.z])
    M[:3, 3] = [p.x, p.y, p.z]
    return M

class Node:
    def __init__(self, tr, parent, W):
        self.tr, self.parent, self.W = tr, parent, W
        self.name = tr.m_GameObject.read().m_Name
        self.path_id = tr.object_reader.path_id
        self.children = []
    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()
    def find(self, name):
        return next((n for n in self.walk() if n.name == name), None)
    def by_path(self, path):    # node at `path` below this one, or None
        n = self
        for part in path.split('/'):
            n = next((c for c in n.children if c.name == part), None)
            if n is None: return None
        return n
    def path_from(self, top):   # path below `top`
        parts, n = [], self
        while n is not top and n is not None:
            parts.append(n.name); n = n.parent
        return '/'.join(reversed(parts))

def hierarchy(env, rootname=None):
    def build(tr, parent, PW):
        n = Node(tr, parent, PW @ trs(tr))
        n.children = [build(c.read(), n, n.W) for c in tr.m_Children]
        return n
    for o in env.objects:
        if o.type.name == 'Transform':
            tr = o.read()
            if not tr.m_Father.m_PathID and (rootname is None or tr.m_GameObject.read().m_Name == rootname):
                return build(tr, None, np.eye(4))
    raise SystemExit('no root %s' % rootname)

def mat_from_dict(d):
    return np.array([[d['e%d%d' % (r, c)] for c in range(4)] for r in range(4)])
def mat_to_dict(M):
    return {'e%d%d' % (r, c): float(M[r, c]) for r in range(4) for c in range(4)}

# ------------------------------------------------------------------------------------------------ classic side
def load_classic(cfg, posed=True):
    """-> {mesh name: dict(pos, nrm, uv, tris[list per submesh], bone_names[list], w[n,4], bi[n,4])}, skeleton root.
    Positions/normals are in the classic prefab's root space at rest (skinned through the bind poses)."""
    env = UnityPy.load(os.path.join(MANIA_AB, cfg['mania']))
    root = hierarchy(env)
    by_tr = {n.path_id: n for n in root.walk()}
    pose = finger_pose(root, hand_spec(cfg['name'])) if posed else {}
    out = {}
    for o in env.objects:
        if o.type.name != 'SkinnedMeshRenderer':
            continue
        smr = o.read()
        mesh = smr.m_Mesh.read()
        h = MeshHandler(mesh); h.process()
        n = h.m_VertexCount
        pos = np.array(h.m_Vertices, dtype=np.float64).reshape(n, 3)
        nrm = np.array(h.m_Normals, dtype=np.float64).reshape(n, 3)
        uv = np.array(h.m_UV0, dtype=np.float64).reshape(n, -1)[:, :2]
        bi = np.array(h.m_BoneIndices, dtype=np.int64).reshape(n, -1)
        bw = np.array(h.m_BoneWeights, dtype=np.float64).reshape(n, -1) if h.m_BoneWeights is not None and len(h.m_BoneWeights) else np.ones((n, 1))
        if bi.shape[1] < 4: bi = np.pad(bi, ((0, 0), (0, 4 - bi.shape[1])))
        if bw.shape[1] < 4: bw = np.pad(bw, ((0, 0), (0, 4 - bw.shape[1])))
        bones = [by_tr[b.m_PathID] for b in smr.m_Bones]
        binds = [np.array(b).reshape(4, 4) if not hasattr(b, 'e00') else np.array([[getattr(b, 'e%d%d' % (r, c)) for c in range(4)] for r in range(4)]) for b in mesh.m_BindPose]
        skin = [pose.get(bones[i].name, np.eye(4)) @ bones[i].W @ binds[i] for i in range(len(bones))]
        P = np.zeros((n, 3)); N = np.zeros((n, 3))
        hp = np.c_[pos, np.ones(n)]
        for k in range(4):
            for b in np.unique(bi[:, k]):
                sel = (bi[:, k] == b) & (bw[:, k] > 0)
                if not sel.any(): continue
                M = skin[b]
                P[sel] += bw[sel, k:k + 1] * (hp[sel] @ M.T)[:, :3]
                N[sel] += bw[sel, k:k + 1] * (nrm[sel] @ M[:3, :3].T)
        N /= np.maximum(np.linalg.norm(N, axis=1, keepdims=True), 1e-9)
        role = mesh.m_Name.rsplit('_', 1)[-1] if not mesh.m_Name.endswith('_eye_expressions') else 'expr'   # body, face, expr
        out[role] = dict(pos=P, nrm=N, uv=uv, tris=[np.array(t).reshape(-1) for t in h.get_triangles()], bones=bones, w=bw, bi=bi,
                         mats=[m.read().m_Name for m in smr.m_Materials])
    cfg['_bundle_tex'] = {o.peek_name(): o for o in env.objects if o.type.name == 'Texture2D'}
    return out, root

# The classic models are stored with flat hands and straight fingers; in Banana Mania their animations curl them.
# Here the hand follows Rumble's hand bone as one piece, so the hand is posed once before the mesh is taken over.
# A hand pose is {'wrist': [x, y, z], 'fingers': {finger: [[curl, spread, twist] x 3 joints]}} in degrees, for the
# left hand (the right hand mirrors it). It comes from classic_hands.json (next to this file) when that file has the
# character (made with the hand poser, port\tools\hand_poser.html), else from the defaults below.
#   curl    turns the joint about the horizontal axis across the finger, towards the palm side (down)
#   spread  turns it about the vertical axis (positive: towards the thumb side, i.e. forwards)
#   twist   turns it about the finger's own direction
#   wrist   turns the whole hand about the wrist: x = along the arm, y = vertical, z = front-back
FINGERS_ORDER = ('oya', 'hit', 'nak', 'kus', 'koy')            # thumb, index, middle, ring, little
FINGER_CURL = {'hit': (30, 45, 35), 'nak': (35, 50, 35), 'kus': (40, 50, 35), 'koy': (45, 50, 35), 'oya': (30, 25, 20)}
FINGER_FIST = {'hit': (85, 95, 75), 'nak': (85, 95, 75), 'kus': (85, 95, 75), 'koy': (85, 95, 75), 'oya': (45, 60, 45)}
FISTS = ('baby', 'gongon', 'yanyan')   # these three close their hands into fists (the user's preference); the others stay relaxed
HANDS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'classic_hands.json')

def default_hand_spec(name):
    curl = FINGER_FIST if name in FISTS else FINGER_CURL
    return dict(wrist=[0, 0, 0], fingers={f: [[curl[f][k], 0, 0] for k in range(3)] for f in FINGERS_ORDER})

def hand_spec(name):
    if os.path.exists(HANDS_FILE):
        import json
        saved = json.load(open(HANDS_FILE, encoding='utf-8'))
        if name in saved:
            return saved[name]
    return default_hand_spec(name)

def _rot(axis, deg, pivot):
    a = np.radians(deg); x, y, z = axis
    K = np.array([[0, -z, y], [z, 0, -x], [-y, x, 0]])
    R = np.eye(4); R[:3, :3] = np.eye(3) + np.sin(a) * K + (1 - np.cos(a)) * (K @ K)
    T = np.eye(4); T[:3, 3] = pivot
    Ti = np.eye(4); Ti[:3, 3] = -np.asarray(pivot)
    return T @ R @ Ti

def finger_chains(root, side):
    """-> wrist node, {finger: [joint nodes a, b, c]} of one side ('l' or 'r')"""
    out = {}
    for f in FINGERS_ORDER:
        n = root.find('%s_a_%s' % (f, side))
        if n is None: continue
        chain = [n]
        while chain[-1].children and len(chain) < 3: chain.append(chain[-1].children[0])
        out[f] = chain
    return root.find('te_' + side), out

def finger_pose(root, spec):
    """-> {bone name: 4x4 transform, in the classic root space, to apply to that bone's rest matrix}.
    The same arithmetic is in port\tools\hand_poser.html (function poseMatrices): keep the two in step."""
    pose = {}
    for side in ('l', 'r'):
        wrist, chains = finger_chains(root, side)
        if wrist is None: continue
        m = 1.0 if side == 'l' else -1.0                 # the right hand is the mirror image in x
        wp = wrist.W[:3, 3]
        wx, wy, wz = spec.get('wrist', [0, 0, 0])
        H = _rot((0, 0, 1), m * wz, wp) @ _rot((0, 1, 0), m * wy, wp) @ _rot((1, 0, 0), wx, wp)
        for d in wrist.walk(): pose[d.name] = H
        for f, chain in chains.items():
            d = (chain[1].W[:3, 3] - chain[0].W[:3, 3]) if len(chain) > 1 else np.array([m, 0.0, 0.0])
            d = np.array([d[0], 0.0, d[2]]); d /= max(np.linalg.norm(d), 1e-9)
            curl_axis = np.cross(d, [0.0, -1.0, 0.0]); curl_axis /= max(np.linalg.norm(curl_axis), 1e-9)
            C = H
            for k, node in enumerate(chain):
                curl, spread, twist = spec['fingers'][f][k]
                p = node.W[:3, 3]
                C = C @ _rot((0, 1, 0), -m * spread, p) @ _rot(curl_axis, curl, p) @ _rot(d, m * twist, p)
                for dn in node.walk():                  # this joint and, until they get their own turn, all below it
                    pose[dn.name] = C
    return pose

def map_bone(name):
    """classic bone name -> (Rumble bone name, finger depth or None), or None when it has no own mapping."""
    side = name[-1] if name[-2:] in ('_l', '_r') else ''
    if side:
        base = name[:-2]
        if base[:3] in FINGERS and base[3:5] in ('_a', '_b', '_c'):
            # The classic hand has five straight fingers, Rumble's four with other proportions and poses:
            # following Rumble's finger bones tears the classic fingers apart, so the hand stays one piece.
            return 'Hand_' + side.upper(), None
        key = base + '_{s}'
        if key in BONE_MAP:
            return BONE_MAP[key].format(S=side.upper()), None
    return (BONE_MAP[name], None) if name in BONE_MAP else None

# ------------------------------------------------------------------------------------------------ fit
def fit(cm, classic_root, lod_root, anim_root, cfg):
    """classic mesh dict -> Rumble-space arrays bound to the bones of `anim_root` (one LOD subtree of the prefab)."""
    rot = np.diag([-1.0, 1.0, -1.0])               # half turn about Y: classic faces -Z, Rumble +Z
    D = np.array([0.0, anim_root.find('Head').W[1, 3] - classic_root.find('kao').W[1, 3], 0.0])   # necks coincide
    def target(cn):                                 # classic Node -> Rumble Node (walks up until something maps)
        n = cn
        while n is not None:
            m = map_bone(n.name)
            if m:
                t = anim_root.find(m[0])
                if t is None and m[1] is not None:  # LOD skeleton without fingers
                    t = anim_root.find('Hand_' + m[0][-1])
                if t is not None:
                    for _ in range(m[1] or 0):      # deeper finger joints
                        if t.children: t = t.children[0]
                    return t
            n = n.parent
        return anim_root.find('Hips')
    def shift(cn):                                  # joint correction of a classic bone (inherited from parents)
        n = cn
        while n is not None:
            base = n.name[:-2] if n.name[-2:] in ('_l', '_r') else n.name
            if base in JOINT_FIT:
                return target(n).W[:3, 3] - (rot @ n.W[:3, 3] + D)
            n = n.parent
        return np.zeros(3)
    bones = cm['bones']
    tgt = [target(b) for b in bones]
    mats = cm['mats']
    sh = np.array([shift(b) for b in bones])
    n = len(cm['pos'])
    pos = cm['pos'] @ rot.T + D
    nrm = cm['nrm'] @ rot.T
    for k in range(4):
        pos += cm['w'][:, k:k + 1] * sh[cm['bi'][:, k]]
    # merge weights per Rumble bone
    uniq = []
    for t in tgt:
        if t not in uniq: uniq.append(t)
    idx_of = np.array([uniq.index(t) for t in tgt])
    W = np.zeros((n, len(uniq)))
    for k in range(4):
        np.add.at(W, (np.arange(n), idx_of[cm['bi'][:, k]]), cm['w'][:, k])
    order = np.argsort(-W, axis=1)[:, :4]
    if order.shape[1] < 4: order = np.pad(order, ((0, 0), (0, 4 - order.shape[1])))
    w4 = np.take_along_axis(W, order, axis=1)
    w4 /= w4.sum(1, keepdims=True)
    order[w4 == 0] = 0
    tris = cm['tris']   # same winding rule as the game's own meshes (checked against their vertex normals)
    return dict(pos=pos, nrm=nrm, uv=cm['uv'], tris=tris, bones=uniq, w=w4, bi=order, mats=mats)

def rigid(fm, bone):
    """bind every vertex to one bone"""
    n = len(fm['pos'])
    w = np.zeros((n, 4)); w[:, 0] = 1
    return dict(fm, bones=[bone], w=w, bi=np.zeros((n, 4), dtype=np.int64))

# ------------------------------------------------------------------------------------------------ Rumble mesh writer
def tangents(pos, nrm, uv, tris):
    tan = np.zeros((len(pos), 3))
    t = tris.reshape(-1, 3)
    e1, e2 = pos[t[:, 1]] - pos[t[:, 0]], pos[t[:, 2]] - pos[t[:, 0]]
    d1, d2 = uv[t[:, 1]] - uv[t[:, 0]], uv[t[:, 2]] - uv[t[:, 0]]
    det = d1[:, 0] * d2[:, 1] - d2[:, 0] * d1[:, 1]
    det[np.abs(det) < 1e-12] = 1e-12
    tt = (e1 * d2[:, 1:2] - e2 * d1[:, 1:2]) / det[:, None]
    for k in range(3): np.add.at(tan, t[:, k], tt)
    tan -= nrm * (tan * nrm).sum(1, keepdims=True)
    ln = np.linalg.norm(tan, axis=1, keepdims=True)
    bad = ln[:, 0] < 1e-9
    tan[bad] = np.cross(nrm[bad], [0, 1, 0.001]); ln = np.linalg.norm(tan, axis=1, keepdims=True)
    return np.c_[tan / np.maximum(ln, 1e-9), np.ones(len(pos))]

def write_mesh(tt, fm, anim_root):
    """fill a Rumble Mesh typetree (layout of the game's own character meshes: stream 0 position/normal/tangent
    float, stream 1 uv0 half + uv1 float, stream 2 weights float + indices uint32; 16-bit indices)."""
    n = len(fm['pos'])
    alltris = np.concatenate(fm['tris'])
    tan = tangents(fm['pos'], fm['nrm'], fm['uv'], alltris)
    s0 = np.c_[fm['pos'], fm['nrm'], tan].astype('<f4').tobytes()
    s1 = b''.join(struct.pack('<2e2f', u, v, u, v) for u, v in fm['uv'])
    s2 = b''.join(fm['w'][i].astype('<f4').tobytes() + fm['bi'][i].astype('<u4').tobytes() for i in range(n))
    data = b''
    for s in (s0, s1, s2):
        data += b'\0' * (-len(data) % 16) + s
    vd = tt['m_VertexData']
    vd['m_VertexCount'] = n
    chans = [dict(stream=0, offset=0, format=0, dimension=0) for _ in range(14)]
    chans[0] = dict(stream=0, offset=0, format=0, dimension=3)
    chans[1] = dict(stream=0, offset=12, format=0, dimension=3)
    chans[2] = dict(stream=0, offset=24, format=0, dimension=4)
    chans[4] = dict(stream=1, offset=0, format=1, dimension=2)
    chans[5] = dict(stream=1, offset=4, format=0, dimension=2)
    chans[12] = dict(stream=2, offset=0, format=0, dimension=4)
    chans[13] = dict(stream=2, offset=16, format=10, dimension=4)
    vd['m_Channels'] = chans
    vd['m_DataSize'] = data if isinstance(vd['m_DataSize'], (bytes, bytearray)) else list(data)
    tt['m_StreamData'] = dict(offset=0, size=0, path='')
    ib = alltris.astype('<u2').tobytes()
    tt['m_IndexBuffer'] = ib if isinstance(tt['m_IndexBuffer'], (bytes, bytearray)) else list(ib)
    tt['m_IndexFormat'] = 0
    def aabb(p):
        lo, hi = p.min(0), p.max(0)
        return dict(m_Center=dict(zip('xyz', map(float, (lo + hi) / 2))), m_Extent=dict(zip('xyz', map(float, (hi - lo) / 2 + 1e-4))))
    subs, first = [], 0
    proto = tt['m_SubMeshes'][0]
    for t in fm['tris']:
        s = dict(proto)
        s.update(firstByte=first * 2, indexCount=len(t), topology=0, baseVertex=0, firstVertex=int(t.min()), vertexCount=int(t.max() - t.min() + 1), localAABB=aabb(fm['pos'][t]))
        subs.append(s); first += len(t)
    tt['m_SubMeshes'] = subs
    tt['m_LocalAABB'] = aabb(fm['pos'])
    binds = [np.linalg.inv(b.W) for b in fm['bones']]
    tt['m_BindPose'] = [mat_to_dict(B) for B in binds]
    tt['m_BoneNameHashes'] = [zlib.crc32(b.path_from(anim_root).encode()) for b in fm['bones']]
    tt['m_RootBoneNameHash'] = tt['m_BoneNameHashes'][0]
    ba = []
    hp = np.c_[fm['pos'], np.ones(n)]
    for i, B in enumerate(binds):
        sel = ((fm['bi'] == i) & (fm['w'] > 0)).any(1)
        if sel.any():
            lp = (hp[sel] @ B.T)[:, :3]
            ba.append(dict(m_Min=dict(zip('xyz', map(float, lp.min(0)))), m_Max=dict(zip('xyz', map(float, lp.max(0))))))
        else:
            ba.append(dict(m_Min=dict(x=0.0, y=0.0, z=0.0), m_Max=dict(x=0.0, y=0.0, z=0.0)))
    tt['m_BonesAABB'] = ba
    tt['m_VariableBoneCountWeights'] = dict(m_Data=type(tt['m_VariableBoneCountWeights']['m_Data'])())
    return aabb(fm['pos'])

# ------------------------------------------------------------------------------------------------ build
def merge(a, b):
    """two single-bone meshes into one (b's submeshes after a's)"""
    n = len(a['pos'])
    return dict(a, pos=np.r_[a['pos'], b['pos']], nrm=np.r_[a['nrm'], b['nrm']], uv=np.r_[a['uv'], b['uv']],
                tris=a['tris'] + [t + n for t in b['tris']], w=np.r_[a['w'], b['w']], bi=np.r_[a['bi'], b['bi']], mats=a['mats'] + b['mats'])

def classic_image(cfg, mat):
    """the picture a classic material shows: the DLC PNG of this character where there is one, else the PNG or the
    bundle texture the material's name points at. Eyes use the "normal" expression."""
    who, part = mat.split('_', 2)[1], mat.split('_', 2)[2]
    part = {'eye': 'eye_normal', 'eye_expressions': 'glass_normal', 'mouth2': 'mouth'}.get(part, part)
    for nm in ('%s_%s' % (cfg['tex'], part), 'cs_%s_%s' % (who, part)):
        f = os.path.join(MANIA_TEX, nm + '.png')
        if os.path.exists(f):
            return Image.open(f).convert('RGBA'), nm
        if nm in cfg['_bundle_tex']:
            return cfg['_bundle_tex'][nm].read().image.convert('RGBA'), nm
    raise SystemExit('%s: no texture for classic material %s' % (cfg['name'], mat))

# Shading of the classic materials (Rumble's Chara/ch_lit_toon). Every classic material takes the shading settings
# of the character's own Rumble body material (`ch_00N_body_mat`: its two shadow tints, rim light, specular and
# environment terms), so a classic monkey is lit like the Rumble one beside it and a decal is lit like the skin
# under it. The Rumble materials being reused each have their own settings (the costume's are tinted for denim, the
# face's for eyes), which is why they are not kept as they are. Normal and specular maps are dropped: they belong
# to Rumble's texture layout. A missing specular map reads as white, full shine on every pixel, so the specular
# term is switched off with it: under the strong front light of the online lobbies it bleached the whole monkey.
def shading_of(envd):
    for o in envd.objects:
        if o.type.name == 'Material' and o.peek_name().endswith('_body_mat'):
            sp = o.read_typetree()['m_SavedProperties']
            fl = dict(sp['m_Floats']); fl['_NormalStrength'] = 0.0
            fl['_SpecularStrength'] = 0.0       # no specular map means "shiny everywhere" (the shader's default is white)
            return fl, dict(sp['m_Colors'])
    raise SystemExit('no body material in the design bundle')

def bake_transparent(cfg, classic):
    """Classic eye (and glasses) materials are alpha-blended decals floating just above the face. Rumble's
    character shader has no cut-out or blended variant in the build, so each such texture is made opaque: every
    transparent texel takes the colour of the surface behind it (found by casting a ray from the decal into the
    model), blended by the texel's alpha. -> {classic material name: RGBA image}"""
    out = {}
    G = 256
    def tex_array(mat):
        img, _ = classic_image(cfg, mat)
        return np.asarray(img).astype(np.float64)
    for role, cm in classic.items():
        if role == 'expr' and cfg['name'] != 'doctor':   # expression overlays: only the doctor's (his glasses) are used
            continue
        for si, mat in enumerate(cm['mats']):
            if mat in out:
                continue
            A = tex_array(mat)
            if (A[..., 3] < 128).mean() < 0.01:
                continue
            # the surfaces a decal can lie on: the other opaque submeshes of its mesh; the glasses lie on the face
            behind = [(cm, j) for j in range(len(cm['tris'])) if j != si]
            if role == 'expr':
                behind += [(classic['face'], j) for j in range(len(classic['face']['tris']))]
            T, Tuv, Ttex = [], [], []
            texs = []
            for m2, j in behind:
                B = tex_array(m2['mats'][j])
                if (B[..., 3] < 128).mean() >= 0.01:
                    continue
                t = m2['tris'][j].reshape(-1, 3)
                T.append(m2['pos'][t]); Tuv.append(m2['uv'][t]); Ttex.append(np.full(len(t), len(texs))); texs.append(B)
            if not T:
                continue
            T, Tuv, Ttex = np.concatenate(T), np.concatenate(Tuv), np.concatenate(Ttex)
            # decal surface points on a G x G grid of its own texture space
            pts, dirs, cells = [], [], []
            for a, b, c in cm['tris'][si].reshape(-1, 3):
                uv = cm['uv'][[a, b, c]] * G
                x0, x1 = int(np.floor(uv[:, 0].min())), int(np.ceil(uv[:, 0].max()))
                y0, y1 = int(np.floor(uv[:, 1].min())), int(np.ceil(uv[:, 1].max()))
                xs, ys = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                d = (uv[1, 1] - uv[2, 1]) * (uv[0, 0] - uv[2, 0]) + (uv[2, 0] - uv[1, 0]) * (uv[0, 1] - uv[2, 1])
                if abs(d) < 1e-12: continue
                l0 = ((uv[1, 1] - uv[2, 1]) * (xs - uv[2, 0]) + (uv[2, 0] - uv[1, 0]) * (ys - uv[2, 1])) / d
                l1 = ((uv[2, 1] - uv[0, 1]) * (xs - uv[2, 0]) + (uv[0, 0] - uv[2, 0]) * (ys - uv[2, 1])) / d
                l2 = 1 - l0 - l1
                m = (l0 >= -0.02) & (l1 >= -0.02) & (l2 >= -0.02)
                if not m.any(): continue
                P = l0[m][:, None] * cm['pos'][a] + l1[m][:, None] * cm['pos'][b] + l2[m][:, None] * cm['pos'][c]
                N = cm['nrm'][a] + cm['nrm'][b] + cm['nrm'][c]
                pts.append(P); dirs.append(np.tile(-N / max(np.linalg.norm(N), 1e-9), (len(P), 1)))
                cells.append(np.c_[xs[m].astype(int) % G, ys[m].astype(int) % G])
            if not pts:
                continue
            pts, dirs, cells = np.concatenate(pts), np.concatenate(dirs), np.concatenate(cells)
            pts = pts - dirs * 0.02                     # start a little outside, in case the decal touches the skin
            fill = np.zeros((G, G, 3)); have = np.zeros((G, G), dtype=bool)
            e1, e2 = T[:, 1] - T[:, 0], T[:, 2] - T[:, 0]
            for k in range(0, len(pts), 256):           # Moeller-Trumbore, rays x triangles
                O, D = pts[k:k + 256, None, :], dirs[k:k + 256, None, :]
                h = np.cross(D, e2[None]); det = (e1[None] * h).sum(-1)
                ok = np.abs(det) > 1e-12
                inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
                sv = O - T[None, :, 0]
                u = (sv * h).sum(-1) * inv
                q = np.cross(sv, e1[None]); v = (D * q).sum(-1) * inv
                t = (e2[None] * q).sum(-1) * inv
                hit = ok & (u >= -1e-6) & (v >= -1e-6) & (u + v <= 1 + 1e-6) & (t > 0)
                t = np.where(hit, t, np.inf)
                best = t.argmin(1); got = np.isfinite(t[np.arange(len(best)), best])
                for r in np.nonzero(got)[0]:
                    ti = best[r]; uu, vv = u[r, ti], v[r, ti]
                    tuv = (1 - uu - vv) * Tuv[ti, 0] + uu * Tuv[ti, 1] + vv * Tuv[ti, 2]
                    B = texs[Ttex[ti]]
                    px = B[int(np.clip((1 - tuv[1] % 1.0) * B.shape[0], 0, B.shape[0] - 1)), int(np.clip((tuv[0] % 1.0) * B.shape[1], 0, B.shape[1] - 1)), :3]
                    cx, cy = cells[k + r]
                    fill[G - 1 - cy, cx] = px; have[G - 1 - cy, cx] = True
            if not have.any():
                continue
            # cells with no hit take the colour of the nearest cell that has one
            yy, xx = np.nonzero(have)
            ay, ax = np.nonzero(~have)
            if len(ay):
                for k in range(0, len(ay), 2048):
                    d2 = (ay[k:k + 2048, None] - yy[None]) ** 2 + (ax[k:k + 2048, None] - xx[None]) ** 2
                    j = d2.argmin(1)
                    fill[ay[k:k + 2048], ax[k:k + 2048]] = fill[yy[j], xx[j]]
            F = np.asarray(Image.fromarray(fill.astype(np.uint8)).resize((A.shape[1], A.shape[0]), Image.BILINEAR)).astype(np.float64)
            al = A[..., 3:4] / 255.0
            res = np.concatenate([A[..., :3] * al + F * (1 - al), np.full(A.shape[:2] + (1,), 255.0)], axis=-1)
            out[mat] = Image.fromarray(res.astype(np.uint8), 'RGBA')
            print('  %-24s transparency baked (%d%% of the decal grid found a surface)' % (mat, 100 * have.sum() // max(len(np.unique(cells[:, 0] * G + cells[:, 1])), 1)))
    return out

def build(name):
    cfg = config(name)
    classic, croot = load_classic(cfg)
    for rel in cfg['prefabs'] + [cfg['design']]:       # always convert from the game's own files
        if not os.path.exists(os.path.join(ORIG, rel)):
            os.makedirs(os.path.dirname(os.path.join(ORIG, rel)), exist_ok=True)
            shutil.copy2(os.path.join(AA, rel), os.path.join(ORIG, rel))
    baked = bake_transparent(cfg, classic)
    envd = UnityPy.load(os.path.join(ORIG, cfg['design']))
    shade_f, shade_c = shading_of(envd)
    d_obj = {o.path_id: o for o in envd.objects}
    d_name = {o.path_id: o.peek_name() for o in envd.objects if o.type.name in ('Material', 'Texture2D')}
    # Rumble material and texture objects to reuse, one pair per classic material (not the LOD and ghost ones)
    free_mats = sorted((o for o in envd.objects if o.type.name == 'Material' and not any(k in o.peek_name() for k in ('LOD', 'ghost'))), key=lambda o: o.peek_name())
    free_texs = sorted((o for o in envd.objects if o.type.name == 'Texture2D'), key=lambda o: (not o.peek_name().endswith('_ab'), o.peek_name()))
    mat_of = {}
    def material(cmat):
        if cmat not in mat_of:
            if not free_mats or not free_texs:
                raise SystemExit('%s: the design bundle has too few materials or textures' % name)
            mo, to = free_mats.pop(0), free_texs.pop(0)
            img, src = classic_image(cfg, cmat)
            if cmat in baked: img = baked[cmat]
            side = min(1024, max(img.size))
            if img.size != (side, side): img = img.resize((side, side), Image.LANCZOS)
            t = to.read()
            t.m_ColorSpace = 1
            t.set_image(img, target_format=TextureFormat.RGBA32, mipmap_count=1)
            t.save()
            mt = mo.read_typetree()
            for key, env_ in mt['m_SavedProperties']['m_TexEnvs']:
                env_['m_Texture'] = dict(m_FileID=0, m_PathID=to.path_id if key == '_BaseMap' else 0)
                env_['m_Scale'] = dict(x=1.0, y=1.0); env_['m_Offset'] = dict(x=0.0, y=0.0)
            sp = mt['m_SavedProperties']
            sp['m_Floats'] = [(k, shade_f.get(k, v)) for k, v in sp['m_Floats']]
            sp['m_Colors'] = [(k, dict(shade_c[k]) if k in shade_c else v) for k, v in sp['m_Colors']]
            mo.save_typetree(mt)
            mat_of[cmat] = mo.path_id
            print('  material %-24s <- %-24s (%s)' % (d_name[mo.path_id], cmat, src))
        return mat_of[cmat]
    cab = next(iter(envd.file.files.keys())).lower()

    # The game never instantiates the "Base" prefab: it spawns per-context prefabs (main game, selector, ghost,
    # in-game light), each a full copy of the hierarchy with its own renderers. They share the Mesh objects of
    # the design bundle, so a mesh is generated once (bones recorded as paths below the skeleton's parent) and
    # every prefab's renderer is pointed at its own transforms by those paths.
    done = {}                                           # mesh path id -> (fitted mesh, bone paths, bounds)
    for rel in cfg['prefabs']:
        envp = UnityPy.load(os.path.join(ORIG, rel))
        root = hierarchy(envp)
        node_of_go = {n.tr.m_GameObject.m_PathID: n for n in root.walk()}
        ext = [e.path.lower().split('/')[-1] for e in envp.assets[0].externals]
        if cab not in ext:
            raise SystemExit('%s does not reference the design bundle (%s)' % (rel, ext))
        dep = 1 + ext.index(cab)
        nb = nf = 0
        for o in envp.objects:
            if o.type.name != 'SkinnedMeshRenderer':
                continue
            tt = o.read_typetree()
            node = node_of_go[tt['m_GameObject']['m_PathID']]
            top = node                                  # the skeleton's parent: nearest ancestor with a Hips child
            while top is not None and not any(ch.name == 'Hips' for ch in top.children): top = top.parent
            nm = node.name
            kind = 'body' if nm.endswith('_cstm_body01') else 'face' if (nm.startswith('head') or nm.endswith('_LOD_head')) else None
            if kind is None or top is None:
                tt['m_Mesh'] = dict(m_FileID=0, m_PathID=0)
                o.save_typetree(tt)
                continue
            mesh_id = tt['m_Mesh']['m_PathID']
            if tt['m_Mesh']['m_FileID'] != dep or mesh_id not in d_obj:
                raise SystemExit('%s: renderer %s uses a mesh outside the design bundle' % (rel, nm))
            if mesh_id not in done:
                fm = fit(classic[kind], croot, root, top, cfg)
                if kind == 'face':
                    fm = rigid(fm, top.find('Head'))
                    if name == 'doctor':                # his glasses are the "eye expressions" mesh
                        fm = merge(fm, rigid(fit(classic['expr'], croot, root, top, cfg), top.find('Head')))
                decal = [i for i, m in enumerate(fm['mats']) if m in baked]
                if decal and len(decal) < len(fm['mats']):   # lit like the skin under them
                    dv = np.unique(np.concatenate([fm['tris'][i] for i in decal]))
                    sv = np.unique(np.concatenate([t for i, t in enumerate(fm['tris']) if i not in decal]))
                    near = ((fm['pos'][dv][:, None, :] - fm['pos'][sv][None, :, :]) ** 2).sum(-1).argmin(1)
                    fm['nrm'] = fm['nrm'].copy(); fm['nrm'][dv] = fm['nrm'][sv[near]]
                mo = d_obj[mesh_id]
                mt = mo.read_typetree()
                write_mesh(mt, fm, top)
                mo.save_typetree(mt)
                rb = top.find('Hips' if kind == 'body' else 'Head')
                lp = (np.c_[fm['pos'], np.ones(len(fm['pos']))] @ np.linalg.inv(rb.W).T)[:, :3]
                lo, hi = lp.min(0), lp.max(0)
                box = dict(m_Center=dict(zip('xyz', map(float, (lo + hi) / 2))), m_Extent=dict(zip('xyz', map(float, (hi - lo) / 2 + 0.05))))
                done[mesh_id] = (fm, [b.path_from(top) for b in fm['bones']], box)
            fm, paths, box = done[mesh_id]
            bones = [top.by_path(q) for q in paths]
            if None in bones:
                raise SystemExit('%s: %s lacks bone %s' % (rel, nm, paths[bones.index(None)]))
            tt['m_Bones'] = [dict(m_FileID=0, m_PathID=bn.path_id) for bn in bones]
            # the ghost prefab keeps its own (translucent) material on every submesh
            m0 = tt['m_Materials'][0] if tt['m_Materials'] else dict(m_FileID=0, m_PathID=0)
            own = m0['m_FileID'] == dep and m0['m_PathID'] in d_name and 'ghost' not in d_name[m0['m_PathID']]
            tt['m_Materials'] = [dict(m_FileID=dep, m_PathID=material(m)) if own else dict(m0) for m in fm['mats']]
            tt['m_RootBone'] = dict(m_FileID=0, m_PathID=top.find('Hips' if kind == 'body' else 'Head').path_id)
            tt['m_AABB'] = box
            o.save_typetree(tt)
            nb += kind == 'body'; nf += kind == 'face'
        save(envp, os.path.join(name, rel))
        print('  %-36s %d body and %d head renderers' % (os.path.basename(rel), nb, nf))
    save(envd, os.path.join(name, cfg['design']))
    print('  %d meshes rebuilt' % len(done))

def save(env, rel):
    dst = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(env.file.save(packer='lz4'))

def install():
    n = 0
    for name in CHARS:
        if os.path.isdir(os.path.join(OUT, name)):
            shutil.copytree(os.path.join(OUT, name), os.path.join(RUN, name), dirs_exist_ok=True)
            n += 1
    print('%d classic characters installed in %s' % (n, RUN))

if __name__ == '__main__':
    if len(sys.argv) >= 2 and sys.argv[1] == 'install':
        install()
    elif len(sys.argv) >= 2 and sys.argv[1] == 'build':
        for nm in sys.argv[2:] or list(CHARS):
            print(nm)
            build(nm)
    else:
        raise SystemExit(__doc__)
