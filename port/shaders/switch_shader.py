"""Parser for Unity 2022.3 compiled shader blobs, Switch (NVN) flavour, plus the generic container.

Layout (verified by parsing every shader of the game without desync, see `--all`):

Shader object (type tree):
  platforms[i]                    ShaderCompilerPlatform (19 = Switch, 18 = Vulkan, 4 = D3D11 ...)
  offsets/compressedLengths/decompressedLengths[i][seg]   LZ4 block segments of compressedBlob for platform i
  m_ParsedForm.m_SubShaders[].m_Passes[].progVertex (.progFragment ... are empty on Switch):
      m_PlayerSubPrograms[t][k]   {m_BlobIndex, m_KeywordIndices, m_ShaderRequirements, m_GpuProgramType}
      m_ParameterBlobIndices[t][k] blob index of the per-variant parameter blob
      m_CommonParameters          parameters shared by all variants of the pass (same structure as a parameter blob)
  (t: only index 3 of 4 is ever populated, on Switch and in the Windows default resources; the platform a
   subprogram belongs to follows from m_GpuProgramType, e.g. 25 SPIRV -> platform 18, 26 ConsoleVS -> platform 19)

Decompressed blob, segment 0 starts with the entry table:
  u32 count; count x {u32 offset, u32 length, u32 segment}
An entry is a subprogram blob or a parameter blob. Both start with u32 0x0C0A75BA (202012090).

Subprogram blob:
  +0x00 u32 version (202012090)
  +0x04 u32 programType (26 = ConsoleVS on Switch: one blob carries all stages of the variant)
  +0x08 3 x i32 statsALU, statsTEX, statsFlow;  +0x14 i32 statsTempRegister  (all 0 on Switch)
  +0x18 u32 keyword count, then that many strings (the variant's keyword names; the same set as
        m_KeywordIndices -> m_ParsedForm.m_KeywordNames in the type tree)
  then  u32 codeLength, code bytes, pad to 4
  then  u32 sourceMap (bit mask of mesh channels), u32 n, n x {u32 source channel, u32 target attribute location}
  (nothing else: all parameter data is in the parameter blob / m_CommonParameters)

Parameter blob:
  +0x00 u32 version
  +0x04 u32 groupCount   (1 + number of constant buffers)
  group 0 (loose globals; always empty in this game): u32 x 4 = 0
  groups 1..: string name, u32 size, u32 nParams, params, u32 nStructs, structs
     param: string name, u32 type(0 float,1 int,2 bool), u32 rows, u32 cols, u32 isMatrix, u32 arraySize, u32 offset
     struct: string name, u32 offset, u32 arraySize, u32 structSize, u32 nMembers, members (param)
  u32 nBindings, bindings: string name, u32 kind, u32 index, [kind-specific]
     kind 0 texture: u32 samplerIndex, u32 (dim << 1 | multisampled)
     kind 1 constant buffer, 2 buffer, 3 UAV, 4 sampler: u32 arraySize/extra
  index = stageMask << 16 | slot   (stage mask bit1 vertex, bit2 fragment, bit3 hull, bit4 domain, bit5 geometry)
  strings: u32 length, bytes, pad to 4

Switch program code ("NVN payload", codeLength bytes):
  +0x00 u32[6] per-stage value, -1 = stage absent                       stage order: VS, FS, GS, TCS, TES, CS
               0 for 67,018 of 67,889 stages, else 0x20000 / 0x40000 / 0x60000 (873 fragment, 2 vertex programs);
               meaning unverified - looks like a per-stage scratch (local) memory requirement
  +0x18 u32[6] control section offset, relative to +0x60
  +0x30 u32[6] control section size (0x880)
  +0x48 u32[6] data section size
  +0x60 sections; for each stage the data section follows its control section directly.
  control section (GLSLC output, magic 0x98761234): +0x700 u32 c1 offset in data, +0x704 u32 data length
  data section (magic 0x12345678): +0x30 Maxwell shader program header (0x50 bytes), +0x80 instructions,
       [c1 offset .. length) = constant buffer 1 (immediate constants / jump tables)

Usage:
  python switch_shader.py --all <Data dir>             parse every shader, report counts
  python switch_shader.py <file> [name substring]      dump
"""
import os
import struct
import sys
import collections

