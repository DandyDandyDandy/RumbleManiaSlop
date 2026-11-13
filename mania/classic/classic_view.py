"""classic_view.py <name> <out.png> [tree] - render a character straight from built bundles, in seconds.

Reads the prefab bundle and its design bundle the way the engine would (renderers -> mesh, bones, per-submesh
material -> _BaseMap texture), skins the meshes in the prefab's rest pose and software-renders front, back and
side views. `tree` is the asset tree to read: `classic` (default, work\\unity\\classic), or `orig` for the game's
own files. What this shows is what the files say; anything different in the game is done by game code at run time.
Renderers that are disabled or on inactive objects are skipped, except that one face set (head01) is shown.
"""
import os, sys
import numpy as np
import UnityPy
from PIL import Image
from UnityPy.helpers.MeshHelper import MeshHandler
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_chara as cc

if cc.AA is None:
    cc.configure_from_env()
from classic_preview import raster

def main(name, out, tree='classic'):
    cfg = cc.config(name)
    base = os.path.join(cc.OUT, name) if tree == 'classic' else cc.ORIG
    envp = UnityPy.load(os.path.join(base, cfg['prefabs'][1]))   # the selector prefab (menus)
    envd = UnityPy.load(os.path.join(base, cfg['design']))
    root = cc.hierarchy(envp)
    by_tr = {n.path_id: n for n in root.walk()}
    node_of_go = {n.tr.m_GameObject.m_PathID: n for n in root.walk()}
    dobj = {o.path_id: o for o in envd.objects}
    lod0 = next(n for n in root.walk() if any(ch.name == 'Hips' for ch in n.children))   # full-detail model
    draws = []     # (positions, uv, triangles, texture RGBA or None, label)
    texcache = {}
    for o in envp.objects:
        if o.type.name != 'SkinnedMeshRenderer':
            continue
        tt = o.read_typetree()
        node = node_of_go[tt['m_GameObject']['m_PathID']]
        n = node; inside = False; active = True
        while n is not None:
            inside |= n is lod0
            active &= bool(n.tr.m_GameObject.read().m_IsActive)
            n = n.parent
        if not inside or not tt['m_Mesh']['m_PathID']:
            continue
        nm = node.name
        if nm[-2:].isdigit() and nm[:-2] in ('head', 'face', 'faces', 'mouth') and nm[-2:] != '01':
            continue
        if not active:
            print('  skipped (inactive object):', nm); continue
        mesh = dobj[tt['m_Mesh']['m_PathID']].read()
        h = MeshHandler(mesh); h.process()
        nv = h.m_VertexCount
        pos = np.array(h.m_Vertices, dtype=np.float64).reshape(nv, 3)
        uv = np.array(h.m_UV0, dtype=np.float64).reshape(nv, -1)[:, :2]
        bi = np.array(h.m_BoneIndices, dtype=np.int64).reshape(nv, -1)
        bw = np.array(h.m_BoneWeights, dtype=np.float64).reshape(nv, -1) if h.m_BoneWeights is not None and len(h.m_BoneWeights) >= nv else np.ones((nv, 1))
        if bi.shape[1] > bw.shape[1]: bi = bi[:, :bw.shape[1]]
        bones = [by_tr[b['m_PathID']] for b in tt['m_Bones']]
        binds = [np.array([[getattr(b, 'e%d%d' % (r, c)) for c in range(4)] for r in range(4)]) for b in mesh.m_BindPose]
        hp = np.c_[pos, np.ones(nv)]
        P = np.zeros((nv, 3))
        for k in range(bi.shape[1]):
            for b in np.unique(bi[:, k]):
                sel = (bi[:, k] == b) & (bw[:, k] > 0)
                if sel.any():
                    P[sel] += bw[sel, k:k + 1] * (hp[sel] @ (bones[b].W @ binds[b]).T)[:, :3]
        for si, tris in enumerate(h.get_triangles()):
            tris = np.array(tris).reshape(-1)
            tex, label = None, '-'
            if si < len(tt['m_Materials']) and tt['m_Materials'][si]['m_PathID'] in dobj:
                mt = dobj[tt['m_Materials'][si]['m_PathID']].read_typetree()
                label = mt['m_Name']
                for key, e in mt['m_SavedProperties']['m_TexEnvs']:
                    pid = e['m_Texture']['m_PathID']
                    if key == '_BaseMap' and pid in dobj:
                        if pid not in texcache:
                            texcache[pid] = np.array(dobj[pid].read().image.convert('RGBA'))
                        tex = texcache[pid]
            print('  %-22s submesh %d: %5d triangles, material %s%s' % (nm, si, len(tris) // 3, label, '' if tex is not None else ' (no texture)'))
            draws.append((P, uv, tris, tex if tex is not None else np.full((2, 2, 4), (255, 0, 255, 255), dtype=np.uint8)))
    S = 700
    sheet = Image.new('RGB', (3 * S, S))
    views = ((0, 1, 2), (0, -1, 2), (2, 1, 0))     # (screen x axis, sign, depth axis): front, back, side
    for col, (ax, sign, dax) in enumerate(views):
        img = np.zeros((S, S, 3), dtype=np.uint8); img[:] = (90, 140, 200)
        zbuf = np.full((S, S), -1e9)
        for P, uv, tris, tex in draws:
            Q = np.c_[S / 2 + sign * P[:, ax] * S * 1.2, S * 0.95 - P[:, 1] * S * 1.2, (sign if col < 2 else -1) * P[:, dax]]
            raster(img, zbuf, Q, uv, tris, tex, False)
        sheet.paste(Image.fromarray(img), (col * S, 0))
    sheet.save(out)
    print('front, back, side ->', out)

if __name__ == '__main__':
    main(*sys.argv[1:4])
