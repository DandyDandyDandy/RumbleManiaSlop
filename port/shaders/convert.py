"""Convert Switch-only Unity 2022.3 Shader objects into Vulkan-only ones (spike of the full pipeline).

    python convert.py <in bundle|data.unity3d> <out> --shader NAME [--shader NAME ...] [--all] [--target 19]
                      [--work DIR] [--max-variants N]

For every selected Shader object:
  1. parse the Switch blob (switch_shader.py), translate each variant's VS and FS Maxwell code to SPIR-V (xlate.py),
  2. post-process the SPIR-V to Unity's Vulkan conventions (spv_fix.py), validate with spirv-val, shrink it with
     spirv-opt -O (validated again; --no-opt to skip),
  3. build Vulkan subprogram blobs (SMOL-V modules + header) and per-variant parameter blobs with Vulkan binding
     indices (vk_shader.py),
  4. rewrite the Shader object: platforms [19] -> [18], new LZ4 blob/offset tables, every player subprogram
     m_GpuProgramType 26 (ConsoleVS) -> 25 (SPIRV) with new blob / parameter-blob indices, m_CommonParameters emptied
     (their content moves into the per-variant parameter blobs), pass m_Platforms -> [18].
The file's build target is set to --target (19 = StandaloneWindows64) like port/assets/retarget.py.
"""
import argparse
import collections
import hashlib
import json
import os
import pickle
import struct
import subprocess
import sys

import lz4.block
import UnityPy
from UnityPy.enums import BuildTarget
from UnityPy.files import SerializedFile, BundleFile

import spv_fix
import vk_shader
import xlate
from switch_shader import entry_bytes, entry_table, parse_subprogram, platform_segments

VK_BASE_FLAGS = 0x02000020          # always set in the reference data
FLAG_DISCARD, FLAG_FRAG_DEPTH, FLAG_NO_SEPARATE_SAMPLERS = 0x01, 0x02, 0x40
CACHE_VERSION = b'br-vk-1'      # bump when xlate/spv_fix/vk_shader output changes
SEGMENT_LIMIT = 16 << 20      # entries are packed into chunks ("segments") of at most this many bytes


def merge_params(params):
    """merge common + variant entries that describe the same constant buffer / binding"""
    cbs = collections.OrderedDict()
    for cb in params['cbuffers']:
        c = cbs.setdefault(cb['name'], dict(name=cb['name'], size=0, params=[], structs=[]))
        c['size'] = max(c['size'], cb['size'])
        have = {p['name'] for p in c['params']}
        c['params'] += [p for p in cb['params'] if p['name'] not in have]
        have = {s['name'] for s in c['structs']}
        c['structs'] += [s for s in cb.get('structs', []) if s['name'] not in have]
    return list(cbs.values()), params['bindings']


