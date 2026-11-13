"""Extract icall-style name strings ("Ns.Type::Method") from binaries. usage: icall_strings.py out.txt file"""
import re, sys
out, path = sys.argv[1], sys.argv[2]
data = open(path, 'rb').read()
rx = re.compile(rb'(?<![\w.:`<>/+])([A-Za-z_][\w.`/+<>]*::[A-Za-z_.][\w.`<>]*(?:\([^\x00)]*\))?)\x00')
res = {}
for m in rx.finditer(data):
    res.setdefault(m.group(1).decode(), m.start(1))
with open(out, 'w') as f:
    for k in sorted(res): f.write(f"{k}\t{res[k]:#x}\n")
print(path, len(res))
