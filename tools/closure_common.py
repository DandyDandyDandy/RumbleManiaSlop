"""Shared loaders for the lift-closure analysis (closure_build.py / closure_census.py).

Everything is derived from the `main` NSO (work/game/exefs/main) and the il2cpp tables in work/unity.
  - function ranges: .eh_frame_hdr -> FDE (pc_begin, pc_range); gaps without FDE become pseudo-functions
  - direct branch edges: every BL and every B decoded with numpy over the whole .text
  - PLT stubs: adrp x16 / ldr x17,[x16,#o] / add x16 / br x17 -> JUMP_SLOT -> import symbol
  - relocations: RELR slots (link-time values in place), RELA ABS64/GLOB_DAT/JUMP_SLOT with symbols
"""
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import struct, sys, os, json, bisect, collections
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from il2cpp_link import load_image

ROOT = REPO
NSO = W + r'\work\game\exefs\main'
UNITY = W + r'\work\unity'
OUT = UNITY + r'\closure'
H = lambda s: int(s, 16) if isinstance(s, str) else s


class Image:
    def __init__(self):
        n, img, stats, relr, unres = load_image(NSO)
        self.n, self.img, self.relr = n, bytes(img), relr
        self.text_hi = n.text[1]
        self.rodata = (n.rodata[0], n.rodata[0] + n.rodata[1])
        self.data = (n.data[0], n.data[0] + n.data[1])
        self.bss = n.bss_range
        img = self.img
        self.w = np.frombuffer(img[:self.text_hi & ~3], dtype='<u4')
        self.layout = json.load(open(UNITY + r'\layout.json'))
        self._fdes()
        self._relocs()
        self._plt()

    def q(self, a):
        return struct.unpack_from('<Q', self.img, a)[0]

    # ---- FDE table
    def _fdes(self):
        img = self.img
        h0, h1 = self.n.eh_frame_hdr
        assert tuple(img[h0:h0 + 4]) == (1, 0x1b, 3, 0x3b)
        cnt = struct.unpack_from('<I', img, h0 + 8)[0]
        tab = np.frombuffer(img[h0 + 12:h0 + 12 + 8 * cnt], dtype='<i4').reshape(-1, 2).astype(np.int64) + h0
        order = np.argsort(tab[:, 0], kind='stable')
        tab = tab[order]
        starts = tab[:, 0]
        fde = tab[:, 1]
        # FDE: u32 len, u32 cie_ptr, pc_begin (pcrel sdata4 assumed, verified), u32 pc_range
        buf = np.frombuffer(img, dtype=np.uint8)
        def u32at(a):
            return (buf[a].astype(np.int64) | (buf[a + 1].astype(np.int64) << 8) | (buf[a + 2].astype(np.int64) << 16) | (buf[a + 3].astype(np.int64) << 24))
        pcb = u32at(fde + 8)
        pcb = np.where(pcb & 0x80000000, pcb - (1 << 32), pcb) + fde + 8
        rng = u32at(fde + 12)
        self.fde_pc_ok = int((pcb == starts).sum())
        self.fde_cnt = cnt
        self.fde_zero = [int(x) for x in starts[rng == 0]]
        keep = rng > 0                              # zero-length FDEs: leave the code to the gap logic
        starts, rng = starts[keep], rng[keep]
        ends = starts + rng
        nxt = np.append(starts[1:], self.text_hi)
        self.fde_overlap = int((ends > nxt).sum())
        ends = np.minimum(ends, nxt)
        # pseudo-functions for gaps (code without unwind info: asm routines, PLT, padding)
        fs, fe, isgap = [], [], []
        prev_end = 0
        w = self.w
        for s, e in zip(starts.tolist(), ends.tolist()):
            if s > prev_end:
                fs.append(prev_end); fe.append(s); isgap.append(True)
            fs.append(s); fe.append(e); isgap.append(False)
            prev_end = e
        if prev_end < self.text_hi:
            fs.append(prev_end); fe.append(self.text_hi); isgap.append(True)
        self.fs = np.array(fs, dtype=np.int64)
        self.fe = np.array(fe, dtype=np.int64)
        self.isgap = np.array(isgap, dtype=bool)
        # a gap is "code" if it holds anything other than zero / nop / udf padding
        nz = np.concatenate(([0], np.cumsum((w != 0) & (w != 0xd503201f))))
        g0, g1 = self.fs // 4, np.minimum(self.fe // 4, len(w))
        self.gapcode = self.isgap & ((nz[g1] - nz[g0]) > 0)
        self.fs_l = self.fs.tolist()

    def func_of(self, a):
        """index of the function/gap containing address a (or -1)"""
        i = bisect.bisect_right(self.fs_l, a) - 1
        if i < 0 or a >= self.fe[i]:
            return -1
        return i

    # ---- relocations
    def _relocs(self):
        img, n = self.img, self.n
        self.slot_sym = {}      # slot -> (type, symbol dict, addend)
        for tab, sz in ((n.dt.get(7), n.dt.get(8, 0)), (n.dt.get(23), n.dt.get(2, 0))):
            for p in range(tab, tab + sz, 24):
                off, info, add = struct.unpack_from('<QQq', img, p)
                self.slot_sym[off] = (info & 0xffffffff, n.syms[info >> 32], add)
        self.relr_arr = np.array(sorted(self.relr), dtype=np.int64)
        vals = np.frombuffer(img, dtype=np.uint8)
        # values of relr slots (unaligned-safe)
        self.relr_val = np.array([struct.unpack_from('<Q', img, s)[0] for s in self.relr_arr.tolist()], dtype=np.uint64).astype(np.int64)

    # ---- PLT
    def _plt(self):
        w = self.w
        isadrp16 = (w & 0x9f00001f) == 0x90000010
        ldr17 = (np.roll(w, -1) & 0xffc003ff) == 0xf9400211
        add16 = (np.roll(w, -2) & 0xffc003ff) == 0x91000210
        br17 = np.roll(w, -3) == 0xd61f0220
        idx = np.nonzero(isadrp16 & ldr17 & add16 & br17)[0]
        self.plt = {}           # stub address -> symbol name
        for i in idx.tolist():
            pc = i * 4
            x = int(w[i])
            imm = (((x >> 5) & 0x7ffff) << 2) | ((x >> 29) & 3)
            if imm & (1 << 20):
                imm -= 1 << 21
            page = (pc & ~0xfff) + (imm << 12)
            slot = page + ((int(w[i + 1]) >> 10) & 0xfff) * 8
            r = self.slot_sym.get(slot)
            self.plt[pc] = (r[1]['name'] if r else f'?slot_{slot:#x}', slot)

    # ---- branches
    def branches(self):
        """returns (bl_src, bl_tgt, b_src, b_tgt) arrays of addresses for all BL / B in .text"""
        w = self.w
        pc = np.arange(len(w), dtype=np.int64) * 4
        imm = (w & 0x3ffffff).astype(np.int64)
        imm = np.where(imm & (1 << 25), imm - (1 << 26), imm)
        tgt = pc + imm * 4
        isbl = (w & 0xfc000000) == 0x94000000
        isb = (w & 0xfc000000) == 0x14000000
        return pc[isbl], tgt[isbl], pc[isb], tgt[isb]

    def adrp_refs(self):
        """ADRP-based address materialisations.
        returns arrays (pc, target, kind) with kind 0=adrp+add, 1=adrp+ldr/str/ldrb.. (memory operand, any size),
        2=adr, 3=ldr literal, 4=bare adrp page (no paired add/mem in the next insn)"""
        w = self.w
        pc = np.arange(len(w), dtype=np.int64) * 4
        isadrp = (w & 0x9f000000) == 0x90000000
        imm = (((w >> 5) & 0x7ffff).astype(np.int64) << 2) | ((w >> 29) & 3).astype(np.int64)
        imm = np.where(imm & (1 << 20), imm - (1 << 21), imm)
        page = (pc & ~0xfff) + (imm << 12)
        rd = w & 31
        nxt = np.roll(w, -1)
        nrn = (nxt >> 5) & 31
        isadd = ((nxt & 0xff800000) == 0x91000000) & (nrn == rd)
        addimm = ((nxt >> 10) & 0xfff).astype(np.int64)
        addimm = np.where((nxt >> 22) & 1, addimm << 12, addimm)
        # load/store unsigned offset: size(2) 111 V 01 opc(2) imm12 Rn Rt
        ismem = ((nxt & 0x3b000000) == 0x39000000) & (nrn == rd)
        size = (nxt >> 30).astype(np.int64)
        isvec128 = ((nxt >> 26) & 1).astype(bool) & (((nxt >> 23) & 1) == 1)
        scale = np.where(isvec128, 4, size)
        memoff = ((nxt >> 10) & 0xfff).astype(np.int64) << scale
        isload64 = ismem & ((nxt & 0xffc00000) == 0xf9400000)
        out_pc, out_t, out_k = [], [], []
        m = isadrp & isadd
        out_pc.append(pc[m]); out_t.append((page + addimm)[m]); out_k.append(np.zeros(m.sum(), dtype=np.int8))
        m2 = isadrp & ismem
        out_pc.append(pc[m2]); out_t.append((page + memoff)[m2]); out_k.append(np.where(isload64[m2], 5, 1).astype(np.int8))
        # bare ADRP (offset applied later): scan forward for uses of the page register (heuristic, linear, no CFG)
        m4 = isadrp & ~isadd & ~ismem
        wl = w
        nW = len(w)
        b_pc, b_t, b_k = [], [], []
        idx4 = np.nonzero(m4)[0]
        pg4 = page[idx4].tolist()
        rd4 = rd[idx4].tolist()
        for i, pg, r in zip(idx4.tolist(), pg4, rd4):
            found = False
            for j in range(i + 1, min(i + 24, nW)):
                x = int(wl[j])
                rn = (x >> 5) & 31
                rt = x & 31
                if (x & 0x3b000000) == 0x39000000 and rn == r:          # ldr/str [r, #imm]
                    sz = x >> 30
                    if (x >> 26) & 1 and (x >> 23) & 1:
                        sz = 4
                    b_pc.append(j * 4); b_t.append(pg + (((x >> 10) & 0xfff) << sz))
                    b_k.append(5 if (x & 0xffc00000) == 0xf9400000 else 1)
                    found = True
                    if rt == r and (x >> 22) & 1 and not (x >> 26) & 1:   # load into the same register
                        break
                    continue
                if (x & 0xff800000) == 0x91000000 and rn == r:          # add xd, r, #imm
                    imm_ = (x >> 10) & 0xfff
                    if (x >> 22) & 1:
                        imm_ <<= 12
                    b_pc.append(j * 4); b_t.append(pg + imm_); b_k.append(0)
                    found = True
                    if rt == r:
                        break
                    continue
                if x == 0xd65f03c0 or (x & 0xfc000000) == 0x14000000 or (x & 0xfffffc1f) == 0xd61f0000:   # ret / b / br
                    break
                if (x & 0xfc000000) == 0x94000000 or (x & 0xfffffc1f) == 0xd63f0000:                      # bl / blr
                    if r <= 18:
                        break
                    continue
                if (x & 0x9f000000) in (0x90000000, 0x10000000) and rt == r:                              # adrp/adr to same reg
                    break
                # generic kill: Rd field equals r for data-processing / load instructions
                if rt == r and ((x & 0x1e000000) in (0x0a000000, 0x1a000000, 0x10000000, 0x12000000)      # dp reg / dp imm
                                or ((x & 0x0a000000) == 0x08000000 and (x >> 22) & 1)):                   # loads
                    break
            if not found:
                b_pc.append(i * 4); b_t.append(pg); b_k.append(4)
        out_pc.append(np.array(b_pc, dtype=np.int64)); out_t.append(np.array(b_t, dtype=np.int64)); out_k.append(np.array(b_k, dtype=np.int8))
        isadr = (w & 0x9f000000) == 0x10000000
        out_pc.append(pc[isadr]); out_t.append((pc + imm)[isadr]); out_k.append(np.full(isadr.sum(), 2, dtype=np.int8))
        islit = (w & 0xbf000000) == 0x18000000
        l = ((w >> 5) & 0x7ffff).astype(np.int64)
        l = np.where(l & (1 << 18), l - (1 << 19), l)
        out_pc.append(pc[islit]); out_t.append((pc + l * 4)[islit]); out_k.append(np.full(islit.sum(), 3, dtype=np.int8))
        return np.concatenate(out_pc), np.concatenate(out_t), np.concatenate(out_k)


