"""Inventory texture formats across a bundle tree (and optionally a player data file).

    python tex_scan.py <aa dir> <out.tsv> [--jobs N] [--extra data.unity3d]

One row per texture object: file, type, name, format, width, height, mips, images/depth, data bytes, streamed(0/1).
Prints a per-(type, format) summary.
"""
import sys, os, argparse, multiprocessing as mp, traceback, collections

TYPES = ('Texture2D', 'Cubemap', 'Texture2DArray', 'Texture3D', 'CubemapArray')


def work(path):
    rows = []
    try:
        with open(path, 'rb') as f:
            if f.read(7) != b'UnityFS':
                return rows
        import UnityPy
        env = UnityPy.load(path)
        for o in env.objects:
            if o.type.name not in TYPES:
                continue
            try:
                t = o.read_typetree()
            except Exception as e:
                rows.append((path, o.type.name, '?', 'ERR ' + repr(e)[:60], 0, 0, 0, 0, 0, 0))
                continue
            fmt = t.get('m_TextureFormat', t.get('m_Format'))
            sd = t.get('m_StreamData') or {}
            streamed = 1 if sd.get('path') else 0
            size = sd.get('size', 0) if streamed else len(t.get('image data', b''))
            rows.append((path, o.type.name, t.get('m_Name', ''), fmt, t.get('m_Width', 0), t.get('m_Height', 0),
                         t.get('m_MipCount', 0), t.get('m_ImageCount', t.get('m_Depth', 0)), size, streamed))
    except Exception:
        rows.append((path, 'FILE', '?', 'ERR ' + traceback.format_exc(limit=1).strip().splitlines()[-1][:80], 0, 0, 0, 0, 0, 0))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('aa'); ap.add_argument('out'); ap.add_argument('--jobs', type=int, default=8)
    ap.add_argument('--extra', action='append', default=[])
    a = ap.parse_args()
    files = list(a.extra)
    for r, _, fs in os.walk(a.aa):
        files += [os.path.join(r, f) for f in fs]
    summ = collections.Counter(); size = collections.Counter()
    with mp.Pool(a.jobs) as pool, open(a.out, 'w', encoding='utf-8') as o:
        for rows in pool.imap_unordered(work, files, chunksize=32):
            for row in rows:
                o.write('\t'.join(str(x) for x in row) + '\n')
                summ[(row[1], row[3])] += 1; size[(row[1], row[3])] += row[8]
    for k in sorted(summ, key=lambda k: -size[k]):
        print(k, summ[k], f'{size[k] / 1e6:.1f} MB')


if __name__ == '__main__':
    main()