def make_plan(bindings):
    """Vulkan binding assignment. Returns (per-stage spv_fix plans, Vulkan binding metadata list)."""
    stage_bits = {'vs': 2, 'fs': 4}
    cb_names = sorted({b['name'] for b in bindings if b['kind'] == 1})
    tex_names = sorted({b['name'] for b in bindings if b['kind'] == 0})
    if any(b['kind'] == 3 for b in bindings):
        raise ValueError('UAV bindings are not handled yet')
    buf_names = sorted({b['name'] for b in bindings if b['kind'] == 2})
    cb_bind = {n: i for i, n in enumerate(cb_names)}
    tex_bind = {n: i for i, n in enumerate(tex_names)}
    # sampler identities: the sampler of a texture, or an inline sampler state
    samp_ident = {}         # (stage bit, sampler slot) -> identity
    for b in bindings:
        for st, bit in stage_bits.items():
            if not b['stages'] & bit:
                continue
            if b['kind'] == 0 and b['sampler'] >= 0:
                samp_ident[(bit, b['sampler'])] = ('tex', b['name'])
            elif b['kind'] == 4:
                samp_ident[(bit, b['slot'])] = ('inline', b['extra'])
    idents = sorted(set(samp_ident.values()))
    samp_bind = {idt: len(tex_names) + i for i, idt in enumerate(idents)}
    buf_bind = {n: len(tex_names) + len(idents) + i for i, n in enumerate(buf_names)}
    plans = {st: dict(ubo={}, tex={}, samp={}, own_samp={}, inline={}, sbuf={}) for st in stage_bits}
    for b in bindings:
        for st, bit in stage_bits.items():
            if not b['stages'] & bit:
                continue
            if b['kind'] == 1:
                plans[st]['ubo'][str(b['slot'] + 3)] = cb_bind[b['name']]
            elif b['kind'] == 0:
                plans[st]['tex'][str(b['slot'])] = tex_bind[b['name']]
                if b['sampler'] >= 0:
                    plans[st]['own_samp'][str(b['slot'])] = b['sampler']
            elif b['kind'] == 4:
                plans[st]['inline'][str(b['slot'])] = b['extra']
            elif b['kind'] == 2:
                # Switch slot = 0x200 | storage block index (the only form in this game: 0x200)
                plans[st]['sbuf'][str(b['slot'] & 0xff)] = buf_bind[b['name']]
    for (bit, slot), idt in samp_ident.items():
        plans['vs' if bit == 2 else 'fs']['samp'][str(slot)] = samp_bind[idt]

    def vk_stages(mask):            # Switch: bit1 VS, bit2 FS  ->  Vulkan index bits 26 (VS), 27 (FS)
        return ((mask >> 1) & 3) << 26

    out = collections.OrderedDict()
    for b in bindings:
        if b['kind'] == 0:
            e = out.setdefault(('t', b['name']), dict(name=b['name'], kind=0, index=tex_bind[b['name']], sampler=-1,
                                                      dim=b['dim'], ms=b.get('ms', 0), _st=0))
            e['_st'] |= b['stages']
            if b['sampler'] >= 0:
                e['_samp'] = samp_bind[('tex', b['name'])]
        elif b['kind'] == 1:
            e = out.setdefault(('c', b['name']), dict(name=b['name'], kind=1, index=(1 << 16) | cb_bind[b['name']], extra=0, _st=0))
            e['_st'] |= b['stages']
        elif b['kind'] == 2:
            e = out.setdefault(('b', b['name']), dict(name=b['name'], kind=2, index=buf_bind[b['name']], extra=b['extra'], _st=0))
            e['_st'] |= b['stages']
        elif b['kind'] == 4:
            e = out.setdefault(('s', b['extra']), dict(name='', kind=4, index=samp_bind[('inline', b['extra'])], extra=b['extra'], _st=0))
            e['_st'] |= b['stages']
    meta = []
    for e in out.values():
        st = vk_stages(e.pop('_st'))
        e['index'] |= st
        if '_samp' in e:
            e['sampler'] = st | e.pop('_samp')
        meta.append(e)
    return plans, meta


SPIRV_VAL = xlate.paths.spirv_tool('spirv-val')
SPIRV_OPT = xlate.paths.spirv_tool('spirv-opt')


def spirv_val(path):
    """None when the module is valid (or when spirv-val is not installed: then nothing is checked)."""
    if SPIRV_VAL is None:
        return None
    p = subprocess.run([str(SPIRV_VAL), path], capture_output=True, text=True, errors='replace')
    return None if p.returncode == 0 else (p.stdout + p.stderr).strip()[:300]


def module_flags(vs, fs):
    flags = VK_BASE_FLAGS
    m = spv_fix.Module(fs)
    if any(i[0] == 252 for i in m.ins):                                     # OpKill
        flags |= FLAG_DISCARD
    if any(i[0] == 16 and i[1][1] == 12 for i in m.ins):                    # ExecutionMode DepthReplacing
        flags |= FLAG_FRAG_DEPTH
    if not any(i[0] == 26 for i in m.ins + spv_fix.Module(vs).ins):         # no OpTypeSampler
        flags |= FLAG_NO_SEPARATE_SAMPLERS
    return flags


