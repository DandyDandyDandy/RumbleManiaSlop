import sys
def hd(d, base=0, maxn=1<<30, out=sys.stdout):
    skip=False
    for i in range(0,min(len(d),maxn),16):
        c=d[i:i+16]
        if c==b'\0'*16 and i+16<len(d):
            if not skip: out.write('   *\n'); skip=True
            continue
        skip=False
        out.write(f'{base+i:06x}  {c.hex(" "):<48}  {"".join(chr(x) if 32<=x<127 else "." for x in c)}\n')
