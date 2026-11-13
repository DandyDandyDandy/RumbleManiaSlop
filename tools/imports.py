"""Group main's imported symbols by namespace and resolving module. python imports.py <re dir>"""
import sys, re, collections
d = sys.argv[1]
def load(m):
    r = []
    for l in open(f'{d}/{m}.syms.tsv', encoding='utf-8'):
        k, t, b, v, s, n = l.rstrip('\n').split('\t')
        r.append((k, n))
    return r
main = load('main')
exp = {m: {n for k, n in load(m) if k == 'exp'} for m in ('sdk', 'subsdk0')}
def comps(n):
    m = re.match(r'_ZNK?', n)
    if not n.startswith('_Z'): return None
    i = len(m.group(0)) if m else 2
    if n.startswith('_ZT') or n.startswith('_ZG'):
        mm = re.match(r'_Z(TV|TI|TS|GV|Tv\w+?_|Th\w+?_)N?', n); i = len(mm.group(0)) if mm else 3
    out = []
    while True:
        mm = re.match(r'(\d+)', n[i:])
        if not mm: break
        L = int(mm.group(1)); i += len(mm.group(1)); out.append(n[i:i+L]); i += L
    return out
imps = [n for k, n in main if k == 'imp']
where = collections.Counter(); groups = collections.defaultdict(list); unres = []
for n in imps:
    w = 'sdk' if n in exp['sdk'] else 'subsdk0' if n in exp['subsdk0'] else 'UNRESOLVED'
    where[w] += 1
    if w == 'UNRESOLVED': unres.append(n)
    c = comps(n)
    if c and c[0] == 'nn' and len(c) > 1: g = 'nn::' + c[1]
    elif c and c[0] in ('std', 'nnmusl'): g = c[0] + '::'
    elif c: g = 'c++ other: ' + (c[0] if c else '?')
    elif n.startswith('_Z'): g = 'c++ operators/other'
    elif n.startswith('nvn'): g = 'nvn*'
    elif n.startswith('gl') or n.startswith('egl'): g = 'gl/egl'
    elif n.startswith('__'): g = 'libc internal (__*)'
    else: g = 'C (libc/other)'
    groups[g].append((n, w))
print('resolved by:', dict(where))
print('unresolved:', unres)
for g, l in sorted(groups.items(), key=lambda x: -len(x[1])):
    print(f'{len(l):4} {g}  [{",".join(sorted({w for _, w in l}))}]')
with open(f'{d}/main_imports_grouped.txt', 'w') as o:
    for g, l in sorted(groups.items()):
        o.write(f'## {g} ({len(l)})\n')
        for n, w in sorted(l): o.write(f'  {w}\t{n}\n')
print('exports of main:', [n for k, n in main if k == 'exp'][:100])
