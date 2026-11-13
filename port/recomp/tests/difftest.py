"""Differential test of the port's generated C against Unicorn, whole functions, including exception unwinding.

Built on xc2-recomp tests/diff/func.py and common.py (MIT, Copyright (c) 2026 Peiikai), which are imported unmodified
from the upstream checkout: the Unicorn runner, the random states, the call stub and the harness protocol are theirs.
See func.py's docstring for the method. What this adds:

  * functions come from the port's lift set and are emitted by gen_il2cpp.Il2cppEmitter (FDE ends, EH checks);
  * a call can throw (tests/eh_harness.c eh_after, EhRunner.stub here): at a call site with a landing pad the C side
    gets c->eh_unwinding set with X19-X29, SP and V8-V15 trashed, and must arrive at the pad with the state the real
    unwinder gives (Unicorn simply continues at the pad with x0/x1 set), or leave the function when rt_eh_enter says
    no handler; calls to __cxa_throw / _Unwind_Resume / __cxa_rethrow from a site without a pad end the function.

Usage: difftest.py [--functions N] [--cases K] [--seed S] [--jobs J]      (needs unicorn; use upstream's .venv)
Work files go to port/build/difftest.
"""
import argparse
import os
import random
import subprocess
import sys
import time
import zlib
from collections import Counter
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import gen_il2cpp as g  # noqa: E402  (puts upstream recomp/ and tools/ on sys.path)

sys.path.insert(0, str(g.UPSTREAM / 'tests' / 'diff'))
import func  # noqa: E402
import unicorn as uc  # noqa: E402
from common import (MSYS_BIN, chunk_rng, compiler, diff_state, run_chunks, run_harness, split)  # noqa: E402
from unicorn import arm64_const as A  # noqa: E402

import ehtab  # noqa: E402
import gen as up  # noqa: E402
from module import Module  # noqa: E402

M64 = func.M64
EH_EXC = func.PTR_LO + 0x100
THROWERS = ('__cxa_throw', '__cxa_rethrow', '_Unwind_Resume', '_ZSt17rethrow_exceptionSt13exception_ptr')
WORK = g.PORT / 'build' / 'difftest'
MUTATE = False


def check_function(emitter, entry, end):
    """func.check_function, but a function may end in a call (a noreturn callee: throw helpers, terminate)."""
    mod = emitter.mod
    insns = [mod.lift(a) for a in range(entry, end, 4)]
    if insns[-1].kind not in up.TERMINATORS + ('bl',) or not any(i.kind == 'ret' for i in insns):
        return None
    tags = set()
    for k, ins in enumerate(insns):
        a = entry + 4 * k
        if ins.kind in ('bl', 'blr'):
            tags.add('calls')
        if ins.kind in ('b', 'bcond'):
            if not entry <= ins.target < end:
                return None
            if ins.target <= a:
                tags.add('loop')
        if ins.kind == 'br':
            if up.jumptables.resolve(mod, a, entry, end):
                tags.add('jump_table')
            elif up.jumptables.is_computed(mod, a, entry):
                tags.add('all_label_fallback')
            else:
                return None
        if ins.kind == 'trap':
            return None
    if func.simd_mask(mod.words[(entry - mod.lo) >> 2:(end - mod.lo) >> 2]).any():
        tags.add('simd')
    return tags


def covered_sites(emitter, entry, end):
    """{return address: (pad, action)} of the function's calls that have a landing pad."""
    lsda, sites = emitter.eh_sites(entry, end)
    out = {}
    for a in func.call_sites(emitter.mod, entry, end):
        for s, e, pad, action in sites:
            if s <= a + 3 < e:
                out[a + 4] = (pad, action)
    return out


