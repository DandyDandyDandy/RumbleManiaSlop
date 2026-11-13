"""ptrref.py ADDR... - find 8-byte pointers and adrp+add refs to ADDR in main.bin"""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import sys,struct,re,numpy as np,os
d=open(W + r'\work\re\main.bin','rb').read()
U=W + r'\work\unity'
idx=np.load(U+r'\adrpadd_idx.npy'); tgt=np.load(U+r'\adrpadd_tgt.npy')
for a in sys.argv[1:]:
    a=int(a,16)
    print(hex(a),'ptrs',[hex(m.start()) for m in re.finditer(re.escape(struct.pack('<Q',a)),d)][:20],'adrp+add',[hex(int(i)*4) for i in idx[tgt==a]][:20])