def convert_tt(tt, work, max_variants=None, log=print, chunk_bytes=SEGMENT_LIMIT, cache=None, optimize=True, keep_work=False):
    """rewrite the Shader type tree dict in place; returns stats"""
    name = tt['m_ParsedForm']['m_Name']
    os.makedirs(work, exist_ok=True)
    segs = dict(platform_segments(tt))[19]
    ents = entry_table(segs)
    stats = collections.Counter()
    # 1. collect distinct (program blob, parameter blob) pairs
    variants = []
    for ss in tt['m_ParsedForm']['m_SubShaders']:
        for ps in ss['m_Passes']:
            pv = ps['progVertex']
            for t, lst in enumerate(pv['m_PlayerSubPrograms']):
                for k, sp in enumerate(lst[:max_variants] if max_variants else lst):
                    if sp['m_GpuProgramType'] != 26:
                        raise ValueError(f"unexpected program type {sp['m_GpuProgramType']}")
                    variants.append((ps, t, k, sp))
            for other in ('progFragment', 'progGeometry', 'progHull', 'progDomain', 'progRayTracing'):
                if any(ps[other]['m_PlayerSubPrograms']):
                    raise ValueError(f'{other} has programs')
    units = {}          # (blob index, param blob index, id of pass) -> unit
    jobs = []
    for ps, t, k, sp in variants:
        pbi = ps['progVertex']['m_ParameterBlobIndices'][t][k]
        key = (sp['m_BlobIndex'], pbi, id(ps))
        if key in units:
            continue
        raw_entry = entry_bytes(segs, ents[sp['m_BlobIndex']])
        cbs, bindings = merge_params(xlate.merged_params(ps, segs, ents, pbi))
        u = dict(key=f'u{len(units)}', cbs=cbs)
        units[key] = u
        # unit cache: the converted subprogram blob depends only on the Switch subprogram blob and its bindings
        u['ckey'] = hashlib.sha1(CACHE_VERSION + (b'O' if optimize else b'-') + raw_entry
                                 + json.dumps(bindings, sort_keys=True).encode()).hexdigest()
        if cache:
            cp_ = os.path.join(cache, u['ckey'][:2], u['ckey'])
            if os.path.exists(cp_):
                try:
                    with open(cp_, 'rb') as fh:
                        u.update(pickle.load(fh))
                    stats['units from cache'] += 1
                    continue
                except Exception:
                    pass
        sub = parse_subprogram(raw_entry)
        if set(sub['stages']) != {'vs', 'fs'}:
            raise ValueError(f"stages {sorted(sub['stages'])} not handled")
        u['plans'], u['meta'] = make_plan(bindings)
        u['sub'] = sub
        jobs += xlate.jobs_for(sub, dict(bindings=bindings), u['key'], work)
    log(f'{name}: {len(variants)} variants, {len(units)} distinct program/parameter units, {len(jobs)} programs to translate')
    res = {}
    for i in range(0, len(jobs), 400):
        res.update(xlate.run_jobs(jobs[i:i + 400], work))
    # 2. post-process, validate, build blobs
    new_entries = []        # bytes
    entry_index = {}        # content -> index

    def add_entry(b):
        if b not in entry_index:
            entry_index[b] = len(new_entries)
            new_entries.append(b)
        return entry_index[b]

    for u in units.values():
        if 'blob_bytes' not in u:
            spv = {}
            notes = []
            for st in ('vs', 'fs'):
                k = f"{u['key']}.{st}"
                if res[k]:
                    raise ValueError(f'{name}: translation failed: {res[k]}')
                with open(os.path.join(work, k + '.spv'), 'rb') as fh:
                    raw = fh.read()
                with open(os.path.join(work, k + '.res.json'), encoding='utf-8') as fh:
                    r = json.load(fh)
                fixed, nn = spv_fix.fix(raw, st, r, u['plans'][st], u['sub']['stages'][st]['c1'])
                notes += nn
                fp = os.path.join(work, k + '.vk.spv')
                with open(fp, 'wb') as fh:
                    fh.write(fixed)
                err = spirv_val(fp)
                if err:
                    raise ValueError(f'{name} {k}: spirv-val after post-processing: {err}')
                if optimize and SPIRV_OPT is not None:
                    op = fp + '.opt'
                    o = subprocess.run([str(SPIRV_OPT), '-O', fp, '-o', op], capture_output=True)
                    if o.returncode == 0 and spirv_val(op) is None:
                        with open(op, 'rb') as fh:
                            fixed = fh.read()
                    else:
                        notes.append('spirv-opt failed; unoptimised module kept')
                spv[st] = fixed
                if not keep_work:
                    for ext in ('.spv', '.res.json', '.vk.spv', '.vk.spv.opt', '.code'):
                        try:
                            os.remove(os.path.join(work, k + ext))
                        except OSError:
                            pass
            flags = module_flags(spv['vs'], spv['fs'])
            code = vk_shader.build_vk_code(flags, spv['vs'], spv['fs'], hashlib.md5(spv['vs']).digest(), hashlib.md5(spv['fs']).digest())
            chans = [(s, 13 + t) for s, t in u['sub']['channels']]
            blob = vk_shader.build_subprogram(25, code, u['sub']['source_map'], chans)
            if u['sub']['keywords']:
                # inline keyword strings sit between the stats and the code length
                kw = b''.join(struct.pack('<I', len(k)) + k.encode() + bytes(-len(k) % 4) for k in u['sub']['keywords'])
                blob = blob[:0x18] + struct.pack('<I', len(u['sub']['keywords'])) + kw + blob[0x1c:]
            rec = dict(blob_bytes=blob, meta=u['meta'], flags=flags, notes=notes)
            u.update(rec)
            del u['sub']
            if cache:
                d = os.path.join(cache, u['ckey'][:2])
                os.makedirs(d, exist_ok=True)
                tmp = os.path.join(d, f"{u['ckey']}.{os.getpid()}.tmp")
                with open(tmp, 'wb') as fh:
                    pickle.dump(rec, fh)
                os.replace(tmp, os.path.join(d, u['ckey']))
        for n in u['notes']:
            stats['note: ' + n] += 1
        stats['units'] += 1
        stats[f"flags {u['flags']:#x}"] += 1
        u['params_index'] = add_entry(vk_shader.build_params(u['cbs'], u['meta']))
    for u in units.values():
        u['blob_index'] = add_entry(u['blob_bytes'])
    # 3. blob container: entry table + entries in segment 0 (more segments past SEGMENT_LIMIT)
    table_size = 4 + 12 * len(new_entries)
    seg_data = [bytearray(table_size)]
    table = []
    for e in new_entries:
        if len(seg_data[-1]) + len(e) > chunk_bytes and len(seg_data[-1]) > (table_size if len(seg_data) == 1 else 0):
            seg_data.append(bytearray())
        table.append((len(seg_data[-1]), len(e), len(seg_data) - 1))
        seg_data[-1] += e
    struct.pack_into('<I', seg_data[0], 0, len(new_entries))
    for i, t in enumerate(table):
        struct.pack_into('<III', seg_data[0], 4 + 12 * i, *t)
    comp = b''
    offs, clens, dlens = [], [], []
    for s in seg_data:
        c = lz4.block.compress(bytes(s), mode='high_compression', store_size=False)
        offs.append(len(comp)); clens.append(len(c)); dlens.append(len(s))
        comp += c
    # 4. type tree
    tt['platforms'] = [18]
    tt['offsets'] = [offs]
    tt['compressedLengths'] = [clens]
    tt['decompressedLengths'] = [dlens]
    tt['compressedBlob'] = comp if isinstance(tt['compressedBlob'], (bytes, bytearray)) else list(comp)
    tt['stageCounts'] = [1]
    done = set()
    for ps, t, k, sp in variants:
        pv = ps['progVertex']
        u = units[(sp['m_BlobIndex'], pv['m_ParameterBlobIndices'][t][k], id(ps))]
        done.add(id(sp))
        sp['_new'] = (u['blob_index'], u['params_index'])
    for ps, t, k, sp in variants:
        pv = ps['progVertex']
        b, p = sp.pop('_new')
        sp['m_BlobIndex'] = b
        sp['m_GpuProgramType'] = 25
        pv['m_ParameterBlobIndices'][t][k] = p
    for ss in tt['m_ParsedForm']['m_SubShaders']:
        for ps in ss['m_Passes']:
            ps['m_Platforms'] = [18] if isinstance(ps['m_Platforms'], list) else ps['m_Platforms']
            pv = ps['progVertex']
            if max_variants:        # drop the variants that were not converted
                for t, lst in enumerate(pv['m_PlayerSubPrograms']):
                    keep = [i for i, sp in enumerate(lst) if id(sp) in done]
                    pv['m_PlayerSubPrograms'][t] = [lst[i] for i in keep]
                    pv['m_ParameterBlobIndices'][t] = [pv['m_ParameterBlobIndices'][t][i] for i in keep]
            cp = pv['m_CommonParameters']
            for key in cp:
                cp[key] = []
    stats['entries'] = len(new_entries)
    stats['chunks'] = len(seg_data)
    stats['blob bytes'] = sum(dlens)
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--shader', action='append', default=[])
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--target', type=int, default=19)
    ap.add_argument('--work', default=None)
    ap.add_argument('--max-variants', type=int, default=None, help='keep only the first N variants of every pass')
    ap.add_argument('--chunk-bytes', type=int, default=SEGMENT_LIMIT, help='blob chunk size (test multi-chunk blobs)')
    ap.add_argument('--cache', default=None, help='unit cache directory')
    ap.add_argument('--no-opt', action='store_true', help='skip spirv-opt -O')
    ap.add_argument('--keep-work', action='store_true')
    ap.add_argument('--neutralize', action='store_true', help='strip the subshaders of shaders that fail to convert')
    a = ap.parse_args()
    work = a.work or (a.dst + '.work')
    env = UnityPy.load(a.src)
    n = 0
    for obj in env.objects:
        if obj.type.name != 'Shader':
            continue
        tt = obj.read_typetree()
        name = tt['m_ParsedForm']['m_Name']
        if not (a.all or name in a.shader):
            continue
        if tt['platforms'] != [19]:
            continue
        try:
            st = convert_tt(tt, os.path.join(work, hashlib.sha1(name.encode()).hexdigest()[:10]), a.max_variants, chunk_bytes=a.chunk_bytes, cache=a.cache, optimize=not a.no_opt, keep_work=a.keep_work)
        except Exception as e:
            print(f'FAILED {name}: {e}')
            if a.neutralize:
                # leave no Switch program behind: the Vulkan player crashes in ShaderLab::SubProgram::Compile on them
                tt = obj.read_typetree()
                tt['m_ParsedForm']['m_SubShaders'] = []
                obj.save_typetree(tt)
            continue
        obj.save_typetree(tt)
        n += 1
        print(f'converted {name}: ' + ', '.join(f'{k}={v}' for k, v in sorted(st.items())))
    # player data: declare Vulkan as the build's graphics API (GfxDeviceRenderer 21) instead of Switch NVN (22), and
    # give the Vulkan shader compiler platform (18) the built-in define set the build recorded for Switch (19)
    for obj in env.objects:
        if obj.type.name == 'BuildSettings':
            tt = obj.read_typetree()
            print('BuildSettings.m_GraphicsAPIs', tt['m_GraphicsAPIs'], '-> [21]')
            tt['m_GraphicsAPIs'] = [21]
            obj.save_typetree(tt)
        elif obj.type.name == 'GraphicsSettings':
            tt = obj.read_typetree()
            for d in tt['m_ShaderDefinesPerShaderCompiler']:
                if d['shaderPlatform'] == 19:
                    d['shaderPlatform'] = 18
            obj.save_typetree(tt)
    tgt = BuildTarget(a.target)

    def walk(f):
        if isinstance(f, SerializedFile):
            f.target_platform = tgt
            f._m_target_platform = int(a.target)
            f.mark_changed()
        elif hasattr(f, 'files'):
            for c in f.files.values():
                walk(c)
    root = env.file
    walk(root)
    data = root.save(packer='lz4') if isinstance(root, BundleFile) else root.save()
    open(a.dst, 'wb').write(data)
    print(f'{n} shaders converted, wrote {a.dst} ({len(data)} bytes)')


if __name__ == '__main__':
    main()
