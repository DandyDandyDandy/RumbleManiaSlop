from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import struct,numpy as np
d=open(W + r'\work\re\main.bin','rb').read()
TS=0x483dae8
w=np.frombuffer(d[:TS&~3],dtype='<u4')
pc=np.arange(len(w),dtype=np.int64)*4
isadrp=(w&0x9f000000)==0x90000000
immlo=(w>>29)&3; immhi=(w>>5)&0x7ffff
imm=((immhi.astype(np.int64)<<2)|immlo); imm=np.where(imm&(1<<20),imm-(1<<21),imm)
page=(pc&~0xfff)+(imm<<12)
rd=w&31
# add immediate 64-bit: 0x91000000 mask 0xffc00000 (sh=0)
nxt=np.roll(w,-1)
isadd=(nxt&0xffc00000)==0x91000000
ok=isadrp&isadd&(((nxt>>5)&31)==rd)
tgt=page+((nxt>>10)&0xfff)
idx=np.nonzero(ok)[0]
np.save('adrpadd_idx.npy',idx); np.save('adrpadd_tgt.npy',tgt[idx]); np.save('adrpadd_rd.npy',(nxt[idx]&31))
print(len(idx))
