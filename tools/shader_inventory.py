"""Inventory every Shader object across the game's bundles + player data.

    python shader_inventory.py <Data dir> <out.tsv>

Columns: shader name, compiled-blob bytes, pass count, subshader count, container file.
Encrypted (non-UnityFS) bundles are skipped and counted.
"""
import sys, os, collections
import UnityPy

data, out = sys.argv[1], sys.argv[2]
files = [os.path.join(data, 'data.unity3d')]
for r, _, fs in os.walk(os.path.join(data, 'StreamingAssets', 'aa')):
    files += [os.path.join(r, f) for f in fs if f.endswith('.bundle')]
rows = {}; skipped = 0; types = collections.Counter()
for i, f in enumerate(files):
    with open(f, 'rb') as fh:
        if fh.read(7) != b'UnityFS': skipped += 1; continue
    try:
        env = UnityPy.load(f)
    except Exception as e:
        print('ERR', f, e, file=sys.stderr); continue
    for obj in env.objects:
        types[obj.type.name] += 1
        if obj.type.name != 'Shader': continue
        tt = obj.read_typetree()
        pf = tt['m_ParsedForm']
        name = pf['m_Name']
        size = sum(x if isinstance(x, int) else sum(x) for x in tt['decompressedLengths'])
        passes = sum(len(s['m_Passes']) for s in pf['m_SubShaders'])
        if name not in rows or size > rows[name][0]:
            rows[name] = (size, passes, len(pf['m_SubShaders']), os.path.relpath(f, data), rows.get(name, (0, 0, 0, '', 0))[4] + 1)
        else:
            r0 = rows[name]; rows[name] = r0[:4] + (r0[4] + 1,)
    if i % 1000 == 0: print(i, len(files), len(rows), flush=True)
with open(out, 'w', encoding='utf-8') as o:
    o.write('name\tblob_bytes\tpasses\tsubshaders\tcopies\tfile\n')
    for n, (s, p, ss, f, c) in sorted(rows.items()):
        o.write(f'{n}\t{s}\t{p}\t{ss}\t{c}\t{f}\n')
print('distinct shaders:', len(rows), 'skipped encrypted:', skipped)
print('object types:', types.most_common(40))
