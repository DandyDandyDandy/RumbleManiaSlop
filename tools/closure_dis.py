"""closure_dis.py ADDR [N] [...]: disassemble N insns at ADDR (function-bounded) with PLT names and string refs"""
import sys, re, capstone
from closure_common import *
im = Image()
md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
def dis(a, n=30):
    i = im.func_of(a); e = min(int(im.fe[i]), a + 4 * n)
    pages = {}
    print(f'--- {a:#x} (func {int(im.fs[i]):#x}-{int(im.fe[i]):#x})')
    for x in md.disasm(im.img[a:e], a):
        note = ''
        s = f'{x.mnemonic} {x.op_str}'
        if x.mnemonic == 'adrp':
            r, p = x.op_str.split(', #'); pages[r] = int(p, 16)
        m = re.match(r'add (x\d+), (x\d+), #(0x[0-9a-f]+|\d+)$', s)
        if m and m.group(2) in pages:
            t = pages[m.group(2)] + int(m.group(3), 0)
            note = ' ; %x %r' % (t, im.img[t:t + 60].split(b'\0')[0][:60])
        m = re.match(r'bl? #(0x[0-9a-f]+)$', s)
        if m and int(m.group(1), 16) in im.plt:
            note = ' ; <%s>' % im.plt[int(m.group(1), 16)][0]
        print('  %x: %s%s' % (x.address, s, note))
if __name__ == '__main__':
    args = sys.argv[1:]
    n = 30
    if args and not args[-1].startswith('0x'):
        n = int(args.pop())
    for a in args:
        dis(int(a, 16), n)