import lz4.block
import UnityPy

MAGIC = 202012090
CONTROL_MAGIC = 0x98761234
DATA_MAGIC = 0x12345678
STAGES = ('vs', 'fs', 'gs', 'tcs', 'tes', 'cs')
CHANNELS = ('Vertex', 'Normal', 'Tangent', 'Color', 'TexCoord0', 'TexCoord1', 'TexCoord2', 'TexCoord3', 'TexCoord4',
            'TexCoord5', 'TexCoord6', 'TexCoord7', 'BlendWeight', 'BlendIndices')


# m_GpuProgramType -> ShaderCompilerPlatform of the blob it indexes (all platforms of a pass share one subprogram list)
PROGTYPE_PLATFORM = {25: 18, 26: 19, 27: 19, 28: 19, 29: 19, 30: 19}


class Desync(Exception):
    pass


def platform_segments(tt):
    """yield (platform, [segment bytes])"""
    comp = bytes(tt['compressedBlob'])
    for i, p in enumerate(tt['platforms']):
        o, c, d = tt['offsets'][i], tt['compressedLengths'][i], tt['decompressedLengths'][i]
        if not isinstance(o, list):
            o, c, d = [o], [c], [d]
        yield p, [lz4.block.decompress(comp[oo:oo + cc], uncompressed_size=dd) for oo, cc, dd in zip(o, c, d)]


def entry_table(segs):
    b0 = segs[0]
    n = struct.unpack_from('<I', b0, 0)[0]
    return [struct.unpack_from('<III', b0, 4 + 12 * i) for i in range(n)]


def entry_bytes(segs, ent):
    off, ln, seg = ent
    if seg >= len(segs) or off + ln > len(segs[seg]):
        raise Desync(f'entry outside segment {ent}')
    return segs[seg][off:off + ln]


class R:
    def __init__(self, b, o=0):
        self.b, self.o = b, o

    def u32(self):
        if self.o + 4 > len(self.b):
            raise Desync('read past end')
        v = struct.unpack_from('<I', self.b, self.o)[0]
        self.o += 4
        return v

    def i32(self):
        v = self.u32()
        return v - (1 << 32) if v & 0x80000000 else v

    def string(self):
        n = self.u32()
        if n > 4096 or self.o + n > len(self.b):
            raise Desync(f'bad string length {n} at {self.o - 4:#x}')
        s = self.b[self.o:self.o + n]
        self.o += (n + 3) & ~3
        try:
            return s.decode('ascii')
        except UnicodeDecodeError:
            raise Desync(f'non-ascii string at {self.o:#x}')

    def raw(self, n):
        if self.o + n > len(self.b):
            raise Desync('read past end')
        s = self.b[self.o:self.o + n]
        self.o += n
        return s


def _param(r):
    name = r.string()
    typ, rows, cols, is_matrix, array, offset = (r.u32() for _ in range(6))
    if typ > 8 or rows > 4 or cols > 4 or is_matrix > 1:
        raise Desync(f'implausible param {name} {typ} {rows} {cols} {is_matrix}')
    return dict(name=name, type=typ, rows=rows, cols=cols, matrix=bool(is_matrix), array=array, offset=offset)