def load_tables(im):
    """il2cpp table roots: {address: kind}, plus naming maps"""
    kind, name, img_of = {}, {}, {}
    with open(UNITY + r'\methods.tsv', encoding='utf-8') as f:
        next(f)
        for line in f:
            p = line.rstrip('\n').split('\t')
            if p[3]:
                a = int(p[3], 16)
                kind[a] = 'method'
                name.setdefault(a, f'{p[1]}::{p[2]}')
                img_of.setdefault(a, p[0])
    with open(UNITY + r'\generic_methods.tsv', encoding='utf-8') as f:
        next(f)
        for line in f:
            p = line.rstrip('\n').split('\t')
            if p[2]:
                a = int(p[2], 16)
                kind.setdefault(a, 'generic'); name.setdefault(a, p[1])
            if p[3]:
                a = int(p[3], 16)
                kind.setdefault(a, 'generic_adjustor'); name.setdefault(a, 'adj:' + p[1])
    q = im.q
    lay = im.layout
    cr = lay['code_registration']['fields']
    for nm, k, c in (('invokerPointers', 'invoker', 'invokerPointersCount'), ('reversePInvokeWrappers', 'reverse_pinvoke', 'reversePInvokeWrapperCount'),
                     ('unresolvedVirtualCallPointers', 'unresolved_call', 'unresolvedIndirectCallCount'),
                     ('unresolvedInstanceCallPointers', 'unresolved_call', 'unresolvedIndirectCallCount'),
                     ('unresolvedStaticCallPointers', 'unresolved_call', 'unresolvedIndirectCallCount'),
                     ('genericAdjustorThunks', 'generic_adjustor', None)):
        t = H(cr[nm])
        c = H(cr[c]) if c else H(lay['tables']['genericAdjustorThunks']['count'])
        for i in range(c):
            a = q(t + 8 * i)
            if a:
                kind.setdefault(a, k)
    mods = H(cr['codeGenModules'])
    for i in range(H(cr['codeGenModulesCount'])):
        rec = q(mods + 8 * i)
        ac, ap = struct.unpack_from('<I', im.img, rec + 0x18)[0], q(rec + 0x20)
        for j in range(ac):
            kind.setdefault(q(ap + 16 * j + 8), 'adjustor')
    # Il2CppInteropData: {delegatePInvokeWrapper, pinvokeMarshalToNative, pinvokeMarshalFromNative, pinvokeMarshalCleanup,
    #                     createCCW, guid, type} (7 pointers)
    t, c = H(cr['interopData']), H(cr['interopDataCount'])
    for i in range(c):
        for j in range(5):
            a = q(t + 56 * i + 8 * j)
            if 0 < a < im.text_hi:
                kind.setdefault(a, 'interop')
    return kind, name, img_of


class Graph:
    """CSR adjacency over function indices"""
    def __init__(self, n, src, dst):
        o = np.argsort(src, kind='stable')
        self.src, self.dst = src[o], dst[o]
        self.ptr = np.searchsorted(self.src, np.arange(n + 1))
        self.n = n

    def succ(self, nodes):
        if len(nodes) == 0:
            return nodes
        a, b = self.ptr[nodes], self.ptr[nodes + 1]
        tot = int((b - a).sum())
        if tot == 0:
            return np.empty(0, dtype=np.int64)
        idx = np.repeat(a - np.concatenate(([0], np.cumsum(b - a)[:-1])), b - a) + np.arange(tot)
        return np.unique(self.dst[idx])

    def closure(self, roots, allowed=None):
        seen = np.zeros(self.n, bool)
        front = np.unique(np.asarray(roots, dtype=np.int64))
        if allowed is not None:
            front = front[allowed[front]]
        seen[front] = True
        while len(front):
            nb = self.succ(front)
            nb = nb[~seen[nb]]
            if allowed is not None:
                nb = nb[allowed[nb]]
            seen[nb] = True
            front = nb
        return seen
