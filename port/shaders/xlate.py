"""Translate Switch (Maxwell) programs of a Unity shader to SPIR-V with the Ryujinx-based translator.

    python xlate.py one <file> <shader name> <outdir> [--variant K] [--pass P] [--sub S]
        extract VS/FS of one variant, translate, validate, write .spv/.res.json/.dis/.glsl and params.json
    python xlate.py sample <Data dir> <outdir> [--per-shader N] [--max M]
        translate a sample across all shaders, report success rate and failure reasons

Translator: third_party/xlate/xc2_xlate.exe (bindings all in set 0; spv_fix.py moves them to Unity's conventions).
spirv-val / spirv-dis / spirv-cross are used when they are there (port/paths.py: SPIRV_TOOLS_BIN).
"""
import argparse
import collections
import hashlib
import json
import os
import struct
import subprocess
import sys

from switch_shader import (Desync, common_params, entry_bytes, entry_table, iter_shaders, iter_variants, parse_params,
                           parse_subprogram, platform_segments)

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import paths  # noqa: E402

XLATE = os.environ.get('XLATE') or str(paths.XLATE)
DIMS = {1: '1d', 2: '2d', 3: '3d', 4: 'cube', 5: '2darray', 6: 'cubearray'}   # Unity TextureDimension


def merged_params(ps, segs, ents, pbi):
    """pass-common parameters + the variant's parameter blob"""
    names = {v: k for k, v in ps['m_NameIndices']}
    out = common_params(ps['progVertex']['m_CommonParameters'], names)
    if pbi is not None:
        pb = parse_params(entry_bytes(segs, ents[pbi]))
        out['cbuffers'] += pb['cbuffers']
        out['bindings'] += pb['bindings']
    return out


def tex_table(params, stage_bit):
    t = {}
    for b in params['bindings']:
        if b['kind'] == 0 and b['stages'] & stage_bit:
            t[str(b['slot'])] = DIMS.get(b['dim'], '2d') + ('ms' if b.get('ms') else '')
    return t


def jobs_for(sub, params, key, outdir):
    """write code files, return translator jobs for the VS and FS of a parsed subprogram"""
    jobs = []
    nloc = max([t for _, t in sub['channels']], default=-1) + 1
    for st, bit, name in (('vs', 2, 'vs'), ('fs', 4, 'ps')):
        if st not in sub['stages']:
            continue
        s = sub['stages'][st]
        code = s['data'][0x30:]
        path = os.path.join(outdir, f'{key}.{st}.code')
        open(path, 'wb').write(code)
        job = dict(key=f'{key}.{st}', stage=name, code=path, c1=s['c1'].hex(), debug=False, tex=tex_table(params, bit))
        if st == 'vs':
            job['attr'] = {str(i): 'float' for i in range(nloc)}
        if st == 'fs' and s['control'][0x718] & 1:
            job['early_fragment_tests'] = True
        jobs.append(job)
    return jobs


def run_jobs(jobs, outdir):
    """returns {key: error or None}"""
    jp = os.path.join(outdir, 'jobs.json')
    json.dump(jobs, open(jp, 'w'))
    p = subprocess.run([XLATE, jp, outdir], capture_output=True, text=True, encoding='utf-8', errors='replace')
    res = {j['key']: None for j in jobs}
    for line in p.stderr.splitlines():
        for k in res:
            if k in line:
                res[k] = line.split(k, 1)[1].lstrip('：: ')
    for k in res:
        if res[k] is None and not os.path.exists(os.path.join(outdir, k + '.spv')):
            res[k] = 'no output: ' + p.stderr[-300:]
    return res


def tool(name, *args):
    exe = paths.spirv_tool(name[:-4])
    if exe is None:
        return subprocess.CompletedProcess([name], 0, '', '')         # tool not installed: nothing to report
    return subprocess.run([str(exe), *args], capture_output=True, text=True, errors='replace')


def find_variant(path, shader, sub_i, pass_i, k):
    for obj, tt in iter_shaders(path):
        if tt['m_ParsedForm']['m_Name'] != shader:
            continue
        segs = dict(platform_segments(tt))[19]
        ents = entry_table(segs)
        for si, pi, ps, prog, t, kk, sp, pbi in iter_variants(tt):
            if (si, pi, kk) == (sub_i, pass_i, k):
                sub = parse_subprogram(entry_bytes(segs, ents[sp['m_BlobIndex']]))
                return tt, ps, sp, sub, merged_params(ps, segs, ents, pbi)
    raise SystemExit('variant not found')