def pick(mod, emitter, S, E, count, r):
    w = mod.words
    s_i, e_i = (S - mod.lo) >> 2, (E - mod.lo) >> 2

    def per_fn(mask):
        cs = np.concatenate([[0], np.cumsum(mask.astype(np.int64))])
        return cs[e_i] - cs[s_i]

    size = e_i - s_i
    ok = (per_fn(func.forbidden_mask(w)) == 0) & (size >= func.MIN_INSNS) & (size <= func.MAX_INSNS)
    has_call = per_fn(func.call_mask(w)) > 0
    has_br = per_fn((w & 0xFFFFFC1F) == 0xD61F0000) > 0
    lsda = {f.start for f in emitter.fdes if f.lsda and any(s[2] for s in f.sites)}
    cand = np.flatnonzero(ok).tolist()
    pools = {'pads': [i for i in cand if int(S[i]) in lsda],
             'br': [i for i in cand if has_br[i] and int(S[i]) not in lsda],
             'calls': [i for i in cand if has_call[i] and not has_br[i] and int(S[i]) not in lsda],
             'leaf': [i for i in cand if not has_call[i] and not has_br[i]]}
    picks = []
    for name, quota in (('pads', count * 2 // 5), ('br', count // 10), ('calls', count // 4), ('leaf', count)):
        pool = pools[name]
        r.shuffle(pool)
        taken = 0
        for i in pool:
            if len(picks) >= count or taken >= quota:
                break
            entry, end = int(S[i]), int(E[i])
            tags = check_function(emitter, entry, end)
            if tags is None:
                continue
            sites = covered_sites(emitter, entry, end)
            if name == 'pads' and not sites:
                continue
            if sites:
                tags.add('pads')
            picks.append((entry, end, tags, sites))
            taken += 1
    picked = {p[0] for p in picks}
    picks = [p for p in picks if not func.callees(emitter, p[0], p[1]) & picked]
    print(f'{len(cand)} candidates, picked {len(picks)}: {dict(Counter(t for p in picks for t in p[2]))}', flush=True)
    return picks


def build(picks, emitter, throwers, jobs):
    cc = compiler()
    env = dict(os.environ, PATH=str(MSYS_BIN) + os.pathsep + os.environ.get('PATH', ''))
    harness = (g.UPSTREAM / 'tests' / 'diff' / 'harness.c').as_posix()
    flags = ['-O1', '-fno-strict-aliasing', '-Wno-return-type', '-Wno-unused-label', '-march=x86-64-v3',
             '-I', str(g.PORT / 'runtime' / 'include'), f'-DUPSTREAM_HARNESS="{harness}"']
    fns = [(e, n) for e, n, _, _ in picks]
    srcs, n, called = [], max(1, jobs), set()
    per = (len(fns) + n - 1) // n
    for j in range(0, len(fns), per):
        path = WORK / f'fn_{j // per:03d}.c'
        text, refs = g.chunk_text(j // per, emitter, fns[j:j + per])
        if MUTATE:   # --mutate: drop the callee-saved restore before a pad; the test must then fail
            text = text.replace('eh_restore(c, &ehs);', '')
        path.write_text(text)
        called |= refs   # callees, and the function after one that ends in a (noreturn) call
        srcs.append(path)
    called -= {e for e, _ in fns}
    rets = sorted(a for p in picks for a in p[3])
    (WORK / 'table.c').write_text(
        '#include "cpu.h"\n' + ''.join(f'void {g.fname(e)}(Cpu *c);\n' for e, _ in fns) +
        'GuestFn tests[] = {' + ','.join(g.fname(e) for e, _ in fns) + '};\n' + f'int ntests = {len(fns)};\n' +
        'void rt_stub_call(Cpu *c, uint64_t target);\n' +
        ''.join(f'void {g.fname(t)}(Cpu *c) {{ rt_stub_call(c, {hex(t)}ull); }}\n' for t in sorted(called)) +
        'const uint64_t eh_rets[] = {' + ','.join(f'{a:#x}ull' for a in rets) + (',' if rets else '') + '0};\n' +
        f'const int eh_nrets = {len(rets)};\n' +
        'const uint64_t eh_throwers[] = {' + ','.join(f'{a:#x}ull' for a in throwers) + '};\n' +
        f'const int eh_nthrowers = {len(throwers)};\n')
    srcs += [WORK / 'table.c', HERE / 'eh_harness.c']
    objs, procs = [], []
    for s in srcs:
        o = WORK / (s.stem + '.o')
        objs.append(o)
        procs.append(subprocess.Popen([cc] + flags + ['-c', str(s), '-o', str(o)], env=env))
    if any(p.wait() for p in procs):
        raise SystemExit('compile failed')
    exe = WORK / 'difftest.exe'
    subprocess.check_call([cc, '-fuse-ld=lld', '-o', str(exe)] + [str(o) for o in objs], env=env)
    return exe


class EhRunner(func.Runner):
    """func.Runner whose stub can throw (eh_harness.c eh_after)."""

    def __init__(self, images, buf0, sites, covered, throwers):
        super().__init__(images, buf0, sites)
        self.covered, self.throwers = covered, throwers
        self.threw = Counter()

    def stub(self, a):
        e, mu = self.emu, self.emu.mu
        w = int.from_bytes(mu.mem_read(a, 4), 'little')
        if (w & 0xFC000000) == 0x94000000:
            imm = w & 0x03FFFFFF
            target = (a + ((imm - (1 << 26) if imm >> 25 else imm) << 2)) & M64
        else:
            target = mu.reg_read(e.xregs[(w >> 5) & 31])
        resume = super().stub(a)
        h = self.h
        thrower = target in self.throwers
        site = self.covered.get(a + 4)
        if site and (thrower or (h >> 8) & 3 == 0):
            # eh_restore gives V8-V15 back with their upper halves zero (only D8-D15 are callee-saved).
            mu.reg_write_batch([(e.qregs[i], mu.reg_read(e.qregs[i]) & M64) for i in range(8, 16)])
            if (h >> 20) & 7 == 0:
                self.threw['pad_site_no_handler'] += 1
                return None
            mu.reg_write_batch([(e.xregs[0], EH_EXC), (e.xregs[1], (h >> 12) & 3)])
            self.threw['pad_entered'] += 1
            return site[0]
        if thrower:
            self.threw['thrown_out'] += 1
            return None
        return resume

    def run(self, entry, end, case, steps):
        fpcr, x, sp, nzcv, v = case
        e, mu = self.emu, self.emu.mu
        self.lo, self.hi, self.left, self.h = entry, end, False, 0
        mu.reg_write_batch(list(zip(e.xregs, x[:31])) + list(zip(e.qregs, v)) +
                           [(A.UC_ARM64_REG_SP, sp), (A.UC_ARM64_REG_NZCV, nzcv), (A.UC_ARM64_REG_FPCR, fpcr)])
        pc, ok = entry, False
        before = Counter(self.threw)
        try:
            for _ in range(self.MAX_CALLS):
                self.at_call = None
                mu.emu_start(pc, func.SENTINEL, count=steps)
                if self.at_call is None:
                    ok = not self.left and mu.reg_read(A.UC_ARM64_REG_PC) == func.SENTINEL
                    break
                pc = self.stub(self.at_call)
                if pc is None:   # the exception left the function
                    ok = True
                    break
        except uc.UcError:
            ok = False
        if not ok:
            self.threw = before
            mu.mem_write(func.BUF, self.buf0)
            return None
        o = mu.reg_read_batch(e.out_regs)
        crc = zlib.crc32(bytes(mu.mem_read(func.BUF, func.BUF_SIZE)))
        mu.mem_write(func.BUF, self.buf0)
        return list(o[:31]), o[31], o[32] & 0xF0000000, o[33], list(o[34:]), crc


W = {}


def worker_init(images, buf0, sites, covered, throwers, funcs, exe, ncases, steps, seed):
    runner = EhRunner([(base, Path(img).read_bytes()) for base, img in images], buf0, sites, covered, throwers)
    W.update(runner=runner, images=images, buf0=buf0, funcs=funcs, exe=exe, cases=ncases, steps=steps, seed=seed)


def run_chunk(chunk):
    index, lo, hi = chunk
    r = chunk_rng(W['seed'], index)
    runner, funcs = W['runner'], W['funcs']
    runner.threw = Counter()
    cases, expect, tested, skipped = [], [], set(), 0
    for k in range(lo, hi):
        entry, end = funcs[k]
        for _ in range(W['cases']):
            case = func.make_case(r)
            want = runner.run(entry, end, case, W['steps'])
            if want is None:
                skipped += 1
                continue
            fpcr, x, sp, nzcv, v = case
            cases.append((k, fpcr, x, sp, nzcv, v, True))
            expect.append(want)
            tested.add(k)
    work = WORK / f'chunk{index}'
    work.mkdir(parents=True, exist_ok=True)
    recs, err = run_harness(W['exe'], work, W['buf0'], cases, W['images'], stubs=True)
    if err:
        k = cases[len(recs)][0] if len(recs) < len(cases) else None
        err += f', stopped in {funcs[k][0]:#x}' if k is not None else ''
    fails, nfail = {}, 0
    for case, want, got in zip(cases, expect, recs):
        d = diff_state(got, want, check_pc=False, check_mem=True, check_nzcv=False)
        if d:
            nfail += 1
            fails.setdefault(case[0], d[:4])
    return len(cases), len(recs), nfail, fails, err, tested, skipped, dict(runner.threw)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--functions', type=int, default=600)
    ap.add_argument('--cases', type=int, default=16)
    ap.add_argument('--steps', type=int, default=200000)
    ap.add_argument('--seed', type=int, default=1)
    ap.add_argument('--jobs', type=int, default=os.cpu_count() or 4)
    ap.add_argument('--show', type=int, default=20)
    ap.add_argument('--mutate', action='store_true', help='self-check: break eh_restore, expect failures')
    args = ap.parse_args()
    global MUTATE
    MUTATE = args.mutate
    r = random.Random(args.seed)
    t0 = time.time()
    WORK.mkdir(parents=True, exist_ok=True)
    nso = g.REPO / 'work' / 'game' / 'exefs' / 'main'
    mod = Module('main', nso, g.BASE, 'c')
    starts, _ = up.discover(mod)
    S = mod.lo + starts * 4
    nxt = np.append(S[1:], mod.hi)
    ls, le = g.lift_ranges(g.REPO / 'work' / 'unity' / 'closure')
    f = np.searchsorted(ls, S, side='right') - 1
    fz = np.maximum(f, 0)
    inside = (f >= 0) & (S < le[fz])
    eS, eE = S[inside], np.minimum(nxt, le[fz])[inside]
    emitter = g.Il2cppEmitter(mod, set(S.tolist()), ehtab.read(mod))
    throwers = sorted(a for a, (_, sym) in g.plt_stubs(mod).items() if sym in THROWERS)
    picks = pick(mod, emitter, eS, eE, args.functions, r)
    img = WORK / 'main.img'
    img.write_bytes(mod.image)
    exe = build(picks, emitter, throwers, args.jobs)
    print(f'compiled ({time.time() - t0:.0f}s)', flush=True)
    buf0 = func.make_buffer(r)
    sites, covered = set(), {}
    for entry, end, _, cov in picks:
        sites.update(func.call_sites(mod, entry, end))
        covered.update(cov)
    res = run_chunks(run_chunk, split(len(picks), func.CHUNK), args.jobs, worker_init,
                     ([(g.BASE, img)], buf0, sites, covered, set(throwers), [p[:2] for p in picks], exe, args.cases,
                      args.steps, args.seed))
    ncases, nrecs, skipped = sum(x[0] for x in res), sum(x[1] for x in res), sum(x[6] for x in res)
    tested = set().union(*(x[5] for x in res))
    threw = Counter()
    for x in res:
        threw.update(x[7])
    errs = [x[4] for x in res if x[4]]
    for e in errs:
        print(f'harness failed: {e}')
    nfail = sum(x[2] for x in res)
    fails = {}
    for x in res:
        fails.update(x[3])
    by_tag, fail_tag = Counter(), Counter()
    for k in tested:
        by_tag.update(picks[k][2] or {'plain'})
        if k in fails:
            fail_tag.update(picks[k][2] or {'plain'})
    print(f'{len(tested)} functions tested, {nrecs} of {ncases} cases run ({skipped} skipped by Unicorn): '
          f'{nfail} failing cases, {len(fails)} failing functions ({time.time() - t0:.0f}s)')
    print(f'  tested by tag: {dict(by_tag)}; failing by tag: {dict(fail_tag)}')
    print(f'  exception events in the compared cases: {dict(threw)}')
    for k, d in list(fails.items())[:args.show]:
        entry, end, tags, _ = picks[k]
        print(f'  {g.fname(entry)} ({(end - entry) // 4} insns, {sorted(tags)}): {"; ".join(d)}')
    return 1 if fails or errs else 0


if __name__ == '__main__':
    sys.exit(main())
