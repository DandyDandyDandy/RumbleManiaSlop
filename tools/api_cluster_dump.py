"""Dump every FDE function in an address range of main.bin (used for the il2cpp-api.cpp wrapper cluster).
   python api_cluster_dump.py LO HI [maxinsn]"""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import sys, struct, bisect, capstone, numpy as np, pickle, os
ROOT = REPO
d = open(W + r'\work\re\main.bin', 'rb').read()
TS = 0x483dae8
def fde_starts():
    c = W + r'\work\unity\api\fde_starts.npy'
    if os.path.exists(c):
        return np.load(c)
    sys.path.insert(0, TOOLS)
    from closure_common import Image
    im = Image()
    s = im.fs[~im.isgap]
    np.save(c, s)
    np.save(W + r'\work\unity\api\fde_ends.npy', im.fe[~im.isgap])
    return s
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
def dis(a, e, mx=30):
    out = []
    for i in md.disasm(d[a:e], a):
        out.append('%s %s' % (i.mnemonic, i.op_str))
        if len(out) >= mx: out.append('...'); break
    return out
if __name__ == '__main__':
    lo, hi = int(sys.argv[1], 16), int(sys.argv[2], 16)
    mx = int(sys.argv[3]) if len(sys.argv) > 3 else 12
    s = fde_starts(); e = np.load(W + r'\work\unity\api\fde_ends.npy')
    i0 = bisect.bisect_left(s, lo)
    while i0 < len(s) and s[i0] < hi:
        print('%x [%d]: %s' % (s[i0], e[i0] - s[i0], '; '.join(dis(int(s[i0]), int(e[i0]), mx))))
        i0 += 1
