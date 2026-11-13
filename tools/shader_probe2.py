"""Parse Unity 2022 shader blobs properly (segmented) and characterise subprogram payloads.

    python shader_probe2.py <bundle> [dump_dir]
"""
import sys, struct, collections, os
import lz4.block
import UnityPy


def segments(tt):
    comp = bytes(tt['compressedBlob'])
    for i, p in enumerate(tt['platforms']):
        o, c, d = tt['offsets'][i], tt['compressedLengths'][i], tt['decompressedLengths'][i]
        if not isinstance(o, list): o, c, d = [o], [c], [d]
        yield p, [lz4.block.decompress(comp[oo:oo + cc], uncompressed_size=dd) for oo, cc, dd in zip(o, c, d)]


def rd_str(b, o):
    n = struct.unpack_from('<I', b, o)[0]
    s = b[o + 4:o + 4 + n]
    return s, o + 4 + ((n + 3) & ~3)


env = UnityPy.load(sys.argv[1])
dump = sys.argv[2] if len(sys.argv) > 2 else None
for obj in env.objects:
    if obj.type.name != 'Shader': continue
    tt = obj.read_typetree()
    name = tt['m_ParsedForm']['m_Name']
    for p, segs in segments(tt):
        b0 = segs[0]
        n = struct.unpack_from('<I', b0, 0)[0]
        ents = [struct.unpack_from('<III', b0, 4 + 12 * i) for i in range(n)]
        print(f'{name!r} platform={p} segments={[len(s) for s in segs]} entries={n}')
        types = collections.Counter(); magics = collections.Counter(); shown = 0
        for idx, (off, ln, seg) in enumerate(ents):
            sub = segs[seg][off:off + ln]
            ver, ptype, s1, s2, s3 = struct.unpack_from('<5i', sub, 0)
            # 2022: version, programType, statsALU, statsTEX, statsFlow, statsTempRegister
            o = 24
            nkw = struct.unpack_from('<I', sub, o)[0]; o += 4
            if nkw < 1000:
                # keywords are strings in older formats, u16 ids in newer; try to locate code by length field
                pass
            types[ptype] += 1
            if ptype and shown < 4:
                shown += 1
                print(f'  [{idx}] seg={seg} len={ln} ver={ver} type={ptype}')
                # scan for plausible code-length-prefixed payload: find biggest u32 length field <= remaining
                best = None
                for q in range(24, min(len(sub) - 4, 600), 4):
                    L = struct.unpack_from('<I', sub, q)[0]
                    if 64 < L <= len(sub) - q - 4 and (best is None or L > best[1]): best = (q, L)
                if best:
                    q, L = best
                    code = sub[q + 4:q + 4 + L]
                    magics[code[:4].hex()] += 1
                    print(f'      code@{q} len={L} head={code[:32].hex()}')
                    print('      ascii:', bytes(c if 32 <= c < 127 else 46 for c in code[:200]).decode())
                    if dump:
                        os.makedirs(dump, exist_ok=True)
                        open(os.path.join(dump, f'p{p}_{idx}_t{ptype}.bin'), 'wb').write(code)
        print('  programType histogram:', dict(types))