def parse_params(b):
    """Parameter blob -> dict(cbuffers=[...], bindings=[...])"""
    r = R(b)
    if r.u32() != MAGIC:
        raise Desync('param blob magic')
    groups = r.u32()
    if groups < 1 or groups > 256:
        raise Desync(f'group count {groups}')
    g0 = [r.u32() for _ in range(4)]
    if any(g0):
        raise Desync(f'group 0 not empty: {g0}')
    cbs = []
    for _ in range(groups - 1):
        name = r.string()
        size = r.u32()
        params = [_param(r) for _ in range(r.u32())]
        structs = []
        for _ in range(r.u32()):
            sname = r.string()
            soff, sarr, ssize = r.u32(), r.u32(), r.u32()
            members = [_param(r) for _ in range(r.u32())]
            structs.append(dict(name=sname, offset=soff, array=sarr, size=ssize, members=members))
        cbs.append(dict(name=name, size=size, params=params, structs=structs))
    binds = []
    for _ in range(r.u32()):
        name = r.string()
        kind, index = r.u32(), r.u32()
        d = dict(name=name, kind=kind, stages=index >> 16, slot=index & 0xffff)
        if kind == 0:
            d['sampler'] = r.i32()
            x = r.u32()
            d['dim'], d['ms'] = x >> 1, x & 1
        elif kind in (1, 2, 3, 4):
            d['extra'] = r.u32()
        else:
            raise Desync(f'binding kind {kind}')
        binds.append(d)
    if r.o != len(b):
        raise Desync(f'param blob: {len(b) - r.o} trailing bytes')
    return dict(cbuffers=cbs, bindings=binds)


def parse_nvn(code):
    """NVN payload -> {stage: dict(control, data, sph_code, c1)}"""
    if len(code) < 0x60:
        raise Desync('payload too small')
    h = struct.unpack_from('<24I', code, 0)
    res, coff, csize, dsize = h[0:6], h[6:12], h[12:18], h[18:24]
    out = {}
    spans = []
    for i, st in enumerate(STAGES):
        if coff[i] == 0xffffffff:
            if not (res[i] == csize[i] == dsize[i] == 0xffffffff):
                raise Desync('inconsistent absent stage')
            continue
        c0 = 0x60 + coff[i]
        d0 = c0 + csize[i]
        if d0 + dsize[i] > len(code):
            raise Desync('section outside payload')
        control = code[c0:c0 + csize[i]]
        data = code[d0:d0 + dsize[i]]
        if struct.unpack_from('<I', control, 0)[0] != CONTROL_MAGIC:
            raise Desync('control magic')
        if struct.unpack_from('<I', data, 0)[0] != DATA_MAGIC:
            raise Desync('data magic')
        c1off, length = struct.unpack_from('<II', control, 0x700)
        if length != dsize[i] or c1off > length:
            raise Desync(f'control c1/length {c1off:#x} {length:#x} vs data {dsize[i]:#x}')
        spans.append((c0, d0 + dsize[i]))
        out[st] = dict(control=control, data=data, c1=data[c1off:length], c1_off=c1off, scratch=res[i],
                       sph_code=data[(0 if st == 'cs' else 0x30):c1off])
    spans.sort()
    pos = 0x60
    for a, b in spans:
        if a != pos:
            raise Desync(f'gap/overlap in payload at {pos:#x} (next section {a:#x})')
        pos = b
    if pos != len(code):
        raise Desync(f'payload: {len(code) - pos} trailing bytes')
    return out


def parse_subprogram(b, nvn=True):
    r = R(b)
    if r.u32() != MAGIC:
        raise Desync('subprogram magic')
    ptype = r.u32()
    stats = [r.i32() for _ in range(4)]
    nkw = r.u32()
    if nkw > 256:
        raise Desync(f'{nkw} inline keywords')
    keywords = [r.string() for _ in range(nkw)]
    n = r.u32()
    code = r.raw(n)
    r.o = (r.o + 3) & ~3
    source_map = r.u32()
    chans = [(r.u32(), r.u32()) for _ in range(r.u32())]
    if r.o != len(b):
        raise Desync(f'subprogram: {len(b) - r.o} trailing bytes (type {ptype})')
    d = dict(type=ptype, stats=stats, keywords=keywords, code=code, source_map=source_map, channels=chans)
    if nvn:
        d['stages'] = parse_nvn(code)
    return d


