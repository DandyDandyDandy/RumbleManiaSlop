"""dis.py ADDR [N] - disassemble N instructions of main.bin at ADDR; annotates adrp+add string targets"""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import sys,capstone,re
d=open(W + r'\work\re\main.bin','rb').read()
md=capstone.Cs(capstone.CS_ARCH_ARM64,capstone.CS_MODE_ARM)
a=int(sys.argv[1],16); n=int(sys.argv[2]) if len(sys.argv)>2 else 40
pages={}
for i in md.disasm(d[a:a+4*n],a):
    note=''
    if i.mnemonic=='adrp':
        r,p=i.op_str.split(', #'); pages[r]=int(p,16)
    m=re.match(r'add (x\d+), (x\d+), #(0x[0-9a-f]+|\d+)$',i.mnemonic+' '+i.op_str)
    if m and m.group(2) in pages:
        t=pages[m.group(2)]+int(m.group(3),0)
        s=d[t:t+60].split(b'\0')[0]
        note=' ; %x %r'%(t,s[:60])
    print('%x: %s %s%s'%(i.address,i.mnemonic,i.op_str,note))
