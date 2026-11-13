"""Link global-metadata.dat (v29) methods to native addresses inside a Switch NSO.

    python il2cpp_link.py <nso> <global-metadata.dat> <outdir>

Writes methods.tsv, generic_methods.tsv, images.tsv, layout.json into <outdir>.
Applies R_AARCH64_RELATIVE (DT_RELA) to the image; DT_RELR slots already hold link-time values (base 0).
"""
import struct, sys, os, json, bisect
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nso import Nso


def load_image(path):
    n = Nso(path)
    img = n.image
    stats = dict(rela_relative=0, rela_other=0, relr=0)
    rela, sz = n.dt.get(7), n.dt.get(8, 0)
    unresolved = set()
    for p in range(rela, rela + sz, 24):
        off, info, add = struct.unpack_from('<QQq', img, p)
        if info & 0xffffffff == 0x403:
            struct.pack_into('<Q', img, off, add)
            stats['rela_relative'] += 1
        else:
            unresolved.add(off)
            stats['rela_other'] += 1
    relr, rsz = n.dt.get(0x24), n.dt.get(0x23, 0)
    relr_slots = []
    if relr:
        where = 0
        for p in range(relr, relr + rsz, 8):
            e = struct.unpack_from('<Q', img, p)[0]
            if e & 1 == 0:
                relr_slots.append(e)
                where = e + 8
            else:
                b = e >> 1
                i = 0
                while b:
                    if b & 1:
                        relr_slots.append(where + i * 8)
                    b >>= 1
                    i += 1
                where += 63 * 8
        stats['relr'] = len(relr_slots)
    return n, img, stats, relr_slots, unresolved


