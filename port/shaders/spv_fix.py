"""Post-process SPIR-V from the Ryujinx Maxwell translator into what Unity 2022.3's Vulkan backend expects.

What changes (see fix()):
  * guest constant buffers (Maxwell c[3+n] = Unity/NVN uniform block binding n) -> DescriptorSet 1, Binding from the plan
  * c[1] (immediate constants the NVN driver uploads from the program's data section) -> Private variable with a
    constant initializer made from the c1 bytes; no descriptor needed
  * c[2] (NVN texture/sampler handle table; only read as dead register traffic) -> Private zero variable
  * Ryujinx's support buffer (set 0 binding 0) -> Private constant (render scale 1, point size 1, rest 0)
  * every combined image sampler (one per NVN texture-handle/sampler-handle pair) -> separate image variable (set 0)
    + sampler variable (set 0), combined at the use site with OpSampledImage: Unity's own convention for
    HLSL separate textures/samplers on Vulkan
  * storage buffers (NVN storage block n, found through its address slot in c[0]) -> set 0, Binding from the plan
  * vertex stage: gl_Position.y negated before every return of main (Unity's Vulkan shaders end with this)
  * capabilities the module does not use are dropped (Ryujinx declares a fixed superset)

    python spv_fix.py in.spv in.res.json plan.json out.spv
"""
import json
import struct
import sys

OP = dict(Name=5, MemberName=6, ExtInst=12, EntryPoint=15, Capability=17, TypeInt=21, TypeFloat=22, TypeVector=23,
          TypeImage=25, TypeSampler=26, TypeSampledImage=27, TypeArray=28, TypeStruct=30, TypePointer=32,
          Constant=43, ConstantComposite=44, ConstantNull=46, Function=54, FunctionEnd=56, Variable=59, Load=61,
          Store=62, AccessChain=65, InBoundsAccessChain=66, Decorate=71, MemberDecorate=72, SampledImage=86,
          FNegate=127, Return=253, ReturnValue=254)
DEC = dict(Block=2, BuiltIn=11, Location=30, Binding=33, DescriptorSet=34)
SC = dict(UniformConstant=0, Input=1, Uniform=2, Output=3, Private=6, Function=7)
CAP = dict(Float64=10, ImageGatherExtended=25, SampledBuffer=46, ImageBuffer=47, ImageQuery=50, DrawParameters=4427,
           GroupNonUniformVote=62, GroupNonUniformBallot=64, GroupNonUniformShuffle=65)

TEX_BASE, SAMP_BASE = 0x168, 0x568      # byte offsets of NVN's separate texture / sampler handle tables in c[2]


def handle_slots(handle):
    """Ryujinx packed handle -> (texture slot, sampler slot or None) for NVN separate handles.
    A type-1 handle is the OR of two c[2] words; the program may load them in either order."""
    typ = (handle >> 28) & 0xf
    offs = [(handle & 0x3fff) * 4] + ([((handle >> 14) & 0x3fff) * 4] if typ == 1 else [])
    if typ not in (0, 1):
        raise ValueError(f'texture handle {handle:#x}: unsupported handle type {typ}')
    tex = samp = None
    for o in offs:
        if TEX_BASE <= o < SAMP_BASE and (o - TEX_BASE) % 8 == 0 and tex is None:
            tex = (o - TEX_BASE) // 8
        elif SAMP_BASE <= o < SAMP_BASE + 0x400 and (o - SAMP_BASE) % 8 == 0 and samp is None:
            samp = (o - SAMP_BASE) // 8
        else:
            raise ValueError(f'texture handle {handle:#x}: c[2] offset {o:#x} is not a separate texture/sampler slot')
    if tex is None:
        raise ValueError(f'texture handle {handle:#x}: no texture word')
    return tex, samp


class Module:
    def __init__(self, data):
        w = struct.unpack(f'<{len(data) // 4}I', data)
        self.header = list(w[:5])
        self.ins = []
        p = 5
        while p < len(w):
            n = w[p] >> 16
            self.ins.append([w[p] & 0xffff, list(w[p + 1:p + n])])
            p += n

    def new_id(self):
        self.header[3] += 1
        return self.header[3] - 1

    def bytes(self):
        out = list(self.header)
        for op, a in self.ins:
            out.append(((len(a) + 1) << 16) | op)
            out.extend(a)
        return struct.pack(f'<{len(out)}I', *out)

    def find(self, op):
        return [i for i in self.ins if i[0] == op]

    def decorations(self, target):
        return {i[1][1]: i[1][2:] for i in self.ins if i[0] == OP['Decorate'] and i[1][0] == target}

    def first_function_index(self):
        return next(k for k, i in enumerate(self.ins) if i[0] == OP['Function'])


