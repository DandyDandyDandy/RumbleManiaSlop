"""callees.py ADDR[,ADDR...]: direct call/branch targets of the function(s) at these NSO offsets, named from
methods.tsv, the P/Invoke boundary table and the PLT (imports). Run with the xc2-recomp venv python (capstone)."""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), 'tools'))
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import bisect
import csv
import re
import sys

import capstone
import numpy as np

ROOT = REPO
d = open(W + r'\work\re\main.bin', 'rb').read()
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
md.skipdata = True
z = np.load(W + r'\work\unity\closure\closure.npz', allow_pickle=True)
fs, fe = z['fs'], z['fe']
methods = sorted((int(r['address'], 16), r['type'] + '::' + r['method'])
                 for r in csv.DictReader(open(W + r'\work\unity\methods.tsv', encoding='utf-8'), delimiter='\t') if r['address'])
maddr = [a for a, _ in methods]
natives = {int(r['target'], 16): r['identification']
           for r in csv.DictReader(open(W + r'\work\unity\closure\boundary_direct.tsv', encoding='utf-8'), delimiter='\t')}
plt = {}
try:
    for r in csv.DictReader(open(W + r'\generated\plt_stubs.tsv', encoding='utf-8'), delimiter='\t'):
        plt[int(r['nso_offset'], 16)] = 'import ' + r['symbol']
except OSError:
    pass


def name(a):
    if a in natives:
        return natives[a]
    if a in plt:
        return plt[a]
    i = bisect.bisect_right(maddr, a) - 1
    if i >= 0 and maddr[i] == a:
        return methods[i][1]
    return ''


for arg in sys.argv[1].split(','):
    a = int(arg, 16)
    i = int(np.searchsorted(fs, a, side='right')) - 1
    lo, hi = int(fs[i]), int(fe[i])
    print(f'== {lo:#x}-{hi:#x} {name(lo)}')
    seen = []
    for ins in md.disasm(d[lo:hi], lo):
        m = re.match(r'#(0x[0-9a-f]+)$', ins.op_str)
        if ins.mnemonic in ('bl', 'b') and m:
            t = int(m.group(1), 16)
            if not lo <= t < hi and t not in seen:
                seen.append(t)
                print(f'   {ins.address:#x} {ins.mnemonic} {t:#x} {name(t)}')
