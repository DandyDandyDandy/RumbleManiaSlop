"""Resolve il2cpp method addresses for one assembly from main.bin (flat image, base 0).

Applies R_AARCH64_RELATIVE relocs, finds the Il2CppCodeGenModule by module-name pointer,
maps method token RID -> methodPointers[rid-1].

    python il2cpp_addr.py <main.bin> <global-metadata.dat> <Assembly.dll>
"""
import struct, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from il2cpp_meta import Meta


def load_relocated(path):
    img = bytearray(open(path, 'rb').read())
    mod = struct.unpack_from('<I', img, 4)[0]
    assert img[mod:mod + 4] == b'MOD0'
    dyn = mod + struct.unpack_from('<i', img, mod + 4)[0]
    dt = {}
    p = dyn
    while True:
        tag, val = struct.unpack_from('<qQ', img, p)
        p += 16
        if tag == 0:
            break
        dt[tag] = val
    rela, relasz = dt[7], dt[8]
    n = 0
    for i in range(relasz // 24):
        off, info, add = struct.unpack_from('<QQq', img, rela + 24 * i)
        if info & 0xffffffff == 0x403:
            struct.pack_into('<Q', img, off, add & 0xffffffffffffffff)
            n += 1
    return img, n


def find_module(img, name):
    s = img.find(name.encode() + b'\0')
    res = []
    while s != -1:
        pat = struct.pack('<Q', s)
        p = img.find(pat)
        while p != -1:
            if p % 8 == 0:
                cnt, ptrs = struct.unpack_from('<QQ', img, p + 8)
                res.append((p, cnt, ptrs))
            p = img.find(pat, p + 1)
        s = img.find(name.encode() + b'\0', s + 1)
    return res


if __name__ == '__main__':
    img, n = load_relocated(sys.argv[1])
    m = Meta(sys.argv[2])
    asm = sys.argv[3]
    mods = find_module(img, asm)
    print('# relocs applied', n, 'module candidates', [(hex(a), c, hex(b)) for a, c, b in mods], file=sys.stderr)
    p, cnt, ptrs = mods[0]
    for t in m.types:
        if t.get('image') != asm:
            continue
        for me in m.methods_of(t):
            rid = me['token'] & 0xffffff
            addr = struct.unpack_from('<Q', img, ptrs + 8 * (rid - 1))[0] if 0 < rid <= cnt else 0
            print(f"{addr:#x}\t{m.fullname(t)}::{me['name']}\t{me['token']:#x}\tfl={me['flags']:04x}")