class Fixer:
    def __init__(self, m):
        self.m = m
        self.new = []                 # declarations to insert before the first function
        self.types = {}
        for i in m.ins:
            if i[0] == OP['TypeFloat'] and i[1][1] == 32:
                self.types['float'] = i[1][0]
            elif i[0] == OP['TypeInt'] and i[1][1] == 32:
                self.types['int' if i[1][2] else 'uint'] = i[1][0]
            elif i[0] == OP['TypeSampler']:
                self.types['sampler'] = i[1][0]
        self.types['vec4'] = next((i[1][0] for i in m.ins if i[0] == OP['TypeVector']
                                   and i[1][1] == self.types['float'] and i[1][2] == 4), None)
        self.ptr_cache = {}
        self.const_cache = {}
        self.notes = []

    def decl(self, op, *args, result_at=None):
        """append a declaration; result id allocated at position result_at"""
        a = list(args)
        rid = None
        if result_at is not None:
            rid = self.m.new_id()
            a.insert(result_at, rid)
        self.new.append([op, a])
        return rid

    def pointer(self, sc, pointee):
        key = (sc, pointee)
        if key not in self.ptr_cache:
            k = self.m.first_function_index()
            old = next((i[1][0] for i in self.m.ins[:k] + self.new
                        if i[0] == OP['TypePointer'] and i[1][1] == sc and i[1][2] == pointee), None)
            self.ptr_cache[key] = old if old is not None else self.decl(OP['TypePointer'], sc, pointee, result_at=0)
        return self.ptr_cache[key]

    def const(self, typ, word):
        key = (typ, word)
        if key not in self.const_cache:
            self.const_cache[key] = self.decl(OP['Constant'], typ, word, result_at=1)
        return self.const_cache[key]

    def int_type(self):
        return self.types.get('int') or self.types['uint']

    def type_ins(self, tid):
        return next(i for i in self.m.ins + self.new if i[0] in (OP['TypeStruct'], OP['TypeArray'], OP['TypePointer'],
                    OP['TypeSampledImage'], OP['TypeImage'], OP['TypeVector'], OP['TypeFloat'], OP['TypeInt'])
                    and i[1][0] == tid)

    def var_by_binding(self, binding, storage):
        for v in self.m.find(OP['Variable']):
            if v[1][2] != storage:
                continue
            d = self.m.decorations(v[1][1])
            if d.get(DEC['Binding']) == [binding] and d.get(DEC['DescriptorSet']) == [0]:
                return v
        return None

    def set_binding(self, var_id, dset, binding):
        for i in self.m.ins:
            if i[0] == OP['Decorate'] and i[1][0] == var_id:
                if i[1][1] == DEC['DescriptorSet']:
                    i[1][2] = dset
                elif i[1][1] == DEC['Binding']:
                    i[1][2] = binding

    def drop_var_decorations(self, var_id):
        self.m.ins = [i for i in self.m.ins if not (i[0] == OP['Decorate'] and i[1][0] == var_id
                                                    and i[1][1] in (DEC['DescriptorSet'], DEC['Binding']))]

    def to_private(self, var, struct_type, initializer):
        """turn a uniform block variable into a Private variable of struct_type with a constant initializer"""
        vid = var[1][1]
        self.drop_var_decorations(vid)
        self.m.ins.remove(var)
        self.new.append([OP['Variable'], [self.pointer(SC['Private'], struct_type), vid, SC['Private'], initializer]])
        for i in self.m.ins:
            if i[0] in (OP['AccessChain'], OP['InBoundsAccessChain']) and i[1][2] == vid:
                pointee = self.type_ins(i[1][0])[1][2]
                i[1][0] = self.pointer(SC['Private'], pointee)
            elif i[0] == OP['Load'] and i[1][2] == vid:
                raise ValueError('whole-block load of a constant buffer')

    def vec4_array_struct(self, n):
        length = self.const(self.int_type(), n)
        arr = self.decl(OP['TypeArray'], self.types['vec4'], length, result_at=0)
        return arr, self.decl(OP['TypeStruct'], arr, result_at=0)

    def bake_c1(self, var, c1):
        words = list(struct.unpack(f'<{len(c1) // 4}I', c1[:len(c1) & ~3]))
        while len(words) % 4 or not words:
            words.append(0)
        n = len(words) // 4
        arr, st = self.vec4_array_struct(n)
        vecs = []
        for k in range(n):
            comps = [self.const(self.types['float'], x) for x in words[4 * k:4 * k + 4]]
            vecs.append(self.decl(OP['ConstantComposite'], self.types['vec4'], *comps, result_at=1))
        a = self.decl(OP['ConstantComposite'], arr, *vecs, result_at=1)
        self.to_private(var, st, self.decl(OP['ConstantComposite'], st, a, result_at=1))

    def zero_block(self, var):
        st_old = self.type_ins(self.type_ins(var[1][0])[1][2])
        st = self.decl(OP['TypeStruct'], *st_old[1][1:], result_at=0)
        self.to_private(var, st, self.decl(OP['ConstantNull'], st, result_at=1))

    def bake_support(self, var):
        st = self.type_ins(self.type_ins(var[1][0])[1][2])
        members = st[1][1:]
        if len(members) != 9:
            raise ValueError(f'support buffer has {len(members)} members')
        one = self.const(self.types['float'], 0x3f800000)
        vals = []
        for k, t in enumerate(members):
            if k == 5:      # render scale array
                ti = self.type_ins(t)
                count = next(i[1][2] for i in self.m.ins if i[0] == OP['Constant'] and i[1][1] == ti[1][2])
                vals.append(self.decl(OP['ConstantComposite'], t, *([one] * count), result_at=1))
            elif k == 8:    # point size
                vals.append(one)
            else:
                vals.append(self.decl(OP['ConstantNull'], t, result_at=1))
        sid = st[1][0]
        self.m.ins = [i for i in self.m.ins if not (i[0] == OP['Decorate'] and i[1][0] == sid and i[1][1] == DEC['Block'])]
        self.to_private(var, sid, self.decl(OP['ConstantComposite'], sid, *vals, result_at=1))
        # which support members are read (2/3 = viewport inverse/size would need real data)
        used = set()
        for i in self.m.ins:
            if i[0] == OP['AccessChain'] and i[1][2] == var[1][1]:
                c = next((x for x in self.m.ins + self.new if x[0] == OP['Constant'] and x[1][1] == i[1][3]), None)
                used.add(c[1][2] if c else -1)
        for u in sorted(used - {8}):
            self.notes.append(f'support buffer member {u} is read (baked as {"1.0" if u == 5 else "0"})')

    def split_textures(self, textures, tex_bind, samp_bind, own_samp=None, inline=None):
        img_vars, samp_vars = {}, {}
        self.own_samp, self.inline = own_samp or {}, inline or {}
        for t in textures:
            var = self.var_by_binding(t['binding'], SC['UniformConstant'])
            if var is None:
                raise ValueError(f"texture binding {t['binding']} not found")
            tex, samp = handle_slots(t['handle'])
            if t.get('array', 1) != 1:
                raise ValueError('texture arrays of handles are not supported')
            si = self.type_ins(var[1][0])[1][2]
            si_ins = self.type_ins(si)
            if si_ins[0] != OP['TypeSampledImage']:
                raise ValueError('texture variable is not a combined image sampler')
            img_t = si_ins[1][1]
            if (tex, img_t) not in img_vars:
                if any(k[0] == tex for k in img_vars):
                    self.notes.append(f'texture slot {tex} is used with two image types (e.g. with and without depth compare)')
                v = self.decl(OP['Variable'], self.pointer(SC['UniformConstant'], img_t), SC['UniformConstant'], result_at=1)
                img_vars[(tex, img_t)] = v
                self.decorate.append([OP['Decorate'], [v, DEC['DescriptorSet'], 0]])
                self.decorate.append([OP['Decorate'], [v, DEC['Binding'], tex_bind[tex]]])
            vid = var[1][1]
            if samp is None:
                # texel fetch / size query through a bare texture handle: every load must only feed OpImage
                loads = {i[1][1] for i in self.m.ins if i[0] == OP['Load'] and i[1][2] == vid}
                sampled = any(i[0] not in (OP['Load'], 100) and any(x in loads for x in i[1]) for i in self.m.ins)
                if sampled:
                    # The translator traced only the texture word of the handle (the program builds the handle in
                    # one block and uses it in another). Take the sampler from Unity's metadata instead.
                    shadow = self.type_ins(img_t)[1][3] == 1
                    cands = [self.own_samp[tex]] if tex in self.own_samp else                         [k for k, extra in self.inline.items() if bool(extra & 0x100) == shadow]
                    if len(cands) != 1:
                        raise ValueError(f'texture slot {tex} is sampled through an untraced handle and has {len(cands)} candidate samplers')
                    samp = cands[0]
                    self.notes.append('sampler of an untraced texture handle taken from the Unity metadata')
            if samp is None:
                out = []
                for i in self.m.ins:
                    if i[0] == OP['Load'] and i[1][2] == vid:
                        out.append([OP['Load'], [img_t, i[1][1], img_vars[(tex, img_t)]]])
                    elif i[0] == 100 and i[1][2] in loads:                  # OpImage -> OpCopyObject
                        out.append([83, [i[1][0], i[1][1], i[1][2]]])
                    elif i is var or (i[0] in (OP['Decorate'], OP['Name']) and i[1][0] == vid):
                        continue
                    else:
                        out.append(i)
                self.m.ins = out
                continue
            if samp not in samp_vars:
                if 'sampler' not in self.types:
                    self.types['sampler'] = self.decl(OP['TypeSampler'], result_at=0)
                v = self.decl(OP['Variable'], self.pointer(SC['UniformConstant'], self.types['sampler']), SC['UniformConstant'], result_at=1)
                samp_vars[samp] = v
                self.decorate.append([OP['Decorate'], [v, DEC['DescriptorSet'], 0]])
                self.decorate.append([OP['Decorate'], [v, DEC['Binding'], samp_bind[samp]]])
            out = []
            for i in self.m.ins:
                if i[0] == OP['Load'] and i[1][2] == vid:
                    a, b = self.m.new_id(), self.m.new_id()
                    out.append([OP['Load'], [img_t, a, img_vars[(tex, img_t)]]])
                    out.append([OP['Load'], [self.types['sampler'], b, samp_vars[samp]]])
                    out.append([OP['SampledImage'], [si, i[1][1], a, b]])
                elif i is var or (i[0] in (OP['Decorate'], OP['Name']) and i[1][0] == vid):
                    continue
                else:
                    out.append(i)
            self.m.ins = out

    def flip_y(self):
        m = self.m
        ep = m.find(OP['EntryPoint'])[0]
        main = ep[1][1]
        pos = None      # (variable, member index or None)
        for i in m.ins:
            if i[0] == OP['MemberDecorate'] and i[1][2] == DEC['BuiltIn'] and i[1][3] == 0:
                st = i[1][0]
                for v in m.find(OP['Variable']):
                    if v[1][2] == SC['Output'] and self.type_ins(v[1][0])[1][2] == st:
                        pos = (v[1][1], i[1][1])
            elif i[0] == OP['Decorate'] and i[1][1] == DEC['BuiltIn'] and i[1][2] == 0:
                pos = (i[1][0], None)
        if pos is None:
            raise ValueError('no gl_Position output')
        fl = self.types['float']
        pf = self.pointer(SC['Output'], fl)
        it = self.int_type()
        idx = ([self.const(it, pos[1])] if pos[1] is not None else []) + [self.const(it, 1)]
        out = []
        inside = False
        for i in m.ins:
            if i[0] == OP['Function']:
                inside = i[1][1] == main
            if inside and i[0] == OP['Return']:
                p, v, n = m.new_id(), m.new_id(), m.new_id()
                out.append([OP['AccessChain'], [pf, p, pos[0]] + idx])
                out.append([OP['Load'], [fl, v, p]])
                out.append([OP['FNegate'], [fl, n, v]])
                out.append([OP['Store'], [p, n]])
            out.append(i)
        m.ins = out

    def prune_capabilities(self):
        ops = {i[0] for i in self.m.ins}
        need = set()
        if any(333 <= o <= 366 for o in ops):
            need |= {CAP['GroupNonUniformVote'], CAP['GroupNonUniformBallot'], CAP['GroupNonUniformShuffle']}
        if any(i[0] == OP['TypeFloat'] and i[1][1] == 64 for i in self.m.ins):
            need.add(CAP['Float64'])
        if any(i[0] == OP['TypeImage'] and i[1][2] == 5 for i in self.m.ins):      # Dim Buffer
            need |= {CAP['SampledBuffer'], CAP['ImageBuffer']}
        if ops & {96, 97}:                                                         # OpImageGather / OpImageDrefGather
            need.add(CAP['ImageGatherExtended'])
        if ops & {103, 104, 105, 106, 107}:                                        # OpImageQuery*
            need.add(CAP['ImageQuery'])
        if any(i[0] in (OP['Decorate'], OP['MemberDecorate']) and DEC['BuiltIn'] in i[1][1:3]
               and i[1][-1] in (4424, 4425, 4426) for i in self.m.ins):            # BaseVertex, BaseInstance, DrawIndex
            need.add(CAP['DrawParameters'])
        prunable = set(CAP.values())
        self.m.ins = [i for i in self.m.ins if not (i[0] == OP['Capability'] and i[1][0] in prunable and i[1][0] not in need)]


