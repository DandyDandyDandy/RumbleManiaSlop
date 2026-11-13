"""Compare converted textures against UnityPy's own decode of the Switch originals (top mip only).

    python tex_verify.py <original aa dir> <decrypted dir> <converted aa dir> <out.tsv> [--jobs N] [--formats 4,1,3]

For every Texture2D in the original tree that carries a platform blob, decode it from the original (UnityPy handles
the Switch layout itself) and from the converted tree, and report the mean absolute pixel difference.
"""
import sys, os, argparse, multiprocessing as mp, traceback
FORMATS = None


def work(task):
    src, dst, formats = task
    rows = []
    try:
        with open(src, 'rb') as f:
            if f.read(7) != b'UnityFS':
                return rows
        import UnityPy, numpy as np
        a = UnityPy.load(src)
        objs = [o for o in a.objects if o.type.name == 'Texture2D']
        if not objs:
            return rows
        want = {}
        for o in objs:
            t = o.read_typetree()
            if t.get('m_PlatformBlob') and t['m_TextureFormat'] in formats and t['m_Width']:
                want[(o.assets_file.name, o.path_id)] = o
        if not want:
            return rows
        b = UnityPy.load(dst)
        for o in b.objects:
            k = (o.assets_file.name, o.path_id)
            if o.type.name != 'Texture2D' or k not in want:
                continue
            try:
                d0 = want[k].read(); d1 = o.read()
                i0 = np.asarray(d0.image.convert('RGBA'), dtype=np.int16); i1 = np.asarray(d1.image.convert('RGBA'), dtype=np.int16)
                diff = float(np.abs(i0 - i1).mean()) if i0.shape == i1.shape else 999.0
                rows.append((dst, d0.m_Name, d0.m_TextureFormat, d1.m_TextureFormat, d0.m_Width, d0.m_Height, d0.m_MipCount, f'{diff:.2f}'))
            except Exception as e:
                rows.append((dst, '?', 0, 0, 0, 0, 0, 'ERR ' + repr(e)[:80]))
    except Exception:
        rows.append((dst, 'FILE', 0, 0, 0, 0, 0, 'ERR ' + traceback.format_exc(limit=1).strip().splitlines()[-1][:80]))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('orig'); ap.add_argument('dec'); ap.add_argument('conv'); ap.add_argument('out')
    ap.add_argument('--jobs', type=int, default=8); ap.add_argument('--formats', default='1,3,4,10,12,24,48')
    a = ap.parse_args()
    formats = {int(x) for x in a.formats.split(',')}
    dec = {f: os.path.join(a.dec, f) for f in os.listdir(a.dec)} if os.path.isdir(a.dec) else {}
    tasks = []
    for r, _, fs in os.walk(a.orig):
        for f in fs:
            src = os.path.join(r, f); rel = os.path.relpath(src, a.orig)
            if f in dec and os.path.dirname(rel).lower() == 'switch':
                src = dec[f]
            tasks.append((src, os.path.join(a.conv, rel), formats))
    n = bad = 0
    with mp.Pool(a.jobs) as pool, open(a.out, 'w', encoding='utf-8') as o:
        for rows in pool.imap_unordered(work, tasks, chunksize=16):
            for row in rows:
                n += 1
                o.write('\t'.join(str(x) for x in row) + '\n')
                if row[7].startswith('ERR') or float(row[7]) > 4:
                    bad += 1
    print('textures', n, 'differing', bad)


if __name__ == '__main__':
    main()