def common_params(cp, names):
    """m_CommonParameters of the type tree -> same shape as parse_params()"""
    def nm(i):
        return names.get(i, f'#{i}')
    cbs = []
    for cb in cp['m_ConstantBuffers']:
        ps = [dict(name=nm(v['m_NameIndex']), type=v['m_Type'], rows=1, cols=v['m_Dim'], matrix=False,
                   array=v['m_ArraySize'], offset=v['m_Index']) for v in cb['m_VectorParams']]
        ps += [dict(name=nm(m['m_NameIndex']), type=m['m_Type'], rows=m['m_RowCount'], cols=4, matrix=True,
                    array=m['m_ArraySize'], offset=m['m_Index']) for m in cb['m_MatrixParams']]
        ps.sort(key=lambda p: p['offset'])
        cbs.append(dict(name=nm(cb['m_NameIndex']), size=cb['m_Size'], params=ps,
                        structs=[dict(name=nm(s['m_NameIndex']), offset=s['m_Index'], array=s['m_ArraySize'],
                                      size=s['m_StructSize']) for s in cb['m_StructParams']]))
    binds = []
    for t in cp['m_TextureParams']:
        binds.append(dict(name=nm(t['m_NameIndex']), kind=0, stages=t['m_Index'] >> 16, slot=t['m_Index'] & 0xffff,
                          sampler=t['m_SamplerIndex'], dim=t['m_Dim'], ms=int(t['m_MultiSampled'])))
    for k, key in ((1, 'm_ConstantBufferBindings'), (2, 'm_BufferParams'), (3, 'm_UAVParams')):
        for c in cp[key]:
            binds.append(dict(name=nm(c['m_NameIndex']), kind=k, stages=c['m_Index'] >> 16, slot=c['m_Index'] & 0xffff,
                              extra=c.get('m_ArraySize', 0)))
    for s in cp['m_Samplers']:
        binds.append(dict(name=f"sampler#{s['sampler']}", kind=4, stages=s['bindPoint'] >> 16, slot=s['bindPoint'] & 0xffff, extra=s['sampler']))
    return dict(cbuffers=cbs, bindings=binds)


def iter_shaders(path):
    env = UnityPy.load(path)
    for obj in env.objects:
        if obj.type.name == 'Shader':
            yield obj, obj.read_typetree()


def iter_variants(tt):
    """yield (subshader idx, pass idx, pass dict, stage name, platform idx, k, player subprogram, param blob index)"""
    for si, ss in enumerate(tt['m_ParsedForm']['m_SubShaders']):
        for pi, ps in enumerate(ss['m_Passes']):
            for prog in ('progVertex', 'progFragment', 'progGeometry', 'progHull', 'progDomain', 'progRayTracing'):
                pv = ps[prog]
                for t, lst in enumerate(pv['m_PlayerSubPrograms']):
                    pb = pv['m_ParameterBlobIndices'][t] if t < len(pv['m_ParameterBlobIndices']) else []
                    for k, sp in enumerate(lst):
                        yield si, pi, ps, prog, t, k, sp, (pb[k] if k < len(pb) else None)


