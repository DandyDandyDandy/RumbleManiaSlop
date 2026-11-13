"""classic_preview.py <name> <out.png> - software render (front and back) of a classic character as fitted to
Rumble's rest pose, with the classic textures: the reference for what the game should show."""
import os, sys
import numpy as np
import UnityPy
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_chara as cc

if cc.AA is None:
    cc.configure_from_env()

def raster(img, zbuf, P, UV, tris, tex, flip_v):
    H, W = zbuf.shape
    th, tw = tex.shape[:2]
    for a, b, c in tris.reshape(-1, 3):
        p = P[[a, b, c]]
        x0, x1 = int(max(np.floor(p[:, 0].min()), 0)), int(min(np.ceil(p[:, 0].max()), W - 1))
        y0, y1 = int(max(np.floor(p[:, 1].min()), 0)), int(min(np.ceil(p[:, 1].max()), H - 1))
        if x1 < x0 or y1 < y0: continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        d = (p[1, 1] - p[2, 1]) * (p[0, 0] - p[2, 0]) + (p[2, 0] - p[1, 0]) * (p[0, 1] - p[2, 1])
        if abs(d) < 1e-9: continue
        l0 = ((p[1, 1] - p[2, 1]) * (xs - p[2, 0]) + (p[2, 0] - p[1, 0]) * (ys - p[2, 1])) / d
        l1 = ((p[2, 1] - p[0, 1]) * (xs - p[2, 0]) + (p[0, 0] - p[2, 0]) * (ys - p[2, 1])) / d
        l2 = 1 - l0 - l1
        m = (l0 >= 0) & (l1 >= 0) & (l2 >= 0)
        z = l0 * p[0, 2] + l1 * p[1, 2] + l2 * p[2, 2]
        m &= z > zbuf[ys, xs]
        if not m.any(): continue
        uv = l0[..., None] * UV[a] + l1[..., None] * UV[b] + l2[..., None] * UV[c]
        u = np.clip((uv[..., 0] % 1.0) * tw, 0, tw - 1).astype(int)
        v = uv[..., 1] % 1.0
        v = np.clip(((v if flip_v else 1 - v)) * th, 0, th - 1).astype(int)
        col = tex[v, u]
        m &= col[..., 3] > 127
        zbuf[ys[m], xs[m]] = z[m]
        img[ys[m], xs[m]] = col[m][:, :3]

def main(name, out):
    cfg = cc.config(name)
    classic, croot = cc.load_classic(cfg)
    envp = UnityPy.load(os.path.join(cc.ORIG, cfg['prefabs'][1]))
    root = cc.hierarchy(envp)
    top = next(n for n in root.walk() if any(ch.name == 'Hips' for ch in n.children))
    S = 700
    sheet = Image.new('RGB', (4 * S, S), (90, 140, 200))
    for col, (sign, flip_v) in enumerate(((1, False), (-1, False), (1, True), (-1, True))):
        img = np.zeros((S, S, 3), dtype=np.uint8); img[:] = (90, 140, 200)
        zbuf = np.full((S, S), -1e9)
        for part in ('body', 'face'):
            fm = cc.fit(classic[cfg[part][0]], croot, root, top, cfg)
            P = np.c_[S / 2 + sign * fm['pos'][:, 0] * S * 1.2, S * 0.95 - fm['pos'][:, 1] * S * 1.2, sign * fm['pos'][:, 2]]
            for t, (_, _, png) in zip(fm['tris'], cfg[part][1]):
                tex = np.array(Image.open(os.path.join(cc.MANIA_TEX, '%s_%s.png' % (cfg['tex'], png))).convert('RGBA'))
                raster(img, zbuf, P, fm['uv'], t, tex, flip_v)
        sheet.paste(Image.fromarray(img), (col * S, 0))
    sheet.save(out)
    print('front / back with v up, then front / back with v down ->', out)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
