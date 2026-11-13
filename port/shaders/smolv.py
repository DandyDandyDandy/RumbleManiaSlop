"""SMOL-V <-> SPIR-V codec (Unity stores Vulkan shader modules as SMOL-V, encoding version 1).

Own Python implementation of the format defined by aras-p/smol-v (public domain / MIT). The per-opcode
table (hasResult, hasType, deltaFromResult, varrest) is read as data from third_party/smolv/smolv.cpp.

    python smolv.py decode in.smolv out.spv
    python smolv.py encode in.spv out.smolv
"""
import os
import re
import struct
import sys

_src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'third_party', 'smolv', 'smolv.cpp'),
            encoding='utf-8', errors='replace').read()
_tab = _src[_src.index('static const OpData kSpirvOpData[] ='):]
_tab = _tab[:_tab.index('};')]
OPDATA = [tuple(int(x) for x in m) for m in re.findall(r'\{\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\}', _tab)]
assert len(OPDATA) == 367, len(OPDATA)
KNOWN = {0: 331, 1: 367}

OP_DECORATE, OP_MEMBER_DECORATE, OP_LOAD, OP_STORE, OP_ACCESS_CHAIN, OP_SHUFFLE, OP_SHUFFLE_COMPACT = 71, 72, 61, 62, 65, 79, 13
_SWAPS = [(71, 0), (61, 1), (62, 2), (65, 3), (79, 4), (72, 7), (248, 8), (59, 9), (133, 10), (129, 11), (32, 14), (127, 15)]
_REMAP = {}
for _a, _b in _SWAPS:
    _REMAP[_a], _REMAP[_b] = _b, _a
_LEN_ADJ = {OP_SHUFFLE: 4, OP_SHUFFLE_COMPACT: 4, OP_DECORATE: 2, OP_LOAD: 3, OP_ACCESS_CHAIN: 3}
M32 = 0xffffffff


def _zig_enc(i):
    i &= M32
    s = M32 if i & 0x80000000 else 0
    return ((i << 1) & M32) ^ s


def _zig_dec(u):
    return ((u >> 1) ^ M32) if u & 1 else (u >> 1)


def _dec_extra(dec):
    if dec == 0 or 2 <= dec <= 5:
        return 0
    if 29 <= dec <= 37:
        return 1
    return -1


def _data(op, n):
    return OPDATA[op] if 0 <= op < n else (0, 0, 0, 0)


def decode(b):
    magic, ver, gen, bound, schema, size = struct.unpack_from('<6I', b, 0)
    if magic != 0x534D4F4C:
        raise ValueError('not SMOL-V')
    smolver = ver >> 24
    known = KNOWN[smolver]
    out = [0x07230203, ver & 0xffffff, gen, bound, schema]
    pos = 24
    end = len(b)

    def varint():
        nonlocal pos
        v = 0
        shift = 0
        while True:
            c = b[pos]
            pos += 1
            v |= (c & 0x7f) << shift
            shift += 7
            if not c & 0x80:
                return v & M32

    prev_result = prev_decorate = 0
    while pos < end:
        val = varint()
        ln = ((val >> 20) << 4) | ((val >> 4) & 0xf)
        op = ((val >> 4) & 0xfff0) | (val & 0xf)
        op = _REMAP.get(op, op)
        ln += 1 + _LEN_ADJ.get(op, 0)
        swizzle = op == OP_SHUFFLE_COMPACT
        if swizzle:
            op = OP_SHUFFLE
        has_result, has_type, delta, varrest = _data(op, known)
        out.append((ln << 16) | op)
        ioffs = 1
        if has_type:
            out.append(varint())
            ioffs += 1
        if has_result:
            prev_result = (prev_result + _zig_dec(varint())) & M32
            out.append(prev_result)
            ioffs += 1
        if op in (OP_DECORATE, OP_MEMBER_DECORATE):
            prev_decorate = (prev_decorate + _zig_dec(varint())) & M32
            out.append(prev_decorate)
            ioffs += 1
        if op == OP_MEMBER_DECORATE:
            count = b[pos]
            pos += 1
            prev_index = prev_offset = 0
            for m in range(count):
                prev_index = (prev_index + varint()) & M32
                dec = varint()
                extra = _dec_extra(dec)
                mlen = varint() + 4 if extra == -1 else 4 + extra
                if m:
                    out.append((mlen << 16) | op)
                    out.append(prev_decorate)
                out.append(prev_index)
                out.append(dec)
                if dec == 35:
                    prev_offset = (prev_offset + varint()) & M32
                    out.append(prev_offset)
                else:
                    for _ in range(4, mlen):
                        out.append(varint())
            continue
        i = 0
        while i < delta and ioffs < ln:
            out.append((prev_result - _zig_dec(varint())) & M32)
            i += 1
            ioffs += 1
        if swizzle and ln <= 9:
            s = b[pos]
            pos += 1
            for k, sh in ((5, 6), (6, 4), (7, 2), (8, 0)):
                if ln > k:
                    out.append((s >> sh) & 3)
        elif varrest:
            for _ in range(ioffs, ln):
                out.append(varint())
        else:
            n = ln - ioffs
            out.extend(struct.unpack_from(f'<{n}I', b, pos))
            pos += 4 * n
    res = struct.pack(f'<{len(out)}I', *out)
    if len(res) != size:
        raise ValueError(f'decoded {len(res)} bytes, header says {size}')
    return res


