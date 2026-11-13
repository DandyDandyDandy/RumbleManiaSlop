"""classic_hand.py <out.png> name [name ...] - close-up of each classic character's left hand as it is taken over
(after the finger pose of classic_chara.py): seen from the front, from above and from the finger tips."""
import os, sys
import numpy as np
import UnityPy
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_chara as cc

if cc.AA is None:
    cc.configure_from_env()
from classic_preview import raster

def main(out, names):
    S = 420
    sheet = Image.new('RGB', (3 * S, S * len(names)))
    for row, name in enumerate(names):
        cfg = cc.config(name)
        classic, croot = cc.load_classic(cfg)
        cm = classic['body']
        te = croot.find('te_l').W[:3, 3]
        ctr = te + np.array([0.05, -0.01, 0.0])
        span = 0.16 if name != 'gongon' else 0.3
        k = S / span
        # (screen x axis, sign), (screen y axis, sign), depth axis sign
        views = (((0, 1), (1, -1), (2, -1)), ((0, 1), (2, 1), (1, 1)), ((2, -1), (1, -1), (0, 1)))
        for col, ((ax, sx), (ay, sy), (az, sz)) in enumerate(views):
            img = np.zeros((S, S, 3), dtype=np.uint8); img[:] = (90, 140, 200)
            zbuf = np.full((S, S), -1e9)
            P = np.c_[S / 2 + sx * (cm['pos'][:, ax] - ctr[ax]) * k, S / 2 + sy * (cm['pos'][:, ay] - ctr[ay]) * k, sz * cm['pos'][:, az]]
            for t, mat in zip(cm['tris'], cm['mats']):
                near = (np.abs(cm['pos'][t] - ctr) < span).all(1).reshape(-1, 3).all(1)
                if not near.any(): continue
                tex = np.array(cc.classic_image(cfg, mat)[0])
                # simple shading by depth-facing so the fingers read
                raster(img, zbuf, P, cm['uv'], t.reshape(-1, 3)[near].reshape(-1), tex, False)
            sheet.paste(Image.fromarray(img), (col * S, row * S))
    sheet.save(out)
    print('front, top, from the finger tips ->', out)

if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2:])