class Meta:
    def __init__(self, path):
        d = self.d = open(path, 'rb').read()
        magic, ver = struct.unpack_from('<II', d, 0)
        assert magic == 0xFAB11BAF and ver == 29, (hex(magic), ver)
        h = struct.unpack_from('<62I', d, 8)
        sec = lambda i: (h[2 * i], h[2 * i + 1])
        self.str_off = sec(2)[0]
        mo, ms = sec(5)
        to, ts = sec(19)
        io, isz = sec(20)
        gco, gcs = sec(14)
        gpo, gps = sec(12)
        self.nmethods = ms // 32
        self.ntypes = ts // 88
        self.methods = [struct.unpack_from('<IiiiiIHHHH', d, mo + 32 * i) for i in range(self.nmethods)]
        self.types = [struct.unpack_from('<16i8HII', d, to + 88 * i) for i in range(self.ntypes)]
        self.images = [struct.unpack_from('<IiiiiiiIii', d, io + 40 * i) for i in range(isz // 40)]
        self.gcont = [struct.unpack_from('<iiii', d, gco + 16 * i) for i in range(gcs // 16)]
        self._sc = {}
        # declaring type from nestedTypes: use declaringTypeIndex (type index into binary types table) -> not usable
        # without binary; derive via nested ranges instead.
        nto, nts = sec(15)
        nested = struct.unpack_from('<%di' % (nts // 4), d, nto)
        self.decl = [-1] * self.ntypes
        for ti, t in enumerate(self.types):
            for k in range(t[12], t[12] + t[20]):
                self.decl[nested[k]] = ti

    def s(self, idx):
        r = self._sc.get(idx)
        if r is None:
            a = self.str_off + idx
            r = self.d[a:self.d.index(b'\0', a)].decode('utf-8')
            self._sc[idx] = r
        return r

    def type_name(self, ti):
        t = self.types[ti]
        nm = self.s(t[0])
        if self.decl[ti] >= 0:
            return self.type_name(self.decl[ti]) + '+' + nm
        ns = self.s(t[1])
        return ns + '.' + nm if ns else nm


def main():
    nso_path, meta_path, outdir = sys.argv[1:4]
    n, img, stats, relr_slots, unresolved = load_image(nso_path)
    m = Meta(meta_path)
    L = len(img)
    text_lo, text_sz = n.text
    text_hi = text_lo + text_sz
    q = lambda a: struct.unpack_from('<Q', img, a)[0]
    u = lambda a: struct.unpack_from('<I', img, a)[0]
    layout = dict(relocs=stats, text=[text_lo, text_hi], rodata=list(n.rodata), data=list(n.data),
                  counts=dict(images=len(m.images), types=m.ntypes, methods=m.nmethods))

    # per-image method counts & max token rid
    imginfo = []
    for ii, im in enumerate(m.images):
        name = m.s(im[0])
        cnt = 0
        maxrid = 0
        for ti in range(im[2], im[2] + im[3]):
            t = m.types[ti]
            cnt += t[16]
            for mi in range(t[9], t[9] + t[16]):
                maxrid = max(maxrid, m.methods[mi][5] & 0xffffff)
        imginfo.append(dict(index=ii, name=name, type_start=im[2], type_count=im[3], method_count=cnt, max_rid=maxrid))

    # find module name strings in image, then pointers to them (all relocated pointers are RELR/RELA slots)
    slots = sorted(set(relr_slots))
    ptr_to = {}
    for sl in slots:
        ptr_to.setdefault(q(sl), []).append(sl)
    for p in range(n.dt[7], n.dt[7] + n.dt.get(8, 0), 24):
        off, info, add = struct.unpack_from('<QQq', img, p)
        if info & 0xffffffff == 0x403:
            ptr_to.setdefault(add, []).append(off)
    mods = {}
    for inf in imginfo:
        needle = b'\0' + inf['name'].encode() + b'\0'
        cands = []
        pos = n.rodata[0]
        while True:
            pos = img.find(needle, pos)
            if pos < 0:
                break
            sa = pos + 1
            for rec in ptr_to.get(sa, []):
                c = u(rec + 8)
                mp = q(rec + 0x10)
                if c == inf['method_count'] or c == inf['max_rid']:
                    if c == 0 or (mp and mp < L):
                        cands.append(rec)
            pos += 1
        cands = sorted(set(cands))
        assert len(cands) == 1, (inf['name'], cands, inf['method_count'], inf['max_rid'])
        inf['module'] = cands[0]
        inf['method_pointer_count'] = u(cands[0] + 8)
        inf['method_pointers'] = q(cands[0] + 0x10)
        mods[cands[0]] = inf

    # module array: a run of pointers covering exactly those records
    modset = set(mods)
    arr = None
    for rec in modset:
        for sl in ptr_to.get(rec, []):
            # walk back to the start of the run
            a = sl
            while q(a - 8) in modset:
                a -= 8
            k = 0
            while q(a + 8 * k) in modset:
                k += 1
            if k == len(modset) and {q(a + 8 * j) for j in range(k)} == modset:
                arr = a
        if arr is not None:
            break
    assert arr is not None, 'module array not found'
    layout['code_gen_modules_array'] = arr
    cr = [sl for sl in ptr_to.get(arr, []) if u(sl - 8) == len(modset)]
    assert len(cr) == 1, cr
    cgm_field = cr[0] - 8
    layout['code_gen_modules_count_field'] = cgm_field

    # CodeRegistration layouts (offset of codeGenModulesCount): 27.1-29 -> 0x60 ; 29.1/31 -> 0x70
    creg = None
    for off, names in ((0x68, ['reversePInvokeWrapperCount', 'reversePInvokeWrappers', 'genericMethodPointersCount', 'genericMethodPointers',
                               'genericAdjustorThunks', 'invokerPointersCount', 'invokerPointers', 'unresolvedVirtualCallCount',
                               'unresolvedVirtualCallPointers', 'interopDataCount', 'interopData', 'windowsRuntimeFactoryCount',
                               'windowsRuntimeFactoryTable', 'codeGenModulesCount', 'codeGenModules']),
                       (0x78, ['reversePInvokeWrapperCount', 'reversePInvokeWrappers', 'genericMethodPointersCount', 'genericMethodPointers',
                               'genericAdjustorThunks', 'invokerPointersCount', 'invokerPointers', 'unresolvedIndirectCallCount',
                               'unresolvedVirtualCallPointers', 'unresolvedInstanceCallPointers', 'unresolvedStaticCallPointers',
                               'interopDataCount', 'interopData', 'windowsRuntimeFactoryCount', 'windowsRuntimeFactoryTable',
                               'codeGenModulesCount', 'codeGenModules'])):
        base = cgm_field - off
        vals = {nm: q(base + 8 * i) for i, nm in enumerate(names)}
        ok = True
        for nm, v in vals.items():
            if nm.endswith('Count'):
                ok &= v < 0x1000000
            else:
                ok &= (v == 0 or v < L + n.bss)
        gp, ip = vals['genericMethodPointers'], vals['invokerPointers']
        ok &= bool(gp and ip and text_lo <= q(gp + 0) < text_hi or (gp and q(gp) == 0)) and bool(ip and text_lo <= q(ip) < text_hi)
        layout.setdefault('code_registration_candidates', []).append(dict(offset=off, base=base, ok=bool(ok), fields=vals))
        if ok and creg is None:
            creg = (base, vals)
    assert creg, layout['code_registration_candidates']
    layout['code_registration'] = dict(address=creg[0], fields=creg[1])
    cv = creg[1]

    # MetadataRegistration: fieldOffsetsCount == typeDefinitionsSizesCount == ntypes
    key = struct.pack('<Q', m.ntypes)
    mr = []
    pos = n.rodata[0]
    while True:
        pos = img.find(key, pos)
        if pos < 0:
            break
        if pos % 8 == 0 and q(pos + 16) == m.ntypes and pos >= 80:
            b = pos - 80
            if q(b) < 0x1000000 and 0 < q(b + 8) < L and q(b + 48) < 0x1000000 and 0 < q(b + 56) < L:
                mr.append(b)
        pos += 8 - pos % 8 if pos % 8 else 8
    assert len(mr) == 1, [hex(x) for x in mr]
    mrb = mr[0]
    mrn = ['genericClassesCount', 'genericClasses', 'genericInstsCount', 'genericInsts', 'genericMethodTableCount', 'genericMethodTable',
           'typesCount', 'types', 'methodSpecsCount', 'methodSpecs', 'fieldOffsetsCount', 'fieldOffsets', 'typeDefinitionsSizesCount',
           'typeDefinitionsSizes', 'metadataUsagesCount', 'metadataUsages']
    mv = {nm: q(mrb + 8 * i) for i, nm in enumerate(mrn)}
    layout['metadata_registration'] = dict(address=mrb, fields=mv)

    # ---- methods.tsv
    addr_owner = []
    rows = []
    states = dict(code=0, nobody=0, unknown=0)
    for inf in imginfo:
        mp, cnt = inf['method_pointers'], inf['method_pointer_count']
        lo, hi, ncode = None, None, 0
        addrs = set()
        for ti in range(inf['type_start'], inf['type_start'] + inf['type_count']):
            t = m.types[ti]
            tn = m.type_name(ti)
            for mi in range(t[9], t[9] + t[16]):
                md = m.methods[mi]
                rid = md[5] & 0xffffff
                assert md[5] >> 24 == 6 and 1 <= rid <= cnt, (inf['name'], tn, hex(md[5]), cnt)
                slot = mp + 8 * (rid - 1)
                if slot in unresolved:
                    a = None
                    states['unknown'] += 1
                else:
                    a = q(slot)
                    if a == 0:
                        states['nobody'] += 1
                    else:
                        assert text_lo <= a < text_hi and a % 4 == 0, (inf['name'], tn, hex(a))
                        states['code'] += 1
                        ncode += 1
                        addrs.add(a)
                rows.append((inf['name'], tn, m.s(md[0]), a, mi, md[5]))
        inf['code_methods'] = ncode
        inf['distinct_addresses'] = len(addrs)
        inf['addr_min'] = min(addrs) if addrs else None
        inf['addr_max'] = max(addrs) if addrs else None
        inf['_addrs'] = addrs
    layout['method_states'] = states
    os.makedirs(outdir, exist_ok=True)
    with open(os.path.join(outdir, 'methods.tsv'), 'w', encoding='utf-8', newline='\n') as o:
        o.write('image\ttype\tmethod\taddress\tmethod_index\ttoken\n')
        for im, tn, mn, a, mi, tok in rows:
            o.write(f"{im}\t{tn}\t{mn}\t{'' if not a else hex(a)}\t{mi}\t{tok:#x}\n")

    # ---- generic instances
    types_tab, types_cnt = mv['types'], mv['typesCount']
    PRIM = {1: 'void', 2: 'bool', 3: 'char', 4: 'sbyte', 5: 'byte', 6: 'short', 7: 'ushort', 8: 'int', 9: 'uint', 10: 'long', 11: 'ulong',
            12: 'float', 13: 'double', 14: 'string', 0x16: 'TypedReference', 0x18: 'IntPtr', 0x19: 'UIntPtr', 0x1c: 'object'}
    gpo, gps = struct.unpack_from('<II', m.d, 8 + 8 * 12)

    def tname(tp, depth=0):
        if depth > 16 or not tp or tp + 16 > L:
            return '?'
        data = q(tp)
        bits = u(tp + 8)
        k = (bits >> 16) & 0xff
        if k in PRIM:
            return PRIM[k]
        if k in (0x11, 0x12):
            return m.type_name(data) if data < m.ntypes else '?'
        if k == 0x1d:
            return tname(data, depth + 1) + '[]'
        if k == 0x0f:
            return tname(data, depth + 1) + '*'
        if k == 0x14:
            return tname(q(data), depth + 1) + '[' + ',' * (img[data + 8] - 1) + ']'
        if k in (0x13, 0x1e):
            if data * 16 < gps:
                return m.s(struct.unpack_from('<I', m.d, gpo + 16 * data + 4)[0])
            return 'T?'
        if k == 0x15:  # Il2CppGenericClass {type, context{class_inst, method_inst}, cached}
            base = tname(q(data), depth + 1).split('`')[0]
            return base + '<' + inst(q(data + 8), depth + 1) + '>'
        return f'?{k:#x}'

    def inst(ip, depth=0):
        if not ip:
            return ''
        argc = u(ip)
        argv = q(ip + 8)
        if argc > 64:
            return '?'
        return ', '.join(tname(q(argv + 8 * j), depth) for j in range(argc))

    gmt, gmtc = mv['genericMethodTable'], mv['genericMethodTableCount']
    ms_, msc = mv['methodSpecs'], mv['methodSpecsCount']
    gi, gic = mv['genericInsts'], mv['genericInstsCount']
    gmp, gmpc = cv['genericMethodPointers'], cv['genericMethodPointersCount']
    gat = cv['genericAdjustorThunks']
    # method index -> declaring type
    mdecl = [md[1] for md in m.methods]
    gstates = dict(code=0, nobody=0, bad=0)
    gaddrs = set()
    adj_addrs = set()
    max_adj = -1
    with open(os.path.join(outdir, 'generic_methods.tsv'), 'w', encoding='utf-8', newline='\n') as o:
        o.write('row\tname\taddress\tadjustor_thunk\tmethod_index\tpointer_index\tinvoker_index\n')
        for r in range(gmtc):
            spec, pidx, inv, adj = struct.unpack_from('<iiii', img, gmt + 16 * r)
            if not (0 <= spec < msc and 0 <= pidx < gmpc):
                gstates['bad'] += 1
                continue
            mdi, ci, mi2 = struct.unpack_from('<iii', img, ms_ + 12 * spec)
            if not 0 <= mdi < m.nmethods:
                gstates['bad'] += 1
                continue
            md = m.methods[mdi]
            tn = m.type_name(mdecl[mdi]).split('`')[0] if 0 <= mdecl[mdi] < m.ntypes else '?'
            # keep nested generic arity markers trimmed
            tn = '+'.join(x.split('`')[0] for x in tn.split('+'))
            name = tn
            if ci >= 0 and ci < gic:
                name += '<' + inst(q(gi + 8 * ci)) + '>'
            name += '$$' + m.s(md[0])
            if mi2 >= 0 and mi2 < gic:
                name += '<' + inst(q(gi + 8 * mi2)) + '>'
            a = q(gmp + 8 * pidx)
            at = q(gat + 8 * adj) if gat and adj >= 0 else 0
            max_adj = max(max_adj, adj)
            if a:
                gstates['code'] += 1
                gaddrs.add(a)
            else:
                gstates['nobody'] += 1
            if at:
                adj_addrs.add(at)
            o.write(f"{r}\t{name}\t{hex(a) if a else ''}\t{hex(at) if at else ''}\t{mdi}\t{pidx}\t{inv}\n")
    layout['generic_method_states'] = gstates

    # ---- pointer tables & ranges
    def table(ptr, cnt):
        v = [q(ptr + 8 * i) for i in range(cnt)] if ptr else []
        nz = [x for x in v if x]
        return dict(table=ptr, count=cnt, nonzero=len(nz), distinct=len(set(nz)), min=min(nz) if nz else None, max=max(nz) if nz else None), set(nz)
    tabs = {}
    tabs['genericMethodPointers'], s_gmp = table(gmp, gmpc)
    tabs['genericAdjustorThunks'], s_gat = table(gat, max_adj + 1) if gat else ({}, set())
    tabs['invokerPointers'], s_inv = table(cv['invokerPointers'], cv['invokerPointersCount'])
    tabs['reversePInvokeWrappers'], s_rpw = table(cv['reversePInvokeWrappers'], cv['reversePInvokeWrapperCount'])
    uvc = cv.get('unresolvedVirtualCallCount', cv.get('unresolvedIndirectCallCount'))
    tabs['unresolvedVirtualCallPointers'], s_uv = table(cv['unresolvedVirtualCallPointers'], uvc)
    for k in ('unresolvedInstanceCallPointers', 'unresolvedStaticCallPointers'):
        if k in cv:
            tabs[k], s_ = table(cv[k], uvc)
            s_uv |= s_
    # per-module adjustor thunks
    s_madj = set()
    for inf in imginfo:
        rec = inf['module']
        ac, ap = u(rec + 0x18), q(rec + 0x20)
        inf['adjustor_thunk_count'] = ac
        for j in range(ac):
            s_madj.add(q(ap + 16 * j + 8))
        inf['module_initializer'] = q(rec + 0x68)
    tabs['moduleAdjustorThunks'] = dict(count=len(s_madj), min=min(s_madj) if s_madj else None, max=max(s_madj) if s_madj else None)
    layout['tables'] = tabs

    allm = set()
    for inf in imginfo:
        allm |= inf['_addrs']
    every = allm | s_gmp | s_gat | s_inv | s_rpw | s_uv | s_madj
    layout['generated_code'] = dict(
        method_def_range=[min(allm), max(allm)], generic_range=[min(s_gmp), max(s_gmp)] if s_gmp else None,
        invoker_range=[min(s_inv), max(s_inv)] if s_inv else None, all_range=[min(every), max(every)],
        distinct_method_def_addrs=len(allm), distinct_generic_addrs=len(s_gmp), distinct_total=len(every))

    # histogram of all generated-code entry addresses per 1 MiB of .text
    hist = {}
    for a in every:
        hist[a >> 20] = hist.get(a >> 20, 0) + 1
    layout['entry_histogram_1MiB'] = {hex(k << 20): hist[k] for k in sorted(hist)}

    with open(os.path.join(outdir, 'images.tsv'), 'w', encoding='utf-8', newline='\n') as o:
        o.write('index\timage\ttypes\tmethods\tcode_methods\tdistinct_addrs\taddr_min\taddr_max\tspan_bytes\tmodule_record\tmethod_pointers\tadjustor_thunks\n')
        for inf in imginfo:
            lo, hi = inf['addr_min'], inf['addr_max']
            o.write(f"{inf['index']}\t{inf['name']}\t{inf['type_count']}\t{inf['method_count']}\t{inf['code_methods']}\t{inf['distinct_addresses']}\t"
                    f"{hex(lo) if lo else ''}\t{hex(hi) if hi else ''}\t{hi - lo if lo else 0}\t{inf['module']:#x}\t{inf['method_pointers']:#x}\t{inf['adjustor_thunk_count']}\n")
    with open(os.path.join(outdir, 'entries.txt'), 'w', newline='\n') as o:
        for a in sorted(every):
            o.write(f'{a:#x}\n')

    def hx(o):
        if isinstance(o, dict):
            return {k: hx(v) for k, v in o.items()}
        if isinstance(o, list):
            return [hx(v) for v in o]
        if isinstance(o, int) and not isinstance(o, bool) and o > 4096:
            return hex(o)
        return o
    json.dump(hx(layout), open(os.path.join(outdir, 'layout.json'), 'w'), indent=1)
    print(json.dumps(hx({k: v for k, v in layout.items() if k != 'entry_histogram_1MiB'}), indent=1))


if __name__ == '__main__':
    main()
