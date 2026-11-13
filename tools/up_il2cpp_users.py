"""Windows UnityPlayer.dll (2022.3.30f1): for each bound il2cpp_* function pointer global, list the player functions
(named via the PDB public symbols) that reference it. Writes work/unity/api/up_users.tsv and up_pubsyms.tsv."""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import pefile, re, struct, sys, bisect, collections, numpy as np
D = UNITY_EDITOR + r'\PlaybackEngines\windowsstandalonesupport\Variations\win64_player_nondevelopment_il2cpp'
OUT = W + r'\work\unity\api'
def pdb_streams(path):
    b = open(path, 'rb').read()
    assert b.startswith(b'Microsoft C/C++ MSF 7.00')
    bs, fpm, nb, dbytes, _, bmap = struct.unpack_from('<6I', b, 32)
    nd = (dbytes + bs - 1) // bs
    dblocks = struct.unpack_from('<%dI' % nd, b, bmap * bs)
    dirb = b''.join(b[x*bs:(x+1)*bs] for x in dblocks)[:dbytes]
    ns = struct.unpack_from('<I', dirb, 0)[0]
    sizes = struct.unpack_from('<%dI' % ns, dirb, 4)
    p = 4 + 4 * ns
    def get(i):
        q = p
        for j in range(i):
            if sizes[j] != 0xffffffff: q += 4 * ((sizes[j] + bs - 1) // bs)
        n = (sizes[i] + bs - 1) // bs
        bl = struct.unpack_from('<%dI' % n, dirb, q)
        return b''.join(b[x*bs:(x+1)*bs] for x in bl)[:sizes[i]]
    return get, sizes
def pubsyms(pdb, pe):
    get, sizes = pdb_streams(pdb)
    dbi = get(3)
    gs, bn, ps, dllv, symrec = struct.unpack_from('<HHHHH', dbi, 12)
    sr = get(symrec)
    secs = [s.VirtualAddress for s in pe.sections]
    out = []; o = 0; kinds = collections.Counter()
    while o + 4 <= len(sr):
        ln, ty = struct.unpack_from('<HH', sr, o)
        kinds[ty] += 1
        if ty == 0x110e:
            fl, off, seg = struct.unpack_from('<IIH', sr, o + 4)
            nm = sr[o+14:sr.index(b'\0', o+14)].decode('latin1')
            if 0 < seg <= len(secs): out.append((secs[seg-1] + off, nm, fl))
        o += ln + 2
    print('symbol record kinds', dict(kinds))
    return sorted(out)
if __name__ == '__main__':
    pe = pefile.PE(D + r'\UnityPlayer.dll', fast_load=True)
    img = pe.get_memory_mapped_image()
    syms = pubsyms(D + r'\UnityPlayer_Win64_player_il2cpp_x64.pdb', pe)
    print('public syms', len(syms))
    with open(OUT + r'\up_pubsyms.tsv', 'w') as f:
        for r, n, fl in syms: f.write('%#x\t%d\t%s\n' % (r, fl, n))
    fsyms = [(r, n) for r, n, fl in syms if fl & 2]   # function flag
    fr = [r for r, n in fsyms]
    glob = {}
    order = []
    for l in open(OUT + r'\up_bind.tsv').read().split('\n')[1:]:
        p = l.split('\t')
        if len(p) > 3 and p[3]: glob[int(p[3], 16)] = p[0]; order.append((int(p[2], 16), p[0]))
    t0, tn = 0x1000, [s for s in pe.sections if s.Name.startswith(b'.text')][0].Misc_VirtualSize
    code = np.frombuffer(img[t0:t0+tn], dtype=np.uint8)
    # any modrm with mod=00 rm=101 followed by disp32 hitting a global: brute force over all byte positions
    d32 = np.lib.stride_tricks.as_strided(code, shape=(len(code)-3, 4), strides=(1, 1)).copy().view('<i4').ravel()
    pos = np.arange(len(d32), dtype=np.int64) + t0
    users = collections.defaultdict(list)
    garr = np.array(sorted(glob), dtype=np.int64)
    for extra in (0, 1, 4):   # bytes of immediate after disp32 (0: call/jmp/mov; 1: cmp imm8; 4: imm32)
        tgt = pos + 4 + extra + d32
        hit = np.nonzero(np.isin(tgt, garr))[0]
        for i in hit.tolist():
            modrm = int(code[i-1]); op = int(code[i-2])
            if (modrm & 0xc7) != 0x05: continue
            a = t0 + i - 2
            kind = {0xff: {2: 'call', 4: 'jmp', 6: 'push'}.get((modrm >> 3) & 7, 'ff?'), 0x8b: 'load', 0x89: 'store', 0x83: 'cmp', 0x39: 'cmp', 0x3b: 'cmp'}.get(op, 'op%02x' % op)
            if extra and kind not in ('cmp',): continue
            if not extra and kind == 'cmp' and op == 0x83: continue
            j = bisect.bisect_right(fr, a) - 1
            users[glob[int(tgt[i])]].append((a, kind, fsyms[j][1], a - fsyms[j][0]))
    with open(OUT + r'\up_users.tsv', 'w') as f:
        f.write('name\tbind_order\tnrefs_excluding_bind\tkinds\tuser_functions\n')
        for k, (r, nm) in enumerate(sorted(order)):
            u = [x for x in users.get(nm, []) if x[1] != 'store']
            fn = collections.Counter(x[2] for x in u)
            f.write('%s\t%d\t%d\t%s\t%s\n' % (nm, k, len(u), dict(collections.Counter(x[1] for x in u)), ' | '.join('%s x%d' % (a, b) for a, b in fn.most_common(12))))
    print('names with no users', sum(1 for nm in glob.values() if not [x for x in users.get(nm, []) if x[1] != 'store']))
    j = bisect.bisect_right(fr, sorted(order)[0][0]) - 1
    print('binder function:', fsyms[j])
