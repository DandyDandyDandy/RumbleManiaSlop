"""Check the mip chains of a converted tree: every mip level should look like a downscale of level 0.

    python tex_mipcheck.py <converted aa dir> <out.tsv> [--jobs N] [--extra file]

Rows: file, name, format, width, height, mip, mean abs difference against the downscaled top level.
"""
import sys, os, argparse, multiprocessing as mp, traceback
BLOCK = {10: (8, 4), 12: (16, 4), 24: (16, 4), 25: (16, 4), 26: (8, 4), 27: (16, 4)}
BPP = {1: 1, 3: 3, 4: 4, 5: 4}


def mip_size(fmt, w, h):
    if fmt in BLOCK:
        b, d = BLOCK[fmt]
        return -(-w // d) * -(-h // d) * b
    return w * h * BPP[fmt]


def work(path):
    rows = []
    try:
        with open(path, 'rb') as f:
            if f.read(7) != b'UnityFS':
                return rows
        import UnityPy, numpy as np
        from PIL import Image
        from UnityPy.export.Texture2DConverter import parse_image_data
        env = UnityPy.load(path)
        for o in env.objects:
            if o.type.name != 'Texture2D':
                continue
            d = o.read()
            fmt = int(d.m_TextureFormat)
            if d.m_MipCount < 2 or (fmt not in BLOCK and fmt not in BPP) or not d.m_Width:
                continue
            try:
                data = bytes(d.get_image_data())
                off = 0; top = None
                for i in range(d.m_MipCount):
                    w, h = max(1, d.m_Width >> i), max(1, d.m_Height >> i)
                    n = mip_size(fmt, w, h)
                    if w < 8 or h < 8:
                        break
                    img = parse_image_data(data[off:off + n], w, h, fmt, (2022, 3, 30, 0), 19, None, False).convert('RGBA')
                    off += n
                    if top is None:
                        top = img; continue
                    ref = np.asarray(top.resize((w, h), Image.BOX), dtype=np.int16)
                    diff = float(np.abs(ref - np.asarray(img, dtype=np.int16)).mean())
                    rows.append((path, d.m_Name, fmt, d.m_Width, d.m_Height, i, f'{diff:.2f}'))
            except Exception as e:
                rows.append((path, d.m_Name, fmt, d.m_Width, d.m_Height, -1, 'ERR ' + repr(e)[:80]))
    except Exception:
        rows.append((path, 'FILE', 0, 0, 0, -1, 'ERR ' + traceback.format_exc(limit=1).strip().splitlines()[-1][:80]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('aa'); ap.add_argument('out'); ap.add_argument('--jobs', type=int, default=8); ap.add_argument('--extra', action='append', default=[])
    a = ap.parse_args()
    files = list(a.extra)
    for r, _, fs in os.walk(a.aa):
        files += [os.path.join(r, f) for f in fs]
    n = bad = 0
    with mp.Pool(a.jobs) as pool, open(a.out, 'w', encoding='utf-8') as o:
        for rows in pool.imap_unordered(work, files, chunksize=16):
            for row in rows:
                n += 1
                o.write('\t'.join(str(x) for x in row) + '\n')
                if row[6].startswith('ERR') or float(row[6]) > 12:
                    bad += 1
    print('mips checked', n, 'suspicious', bad)


if __name__ == '__main__':
    main()
