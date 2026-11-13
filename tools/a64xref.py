from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import numpy as np,sys
d=open(W + r'\work\re\main.bin','rb').read()
TS=0x483dae8
w=np.frombuffer(d[:TS&~3],dtype='<u4')
pc=np.arange(len(w),dtype=np.int64)*4
isbl=(w&0x7c000000)==0x14000000  # b or bl
imm=(w&0x3ffffff).astype(np.int64); imm=np.where(imm&(1<<25),imm-(1<<26),imm)
t=pc+imm*4
for a in sys.argv[1:]:
    a=int(a,16); h=np.nonzero(isbl&(t==a))[0]
    print(hex(a),len(h),[hex(int(x)*4) for x in h[:20]])
