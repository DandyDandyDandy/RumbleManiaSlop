"""Report which GPU platforms/program formats the game's compiled shaders carry.

    python shader_probe.py <bundle or data.unity3d> [...]

For each Shader object: platforms list, decompressed blob sizes, and marker counts
(SPIR-V magic, GLSL '#version', DXBC) so we can tell what a Windows player could consume.
"""
import sys, struct, collections
import lz4.block
import UnityPy

MARK = {'spirv': struct.pack('<I', 0x07230203), 'glsl': b'#version', 'dxbc': b'DXBC', 'nvn': b'NVN', 'glslc': b'GLSLC'}


def blobs(tt):
    comp = bytes(tt['compressedBlob'])
    plats = tt['platforms']
    offs, clens, dlens = tt['offsets'], tt['compressedLengths'], tt['decompressedLengths']
    for i, p in enumerate(plats):
        o, c, d = offs[i], clens[i], dlens[i]
        if not isinstance(o, list):
            o, c, d = [o], [c], [d]
        out = b''
        for oo, cc, dd in zip(o, c, d):
            out += lz4.block.decompress(comp[oo:oo + cc], uncompressed_size=dd)
        yield p, out


def main():
    tot = collections.Counter(); n = 0; shown = 0
    for path in sys.argv[1:]:
        env = UnityPy.load(path)
        for obj in env.objects:
            if obj.type.name != 'Shader':
                continue
            n += 1
            tt = obj.read_typetree()
            name = tt['m_ParsedForm']['m_Name']
            for p, b in blobs(tt):
                cnt = {k: b.count(v) for k, v in MARK.items()}
                tot[('platform', p)] += 1
                for k, v in cnt.items():
                    if v: tot[k] += v
                if shown < 6:
                    shown += 1
                    print(f'{name!r} platform={p} blob={len(b)} markers={ {k: v for k, v in cnt.items() if v} }')
                    ne = struct.unpack_from('<I', b, 0)[0]
                    print('   entries:', ne, 'head:', b[:48].hex())
                    if ne and ne < 100000:
                        eo, el = struct.unpack_from('<II', b, 4)
                        sub = b[eo:eo + min(el, 4096)]
                        print('   first subprogram', eo, el, 'hdr ints:', struct.unpack_from('<6i', sub, 0))
                        i = sub.find(b'#version')
                        if i >= 0: print('   glsl excerpt:', sub[i:i + 300])
                        txt = bytes(c if 32 <= c < 127 else 46 for c in sub[:400]).decode()
                        print('   ascii:', txt)
    print('shaders:', n, dict(tot))


main()