def encode(spv):
    w = struct.unpack(f'<{len(spv) // 4}I', spv)
    if w[0] != 0x07230203:
        raise ValueError('not SPIR-V')
    out = bytearray(struct.pack('<6I', 0x534D4F4C, (w[1] & 0xffffff) | (1 << 24), w[2], w[3], w[4], len(spv)))
    known = KNOWN[1]

    def varint(v):
        v &= M32
        while v > 127:
            out.append((v & 127) | 128)
            v >>= 7
        out.append(v)

    prev_result = prev_decorate = 0
    p = 5
    n = len(w)
    while p < n:
        ln, op = w[p] >> 16, w[p] & 0xffff
        if ln < 1 or p + ln > n:
            raise ValueError('malformed SPIR-V')
        swizzle = 0
        if op == OP_SHUFFLE and ln <= 9:
            sw = [w[p + k] if ln > k else 0 for k in (5, 6, 7, 8)]
            if all(x < 4 for x in sw):
                op = OP_SHUFFLE_COMPACT
                swizzle = (sw[0] << 6) | (sw[1] << 4) | (sw[2] << 2) | sw[3]
        el = ln - 1 - _LEN_ADJ.get(op, 0)
        if el < 0 or el > 0xffff:
            raise ValueError('bad length')
        rop = _REMAP.get(op, op)
        varint(((el >> 4) << 20) | ((rop >> 4) << 8) | ((el & 0xf) << 4) | (rop & 0xf))
        has_result, has_type, delta, varrest = _data(op, known)
        ioffs = 1
        if has_type:
            varint(w[p + ioffs])
            ioffs += 1
        if has_result:
            v = w[p + ioffs]
            varint(_zig_enc(v - prev_result))
            prev_result = v
            ioffs += 1
        if op in (OP_DECORATE, OP_MEMBER_DECORATE):
            v = w[p + ioffs]
            varint(_zig_enc(v - prev_decorate))
            prev_decorate = v
            ioffs += 1
        if op == OP_MEMBER_DECORATE:
            dtype = w[p + ioffs - 1]
            q = p
            prev_index = prev_offset = 0
            cloc = len(out)
            out.append(0)
            count = 0
            while q < n and count < 255:
                mlen, mop = w[q] >> 16, w[q] & 0xffff
                if mop != OP_MEMBER_DECORATE or w[q + 1] != dtype:
                    break
                idx = w[q + 2]
                varint(idx - prev_index)
                prev_index = idx
                dec = w[q + 3]
                varint(dec)
                extra = _dec_extra(dec)
                if extra == -1:
                    varint(mlen - 4)
                elif extra + 4 != mlen:
                    raise ValueError('bad member decoration')
                if dec == 35:
                    varint(w[q + 4] - prev_offset)
                    prev_offset = w[q + 4]
                else:
                    for i in range(4, mlen):
                        varint(w[q + i])
                q += mlen
                count += 1
            out[cloc] = count
            p = q
            continue
        i = 0
        while i < delta and ioffs < ln:
            varint(_zig_enc(prev_result - w[p + ioffs]))
            i += 1
            ioffs += 1
        if op == OP_SHUFFLE_COMPACT:
            out.append(swizzle)
        elif varrest:
            for k in range(ioffs, ln):
                varint(w[p + k])
        else:
            for k in range(ioffs, ln):
                out += struct.pack('<I', w[p + k])
        p += ln
    return bytes(out)


if __name__ == '__main__':
    data = open(sys.argv[2], 'rb').read()
    open(sys.argv[3], 'wb').write(decode(data) if sys.argv[1] == 'decode' else encode(data))