def check_file(path, stats, seen):
    for obj, tt in iter_shaders(path):
        name = tt['m_ParsedForm']['m_Name']
        key = (name, len(tt['compressedBlob']))
        if key in seen:
            stats['duplicate shader objects skipped'] += 1
            continue
        seen.add(key)
        stats['shaders'] += 1
        plats = tt['platforms']
        segsets = list(platform_segments(tt))
        for p, segs in segsets:
            stats[f'platform {p}'] += 1
            ents = entry_table(segs)
            stats['blob entries'] += len(ents)
            used_sub, used_par = set(), set()
            kwmap = {}
            for si, pi, ps, prog, t, k, sp, pbi in iter_variants(tt):
                if PROGTYPE_PLATFORM.get(sp['m_GpuProgramType'], 19) != p and len(plats) > 1:
                    continue
                stats[f'variants in {prog}'] += 1
                stats[f"variant gpuProgramType {sp['m_GpuProgramType']}"] += 1
                kwmap.setdefault(sp['m_BlobIndex'], set()).add(tuple(sorted(tt['m_ParsedForm']['m_KeywordNames'][x] for x in sp['m_KeywordIndices'])))
                used_sub.add(sp['m_BlobIndex'])
                if pbi is not None:
                    used_par.add(pbi)
            if used_sub & used_par:
                raise Desync(f'{name}: blob index used both as program and parameters')
            if (used_sub | used_par) != set(range(len(ents))):
                stats['shaders with unreferenced blob entries'] += 1
            for i in sorted(used_sub):
                try:
                    sub = parse_subprogram(entry_bytes(segs, ents[i]))
                except Desync as e:
                    stats['DESYNC subprogram'] += 1
                    print(f'DESYNC {name} entry {i}: {e}', file=sys.stderr)
                    continue
                stats['subprograms parsed'] += 1
                kwn = tt['m_ParsedForm']['m_KeywordNames']
                stats['distinct shader names'] = len({n for n, _ in seen})
                stats[f"subprogram channel bindings {len(sub['channels'])}"] += 1
                stats[f"subprogram blob type {sub['type']}"] += 1
                if kwmap[i] == {tuple(sorted(sub['keywords']))}:
                    stats['subprograms whose inline keywords equal m_KeywordIndices'] += 1
                else:
                    stats['subprograms whose inline keywords DIFFER from m_KeywordIndices'] += 1
                stats['subprogram stages ' + '+'.join(sub['stages'])] += 1
                for st, s in sub['stages'].items():
                    stats[f'{st} programs'] += 1
                    stats[f'{st} code bytes'] += len(s['sph_code'])
                    stats[f"stages with header field 0 = {s['scratch']:#x}"] += 1
                    if s['scratch']:
                        stats[f'{st} programs with non-zero header field 0'] += 1
            for i in sorted(used_par):
                try:
                    pb = parse_params(entry_bytes(segs, ents[i]))
                except Desync as e:
                    stats['DESYNC param blob'] += 1
                    print(f'DESYNC {name} param entry {i}: {e}', file=sys.stderr)
                    continue
                stats['param blobs parsed'] += 1
                stats['param cbuffers'] += len(pb['cbuffers'])
                for bd in pb['bindings']:
                    stats[f"param binding kind {bd['kind']}"] += 1
                if any(cb['structs'] for cb in pb['cbuffers']):
                    stats['param blobs with struct params'] += 1


def main():
    if sys.argv[1] == '--all':
        data = sys.argv[2]
        files = [os.path.join(data, 'data.unity3d')]
        for root, _, fs in os.walk(os.path.join(data, 'StreamingAssets', 'aa')):
            files += [os.path.join(root, f) for f in fs if f.endswith('.bundle')]
        stats = collections.Counter()
        seen = set()
        for i, f in enumerate(files):
            with open(f, 'rb') as fh:
                head = fh.read(7)
            if head != b'UnityFS':
                stats['non-UnityFS files skipped'] += 1
                continue
            # cheap pre-filter: skip bundles without a Shader object
            try:
                check_file(f, stats, seen)
            except Desync as e:
                stats['DESYNC file'] += 1
                print('DESYNC', f, e, file=sys.stderr)
            except Exception as e:
                stats['load errors'] += 1
                print('ERR', f, repr(e)[:200], file=sys.stderr)
            if i % 2000 == 0:
                print(f'{i}/{len(files)} shaders={stats["shaders"]}', file=sys.stderr, flush=True)
        for k in sorted(stats):
            print(f'{stats[k]:>12}  {k}')
        return
    want = sys.argv[2] if len(sys.argv) > 2 else ''
    for obj, tt in iter_shaders(sys.argv[1]):
        pf = tt['m_ParsedForm']
        if want not in pf['m_Name']:
            continue
        print(f"== {pf['m_Name']} platforms={tt['platforms']}")
        for p, segs in platform_segments(tt):
            ents = entry_table(segs)
            print(f'  platform {p}: segments {[len(s) for s in segs]} entries {len(ents)}')
        for si, pi, ps, prog, t, k, sp, pbi in iter_variants(tt):
            if k < 3:
                print(f"  sub {si} pass {pi} {ps['m_State']['m_Name']!r} {prog}[{t}][{k}] blob {sp['m_BlobIndex']} params {pbi} "
                      f"type {sp['m_GpuProgramType']} kw {sp['m_KeywordIndices']}")


if __name__ == '__main__':
    main()