def cmd_one(a):
    os.makedirs(a.out, exist_ok=True)
    tt, ps, sp, sub, params = find_variant(a.file, a.shader, a.sub, a.pass_, a.variant)
    key = 'v'
    kw = [tt['m_ParsedForm']['m_KeywordNames'][i] for i in sp['m_KeywordIndices']]
    meta = dict(shader=a.shader, pass_name=ps['m_State']['m_Name'], keywords=kw, source_map=sub['source_map'],
                channels=sub['channels'], params=params,
                stages={st: dict(code_bytes=len(s['sph_code']), c1_bytes=len(s['c1']), data_bytes=len(s['data']),
                                 sph=s['data'][0x30:0x80].hex()) for st, s in sub['stages'].items()})
    json.dump(meta, open(os.path.join(a.out, 'params.json'), 'w'), indent=1)
    jobs = jobs_for(sub, params, key, a.out)
    res = run_jobs(jobs, a.out)
    for k, err in res.items():
        spv = os.path.join(a.out, k + '.spv')
        if err:
            print(k, 'FAILED', err)
            continue
        v = tool('spirv-val.exe', spv)
        print(k, 'translated;', 'spirv-val OK' if v.returncode == 0 else 'spirv-val FAILED: ' + (v.stdout + v.stderr)[:400])
        open(os.path.join(a.out, k + '.dis'), 'w').write(tool('spirv-dis.exe', spv).stdout)
        g = tool('spirv-cross.exe', '-V', spv)
        open(os.path.join(a.out, k + '.glsl'), 'w').write(g.stdout if g.returncode == 0 else 'spirv-cross failed: ' + g.stderr)


def cmd_sample(a):
    os.makedirs(a.out, exist_ok=True)
    files = [os.path.join(a.data, 'data.unity3d')]
    for root, _, fs in os.walk(os.path.join(a.data, 'StreamingAssets', 'aa')):
        files += [os.path.join(root, f) for f in fs if f.endswith('.bundle')]
    seen = set()
    done_code = {}
    stats = collections.Counter()
    fails = collections.Counter()
    fail_examples = {}
    total = 0
    for f in files:
        with open(f, 'rb') as fh:
            if fh.read(7) != b'UnityFS':
                continue
        try:
            shaders = list(iter_shaders(f))
        except Exception:
            continue
        for obj, tt in shaders:
            name = tt['m_ParsedForm']['m_Name']
            if name in seen:
                continue
            seen.add(name)
            segs = dict(platform_segments(tt))[19]
            ents = entry_table(segs)
            variants = list(iter_variants(tt))
            # spread the sample over the shader's passes/variants
            step = max(1, len(variants) // a.per_shader)
            picked = variants[::step][:a.per_shader]
            jobs = []
            for si, pi, ps, prog, t, k, sp, pbi in picked:
                sub = parse_subprogram(entry_bytes(segs, ents[sp['m_BlobIndex']]))
                params = merged_params(ps, segs, ents, pbi)
                key = hashlib.sha1(f'{name}/{si}/{pi}/{k}'.encode()).hexdigest()[:16]
                for j in jobs_for(sub, params, key, a.out):
                    h = hashlib.sha1(open(j['code'], 'rb').read() + json.dumps(j['tex'], sort_keys=True).encode()).hexdigest()
                    if h in done_code:
                        stats['duplicate programs skipped'] += 1
                        os.remove(j['code'])
                        continue
                    done_code[h] = j['key']
                    j['_shader'] = name
                    jobs.append(j)
            if not jobs:
                continue
            res = run_jobs([{k: v for k, v in j.items() if k != '_shader'} for j in jobs], a.out)
            for j in jobs:
                err = res[j['key']]
                stage = j['key'].rsplit('.', 1)[1]
                stats[f'{stage} programs'] += 1
                spv = os.path.join(a.out, j['key'] + '.spv')
                if err is None:
                    v = tool('spirv-val.exe', spv)
                    if v.returncode != 0:
                        err = 'spirv-val: ' + (v.stdout + v.stderr).strip().splitlines()[0][:160]
                if err is None:
                    stats[f'{stage} ok'] += 1
                    notes = json.load(open(os.path.join(a.out, j['key'] + '.res.json'), encoding='utf-8'))['notes']
                    if notes:
                        stats[f'{stage} ok with translator notes'] += 1
                else:
                    stats[f'{stage} FAILED'] += 1
                    fails[err[:120]] += 1
                    fail_examples.setdefault(err[:120], f"{name} {j['key']}")
                for ext in ('.spv', '.res.json'):
                    if not a.keep and os.path.exists(os.path.join(a.out, j['key'] + ext)):
                        os.remove(os.path.join(a.out, j['key'] + ext))
                if not a.keep or err is None:
                    os.remove(j['code'])
                total += 1
            print(f'{len(seen)} shaders, {total} programs', file=sys.stderr, flush=True)
            if total >= a.max:
                break
        if total >= a.max:
            break
    print('translator:', XLATE)
    print('shaders sampled:', len(seen))
    for k in sorted(stats):
        print(f'{stats[k]:>8}  {k}')
    print('failure reasons:')
    for k, v in fails.most_common():
        print(f'{v:>8}  {k}   e.g. {fail_examples[k]}')


def main():
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest='cmd', required=True)
    o = sp.add_parser('one')
    o.add_argument('file'); o.add_argument('shader'); o.add_argument('out')
    o.add_argument('--variant', type=int, default=0); o.add_argument('--pass', dest='pass_', type=int, default=0)
    o.add_argument('--sub', type=int, default=0)
    s = sp.add_parser('sample')
    s.add_argument('data'); s.add_argument('out')
    s.add_argument('--per-shader', type=int, default=4); s.add_argument('--max', type=int, default=600)
    s.add_argument('--keep', action='store_true')
    a = ap.parse_args()
    (cmd_one if a.cmd == 'one' else cmd_sample)(a)


if __name__ == '__main__':
    main()
