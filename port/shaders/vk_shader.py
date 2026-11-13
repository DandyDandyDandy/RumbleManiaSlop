"""Unity 2022.3 Vulkan (ShaderCompilerPlatform 18, GpuProgramType 25 SPIRV) subprogram code: parse / build.

Program code layout (inside the generic subprogram blob, see switch_shader.py), verified against the six
shaders of the Windows 'unity default resources' (all variants parse, sections tile the code exactly):

  +0x00 u32  flags/requirements word (0x02000060 typical; see FLAGS notes in the report)
  +0x04 u32[6][2]  per stage {offset, size} of its SMOL-V module, relative to the code start; 0,0 = absent
                   stage order: VS, FS, (others; never present in the reference data)
  ...   remaining u32s up to +0x50 (zero except the word at +0x4c)
  +0x50 u8[16][6]  per stage 128-bit hash of the module (0 when absent)
  +0xb0 modules, SMOL-V encoded ('SMOL' magic, version byte 1)

    python vk_shader.py <unity default resources> <outdir>     dump every Vulkan subprogram (spv + metadata)
"""
import json
import os
import struct
import sys

import smolv
from switch_shader import (MAGIC, R, Desync, parse_params, parse_subprogram, platform_segments, entry_table, entry_bytes,
                           iter_shaders, iter_variants)

HEADER = 0xb0


def parse_vk_code(code):
    if len(code) < HEADER:
        raise Desync('vk code too small')
    words = struct.unpack_from('<20I', code, 0)
    hashes = [code[0x50 + 16 * i:0x60 + 16 * i] for i in range(6)]
    mods = {}
    spans = []
    for i in range(6):
        off, size = words[1 + 2 * i], words[2 + 2 * i]
        if size:
            m = code[off:off + size]
            if m[:4] != b'LOMS':
                raise Desync(f'stage {i}: module is not SMOL-V')
            mods[i] = dict(smolv=m, hash=hashes[i])
            spans.append((off, off + size))
        elif any(hashes[i]):
            raise Desync('hash for absent stage')
    spans.sort()
    pos = HEADER
    for a, b in spans:
        if a != pos:
            raise Desync(f'gap in vk code at {pos:#x}')
        pos = b
    if pos != len(code):
        raise Desync('trailing bytes in vk code')
    return dict(flags=words[0], words=list(words), modules=mods)


def build_vk_code(flags, vs_spv, fs_spv, vs_hash, fs_hash, word_4c=1):
    """Unity writes the fragment module first, then the vertex module."""
    fs = smolv.encode(fs_spv)
    vs = smolv.encode(vs_spv)
    hdr = bytearray(HEADER)
    struct.pack_into('<I', hdr, 0, flags)
    struct.pack_into('<II', hdr, 4, HEADER + len(fs), len(vs))
    struct.pack_into('<II', hdr, 12, HEADER, len(fs))
    struct.pack_into('<I', hdr, 0x4c, word_4c)
    hdr[0x50:0x60] = vs_hash
    hdr[0x60:0x70] = fs_hash
    return bytes(hdr) + fs + vs


def build_subprogram(ptype, code, source_map, channels):
    b = struct.pack('<8I', MAGIC, ptype, 0, 0, 0, 0, 0, len(code)) + code
    b += b'\0' * (-len(b) % 4)
    b += struct.pack('<II', source_map, len(channels))
    for s, t in channels:
        b += struct.pack('<II', s, t)
    return b


def build_params(cbuffers, bindings):
    def s(x):
        x = x.encode()
        return struct.pack('<I', len(x)) + x + b'\0' * (-len(x) % 4)

    def param(p):
        return s(p['name']) + struct.pack('<6I', p['type'], p['rows'], p['cols'], int(p['matrix']), p['array'], p['offset'])
    b = struct.pack('<6I', MAGIC, len(cbuffers) + 1, 0, 0, 0, 0)
    for cb in cbuffers:
        b += s(cb['name']) + struct.pack('<II', cb['size'], len(cb['params']))
        for p in cb['params']:
            b += param(p)
        b += struct.pack('<I', len(cb.get('structs', [])))
        for st in cb.get('structs', []):
            b += s(st['name']) + struct.pack('<4I', st['offset'], st['array'], st['size'], len(st['members']))
            for p in st['members']:
                b += param(p)
    b += struct.pack('<I', len(bindings))
    for bd in bindings:
        b += s(bd['name']) + struct.pack('<II', bd['kind'], bd['index'])
        if bd['kind'] == 0:
            b += struct.pack('<iI', bd['sampler'], (bd['dim'] << 1) | bd.get('ms', 0))
        else:
            b += struct.pack('<I', bd.get('extra', 0))
    return b


def parse_params_raw(b):
    """like switch_shader.parse_params but keeps the raw 32-bit binding index"""
    d = parse_params(b)
    for bd in d['bindings']:
        bd['index'] = (bd.pop('stages') << 16) | bd.pop('slot')
    return d


def parse_subprogram_kw(b):
    """Vulkan subprograms in the default resources still carry inline keyword strings."""
    r = R(b)
    if r.u32() != MAGIC:
        raise Desync('magic')
    ptype = r.u32()
    stats = [r.i32() for _ in range(4)]
    kws = [r.string() for _ in range(r.u32())]
    code = r.raw(r.u32())
    r.o = (r.o + 3) & ~3
    source_map = r.u32()
    chans = [(r.u32(), r.u32()) for _ in range(r.u32())]
    if r.o != len(b):
        raise Desync(f'{len(b) - r.o} trailing bytes')
    return dict(type=ptype, stats=stats, keywords=kws, code=code, source_map=source_map, channels=chans)


def main():
    src, out = sys.argv[1], sys.argv[2]
    os.makedirs(out, exist_ok=True)
    n = 0
    for obj, tt in iter_shaders(src):
        name = tt['m_ParsedForm']['m_Name']
        safe = name.replace('/', '_').replace(' ', '_')
        segs = dict(platform_segments(tt)).get(18)
        if segs is None:
            continue
        ents = entry_table(segs)
        for si, pi, ps, prog, t, k, sp, pbi in iter_variants(tt):
            if sp['m_GpuProgramType'] != 25:
                continue
            sub = parse_subprogram_kw(entry_bytes(segs, ents[sp['m_BlobIndex']]))
            vk = parse_vk_code(sub['code'])
            par = parse_params_raw(entry_bytes(segs, ents[pbi]))
            base = os.path.join(out, f'{safe}_s{si}p{pi}_v{k}')
            meta = dict(shader=name, keywords=sub['keywords'], keyword_indices=sp['m_KeywordIndices'],
                        requirements=sp['m_ShaderRequirements'], source_map=sub['source_map'], channels=sub['channels'],
                        header_words=[hex(x) for x in vk['words']], params=par, modules={})
            for i, m in vk['modules'].items():
                spv = smolv.decode(m['smolv'])
                assert smolv.encode(spv) == m['smolv'], 'smolv re-encode mismatch'
                stage = ('vs', 'fs', 's2', 's3', 's4', 's5')[i]
                open(f'{base}.{stage}.spv', 'wb').write(spv)
                meta['modules'][stage] = dict(hash=m['hash'].hex(), smolv_bytes=len(m['smolv']), spv_bytes=len(spv))
            json.dump(meta, open(base + '.json', 'w'), indent=1)
            n += 1
    print('vulkan subprograms dumped:', n)


if __name__ == '__main__':
    main()