def fix(spv, stage, res, plan, c1=b''):
    """plan: {"ubo": {guest cbuf slot: binding in set 1}, "tex": {texture slot: binding in set 0},
              "samp": {sampler slot: binding in set 0}, "own_samp": {texture slot: its own sampler slot},
              "inline": {sampler slot: inline sampler state word}}  ->  (new spv, notes)"""
    m = Module(spv)
    f = Fixer(m)
    f.decorate = []
    sup = f.var_by_binding(0, SC['Uniform'])
    if sup is not None:
        f.bake_support(sup)
    for cb in res['cbufs']:
        var = f.var_by_binding(cb['binding'], SC['Uniform'])
        if var is None:
            raise ValueError(f"constant buffer binding {cb['binding']} not found")
        slot = cb['slot']
        if slot == 1:
            f.bake_c1(var, c1)
        elif slot == 2:
            f.zero_block(var)
            f.notes.append('c[2] (texture handle table) is read by the program; replaced by zeros')
        elif slot == 0:
            raise ValueError('program reads c[0] (driver constants)')
        else:
            f.pending = getattr(f, 'pending', []) + [(var[1][1], plan['ubo'][str(slot)])]
    for vid, binding in getattr(f, 'pending', []):
        f.set_binding(vid, 1, binding)
    if res.get('images'):
        raise ValueError('storage images are not handled yet')
    for sb in res.get('sbufs', []):
        # NVN keeps shader storage block n's address in driver constants c[0] at byte 0x110 + 16 n (word 68 + 4 n)
        if sb['cb_slot'] != 0 or sb['cb_offset'] < 68 or (sb['cb_offset'] - 68) % 4:
            raise ValueError(f"storage buffer at c[{sb['cb_slot']}] word {sb['cb_offset']} is not an NVN storage block slot")
        idx = (sb['cb_offset'] - 68) // 4
        var = f.var_by_binding(sb['binding'], 12) or f.var_by_binding(sb['binding'], SC['Uniform'])    # 12 = StorageBuffer
        if var is None or str(idx) not in plan.get('sbuf', {}):
            raise ValueError(f'storage block {idx} has no Unity buffer binding')
        f.set_binding(var[1][1], 0, plan['sbuf'][str(idx)])
    f.split_textures(res['textures'], {int(k): v for k, v in plan['tex'].items()}, {int(k): v for k, v in plan['samp'].items()},
                     {int(k): v for k, v in plan.get('own_samp', {}).items()}, {int(k): v for k, v in plan.get('inline', {}).items()})
    if stage == 'vs':
        f.flip_y()
    f.prune_capabilities()
    # insert new decorations after the last existing annotation, new declarations before the first function
    k = m.first_function_index()
    m.ins[k:k] = f.new
    last_dec = max((n for n, i in enumerate(m.ins[:k]) if i[0] in (OP['Decorate'], OP['MemberDecorate'])), default=None)
    if last_dec is None:
        last_dec = max(n for n, i in enumerate(m.ins[:k]) if i[0] in (OP['Name'], OP['MemberName'], 16, OP['EntryPoint']))
    m.ins[last_dec + 1:last_dec + 1] = f.decorate
    return m.bytes(), f.notes


if __name__ == '__main__':
    spv = open(sys.argv[1], 'rb').read()
    res = json.load(open(sys.argv[2], encoding='utf-8'))
    plan = json.load(open(sys.argv[3]))
    out, notes = fix(spv, res['stage'].replace('ps', 'fs'), res, plan, bytes.fromhex(plan.get('c1', '')))
    open(sys.argv[4], 'wb').write(out)
    for n in notes:
        print('note:', n)
