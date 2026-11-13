"""Windows UnityPlayer.dll (2022.3.30f1): find where each il2cpp_* name string is referenced (lea rip-rel),
and which global receives the looked-up pointer. Writes work/unity/api/up_bind.tsv (name, string_rva, ref_rva, global_rva)."""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import pefile, re, struct, sys, numpy as np, capstone
P = UNITY_EDITOR + r'\PlaybackEngines\windowsstandalonesupport\Variations\win64_player_nondevelopment_il2cpp\UnityPlayer.dll'
OUT = W + r'\work\unity\api'
pe = pefile.PE(P, fast_load=True)
d = pe.__data__
img = pe.get_memory_mapped_image()
secs = [(s.Name.rstrip(b'\0').decode(), s.VirtualAddress, s.Misc_VirtualSize) for s in pe.sections]
print(secs)
names = {}
for m in re.finditer(rb'(?<![\w])(il2cpp_[a-z0-9_]+)\x00', img):
    names[m.start()] = m.group(1).decode()
tx = [s for s in secs if s[0] == '.text'][0]
t0, tn = tx[1], tx[2]
code = np.frombuffer(img[t0:t0+tn], dtype=np.uint8)
# lea r64,[rip+disp32]: 48/4C 8D modrm(00 reg 101) disp32
idx = np.nonzero((code[1:-6] == 0x8d) & ((code[:-7] & 0xfb) == 0x48) & ((code[2:-5] & 0xc7) == 0x05))[0]
disp = np.frombuffer(img[t0:t0+tn], dtype='<i4', offset=0, count=0)  # placeholder
refs = {}
for i in idx.tolist():
    dsp = struct.unpack_from('<i', img, t0 + i + 3)[0]
    tgt = t0 + i + 7 + dsp
    if tgt in names:
        refs.setdefault(tgt, []).append(t0 + i)
print('names', len(names), 'with lea refs', len(refs))
md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
rows = []
for srva, nm in sorted(names.items()):
    for r in refs.get(srva, []):
        g = None; txt = []
        for ins in md.disasm(img[r:r+60], r):
            txt.append('%s %s' % (ins.mnemonic, ins.op_str))
            m = re.match(r'qword ptr \[rip ([+-]) (0x[0-9a-f]+)\], rax', ins.op_str)
            if ins.mnemonic == 'mov' and m:
                g = ins.address + ins.size + (1 if m.group(1) == '+' else -1) * int(m.group(2), 16); break
            if len(txt) > 8: break
        rows.append((nm, srva, r, g, '; '.join(txt)))
rows.sort(key=lambda x: x[2])
with open(OUT + r'\up_bind.tsv', 'w') as f:
    f.write('name\tstring_rva\tref_rva\tglobal_rva\tcode\n')
    for nm, s, r, g, t in rows:
        f.write('%s\t%#x\t%#x\t%s\t%s\n' % (nm, s, r, '%#x' % g if g else '', t))
print('rows', len(rows), 'with global', sum(1 for x in rows if x[3]))
for x in rows[:6]: print(x)
print('unreferenced', [n for s, n in names.items() if s not in refs])
