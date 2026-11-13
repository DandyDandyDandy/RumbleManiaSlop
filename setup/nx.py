"""Read Nintendo Switch game dumps: XCI cartridge images and NSP packages, with the console's own prod.keys.

Only what the setup needs: find the NCA archives, decrypt them (AES-XTS header, AES-CTR sections, title keys from the
ticket), read the executable file system (PFS0) and the data file system (RomFS), and apply an update's patch
(the "BKTR" relocation and counter tables) on top of the base game. Pure Python; the only dependency is
pycryptodome for AES.

    python nx.py info <file.xci|file.nsp> [...]         list the contents (needs input\\prod.keys or --keys)
    python nx.py extract <base> [<update.nsp>] <out>    write exefs\\ and romfs\\ of the (patched) program

Compressed dumps (.nsz, .xcz) are not supported.
"""
import bisect
import os
import struct
import sys

from Crypto.Cipher import AES

MEDIA = 0x200
CHUNK = 8 << 20


class NxError(Exception):
    pass


# ----------------------------------------------------------------------------------------------------------- keys

class Keys:
    """prod.keys: `name = hex` lines. Derived keys are taken when present and derived from the master keys otherwise."""

    def __init__(self, path):
        self.k = {}
        with open(path, encoding='utf-8', errors='replace') as f:
            for line in f:
                if '=' not in line or line.lstrip().startswith(('#', ';')):
                    continue
                name, _, val = line.partition('=')
                try:
                    self.k[name.strip().lower()] = bytes.fromhex(val.strip())
                except ValueError:
                    pass                              # lines this reader does not need may have any shape
        if 'header_key' not in self.k:
            try:
                kek = self._gen_kek(self.k['header_kek_source'], self.k['master_key_00'])
                self.k['header_key'] = _ecb_dec(kek, self.k['header_key_source'])
            except KeyError:
                raise NxError('prod.keys has neither header_key nor the keys to derive it '
                              '(header_kek_source, header_key_source, master_key_00, aes_kek_generation_source, '
                              'aes_key_generation_source)') from None
        if len(self.k['header_key']) != 32:
            raise NxError('prod.keys: header_key must be 64 hex digits')

    def _gen_kek(self, src, master):
        kek = _ecb_dec(master, self.k['aes_kek_generation_source'])
        k = _ecb_dec(kek, src)
        return _ecb_dec(k, self.k['aes_key_generation_source'])

    def _need(self, name, gen, how):
        key = self.k.get(f'{name}_{gen:02x}')
        if key and len(key) == 16:
            return key
        master = self.k.get(f'master_key_{gen:02x}')
        if not master or len(master) != 16:
            raise NxError(f'prod.keys has no {name}_{gen:02x} and no master_key_{gen:02x}: the keys are from a system '
                          f'version older than this game needs. Dump them again from an up-to-date console.')
        return how(master)

    def key_area_key(self, gen, index=0):
        names = ('key_area_key_application', 'key_area_key_ocean', 'key_area_key_system')
        return self._need(names[index], gen, lambda m: self._gen_kek(self.k[names[index] + '_source'], m))

    def titlekek(self, gen):
        return self._need('titlekek', gen, lambda m: _ecb_dec(m, self.k['titlekek_source']))


def _ecb_dec(key, data):
    return AES.new(key, AES.MODE_ECB).decrypt(data)


def _xts_decrypt(key, data, sector_size=MEDIA, first_sector=0):
    """AES-XTS as the console uses it: the tweak is the sector number, big-endian."""
    crypt, tweak = AES.new(key[:16], AES.MODE_ECB), AES.new(key[16:], AES.MODE_ECB)
    out = bytearray()
    for s in range(len(data) // sector_size):
        t = int.from_bytes(tweak.encrypt((first_sector + s).to_bytes(16, 'big')), 'little')
        sec = data[s * sector_size:(s + 1) * sector_size]
        masks = bytearray()
        for _ in range(sector_size // 16):
            masks += t.to_bytes(16, 'little')
            t <<= 1
            if t >> 128:
                t = (t & ((1 << 128) - 1)) ^ 0x87
        x = bytes(a ^ b for a, b in zip(sec, masks))
        out += bytes(a ^ b for a, b in zip(crypt.decrypt(x), masks))
    return bytes(out)


# ------------------------------------------------------------------------------------------------------ storages

class FileStorage:
    """A byte range of a file."""

    def __init__(self, f, offset, size):
        self.f, self.offset, self.size = f, offset, size

    def read(self, off, n):
        n = max(0, min(n, self.size - off))
        self.f.seek(self.offset + off)
        return self.f.read(n)

    def sub(self, off, size):
        return FileStorage(self.f, self.offset + off, size)


class CtrStorage:
    """AES-CTR over a storage. `upper` is the first 8 counter bytes; the last 8 are the absolute NCA offset / 16."""

    def __init__(self, base, key, upper, nca_offset):
        self.base, self.key, self.upper, self.nca_offset, self.size = base, key, upper, nca_offset, base.size

    def read(self, off, n, upper=None):
        n = max(0, min(n, self.size - off))
        if n <= 0:
            return b''
        start = off & ~15
        raw = self.base.read(start, (off + n - start + 15) & ~15)
        iv = (upper or self.upper) + ((self.nca_offset + start) >> 4).to_bytes(8, 'big')
        dec = AES.new(self.key, AES.MODE_CTR, nonce=b'', initial_value=iv).decrypt(raw)
        return dec[off - start:off - start + n]


class PlainStorage(FileStorage):
    pass


class SubStorage:
    def __init__(self, base, offset, size):
        self.base, self.offset, self.size = base, offset, size

    def read(self, off, n):
        n = max(0, min(n, self.size - off))
        return self.base.read(self.offset + off, n) if n > 0 else b''


class BktrStorage:
    """The data section of an update, laid over the base game's section.

    `patch` is the update's section (AES-CTR with a per-range counter value), `base` the decrypted section of the base
    game. The relocation table says for each range of the patched image whether it comes from the update (at which
    offset) or from the base game; the counter table gives the counter generation of each range of the update."""

    def __init__(self, patch, base, reloc_off, reloc_size, sub_off, sub_size):
        self.patch, self.base = patch, base
        rel = patch.read(reloc_off, reloc_size)
        sub = patch.read(sub_off, sub_size)
        self.size = struct.unpack_from('<Q', rel, 8)[0]
        self.rv, self.rp, self.rpatch = [], [], []
        for b in range(struct.unpack_from('<I', rel, 4)[0]):
            o = 0x4000 * (b + 1)
            for i in range(struct.unpack_from('<I', rel, o + 4)[0]):
                v, p, ip = struct.unpack_from('<QQI', rel, o + 0x10 + 0x14 * i)
                self.rv.append(v)
                self.rp.append(p)
                self.rpatch.append(ip)
        self.so, self.sc = [], []
        for b in range(struct.unpack_from('<I', sub, 4)[0]):
            o = 0x4000 * (b + 1)
            for i in range(struct.unpack_from('<I', sub, o + 4)[0]):
                off, _, ctr = struct.unpack_from('<QII', sub, o + 0x10 + 0x10 * i)
                self.so.append(off)
                self.sc.append(ctr)
        # the tables themselves (at the end of the section) use the section's own counter
        self.so.append(min(reloc_off, sub_off))
        self.sc.append(None)

    def _patch_read(self, off, n):
        out = []
        while n > 0:
            i = bisect.bisect_right(self.so, off) - 1
            end = self.so[i + 1] if i + 1 < len(self.so) else self.patch.size
            k = min(n, end - off)
            if k <= 0:
                raise NxError('update data: read outside the counter table')
            ctr = self.sc[i]
            upper = None if ctr is None else self.patch.upper[:4] + ctr.to_bytes(4, 'big')
            out.append(self.patch.read(off, k, upper))
            off += k
            n -= k
        return b''.join(out)

    def read(self, off, n):
        n = max(0, min(n, self.size - off))
        out = []
        while n > 0:
            i = bisect.bisect_right(self.rv, off) - 1
            end = self.rv[i + 1] if i + 1 < len(self.rv) else self.size
            k = min(n, end - off)
            src = off - self.rv[i] + self.rp[i]
            if self.rpatch[i]:
                out.append(self._patch_read(src, k))
            else:
                if self.base is None:
                    raise NxError('the update needs the base game: put the base game file in the input folder too')
                d = self.base.read(src, k)
                if len(d) != k:
                    raise NxError('the update does not fit this base game (different release of the game?)')
                out.append(d)
            off += k
            n -= k
        return b''.join(out)


# ---------------------------------------------------------------------------------------------------- containers

def _read_partition(st, magic, entry_size):
    """[(name, offset, size)] of a PFS0 / HFS0 partition held in storage `st`; offsets are relative to `st`."""
    h = st.read(0, 16)
    if h[:4] != magic:
        raise NxError(f'not a {magic.decode()} partition')
    count, strsize = struct.unpack_from('<II', h, 4)
    table = st.read(16, count * entry_size + strsize)
    names = table[count * entry_size:]
    data = 16 + count * entry_size + strsize
    out = []
    for i in range(count):
        off, size, name_off = struct.unpack_from('<QQI', table, i * entry_size)
        name = names[name_off:names.index(b'\0', name_off)].decode('utf-8', 'replace')
        out.append((name, data + off, size))
    return out


class Container:
    """An .xci or .nsp file: the NCA archives and tickets in it."""

    def __init__(self, path, keys):
        self.path, self.keys = path, keys
        self.f = open(path, 'rb')
        size = os.path.getsize(path)
        whole = FileStorage(self.f, 0, size)
        head = whole.read(0, 0x1200)
        self.kind = None
        if head[:4] == b'PFS0':
            self.kind = 'nsp'
            self.files = [(n, whole.sub(o, s)) for n, o, s in _read_partition(whole, b'PFS0', 0x18)]
        else:
            for base in (0, 0x1000):                  # a "full" cartridge dump starts with a 0x1000-byte key area
                if head[base + 0x100:base + 0x104] == b'HEAD':
                    self.kind = 'xci'
                    root_off = struct.unpack_from('<Q', head, base + 0x130)[0] + base
                    root = whole.sub(root_off, size - root_off)
                    self.files = []
                    for n, o, s in _read_partition(root, b'HFS0', 0x40):
                        if n == 'secure':
                            sec = root.sub(o, s)
                            self.files = [(m, sec.sub(mo, ms)) for m, mo, ms in _read_partition(sec, b'HFS0', 0x40)]
                    break
        if self.kind is None:
            if head[:4] in (b'NCZS', b'XCZ0') or path.lower().endswith(('.nsz', '.xcz')):
                raise NxError(f'{os.path.basename(path)}: compressed dumps (.nsz / .xcz) are not supported; '
                              f'use the plain .nsp / .xci')
            raise NxError(f'{os.path.basename(path)} is neither an XCI cartridge image nor an NSP package')
        self.tickets = {}
        for n, st in self.files:
            if n.endswith('.tik'):
                t = st.read(0, st.size)
                self.tickets[t[0x2a0:0x2b0]] = t[0x180:0x190]
        self.ncas = []
        for n, st in self.files:
            if n.endswith('.nca'):
                try:
                    self.ncas.append(Nca(n, st, keys, self.tickets))
                except NxError as e:
                    raise NxError(f'{os.path.basename(path)}: {n}: {e}') from None
            elif n.endswith('.ncz'):
                raise NxError(f'{os.path.basename(path)}: compressed dumps (.nsz / .xcz) are not supported')


CONTENT_TYPES = {0: 'Program', 1: 'Meta', 2: 'Control', 3: 'Manual', 4: 'Data', 5: 'PublicData'}


class Section:
    def __init__(self, nca, index, fs, start, end):
        self.nca, self.index = nca, index
        self.fs_type, self.hash_type, self.enc_type = fs[2], fs[3], fs[4]
        self.offset, self.size = start, end - start
        self.upper = fs[0x140:0x148][::-1]
        self.fs = fs
        self.is_patch = self.enc_type in (4, 6) and fs[0x110:0x114] == b'BKTR'

    def raw(self):
        """The decrypted section (for an update's data section: without the base game laid under it)."""
        st = self.nca.st.sub(self.offset, self.size)
        if self.enc_type == 1:
            return st
        if self.enc_type in (3, 4, 5, 6):
            return CtrStorage(st, self.nca.section_key(), self.upper, self.offset)
        raise NxError(f'section encryption type {self.enc_type} is not supported')

    def storage(self, base_section=None):
        raw = self.raw()
        if not self.is_patch:
            return raw
        ro, rs = struct.unpack_from('<QQ', self.fs, 0x100)
        so, ss = struct.unpack_from('<QQ', self.fs, 0x120)
        return BktrStorage(raw, base_section.raw() if base_section else None, ro, rs, so, ss)

    def content(self, base_section=None):
        """The file system image inside the section's hash layers."""
        st = self.storage(base_section)
        if self.fs_type == 1 and self.hash_type in (2, 5):        # PFS0 under a SHA-256 hash table
            off, size = struct.unpack_from('<QQ', self.fs, 0x40)
        elif self.fs_type == 0 and self.hash_type in (3, 6):      # RomFS under IVFC: the last of six levels
            off, size = struct.unpack_from('<QQ', self.fs, 0x18 + 5 * 0x18)
        else:
            raise NxError(f'section layout {self.fs_type}/{self.hash_type} is not supported')
        return SubStorage(st, off, size)


class Nca:
    def __init__(self, name, st, keys, tickets):
        self.name, self.st, self.keys = name, st, keys
        h = _xts_decrypt(keys.k['header_key'], st.read(0, 0xC00))
        if h[0x200:0x204] != b'NCA3':
            raise NxError('cannot read the NCA header: wrong or outdated prod.keys (header_key)?')
        self.h = h
        self.content_type = CONTENT_TYPES.get(h[0x205], str(h[0x205]))
        self.kak_index = h[0x207]
        self.title_id = struct.unpack_from('<Q', h, 0x210)[0]
        gen = max(h[0x206], h[0x220])
        self.key_gen = gen - 1 if gen else 0
        self.rights_id = h[0x230:0x240]
        self.tickets = tickets
        self.sections = []
        for i in range(4):
            s, e = struct.unpack_from('<II', h, 0x240 + 0x10 * i)
            if e > s:
                self.sections.append(Section(self, i, h[0x400 + 0x200 * i:0x600 + 0x200 * i], s * MEDIA, e * MEDIA))
        self._key = None

    def section_key(self):
        if self._key is None:
            if any(self.rights_id):
                enc = self.tickets.get(self.rights_id)
                if enc is None:
                    raise NxError(f'{self.name}: no ticket for this content in the file (a personalised or incomplete dump?)')
                self._key = _ecb_dec(self.keys.titlekek(self.key_gen), enc)
            else:
                area = _ecb_dec(self.keys.key_area_key(self.key_gen, self.kak_index), self.h[0x300:0x340])
                self._key = area[0x20:0x30]
        return self._key

    def section(self, fs_type):
        for s in self.sections:
            if s.fs_type == fs_type:
                return s
        return None

    @property
    def is_patch(self):
        return any(s.is_patch for s in self.sections)


# -------------------------------------------------------------------------------------------------- file systems

def pfs0_files(st):
    return [(n, SubStorage(st, o, s)) for n, o, s in _read_partition(st, b'PFS0', 0x18)]


def romfs_files(st):
    """[(path, offset, size)] of a RomFS image; offsets are relative to `st`."""
    h = struct.unpack('<10Q', st.read(0, 0x50))
    dir_off, dir_size, file_off, file_size, data_off = h[3], h[4], h[7], h[8], h[9]
    dirs = st.read(dir_off, dir_size)
    files = st.read(file_off, file_size)
    out = []
    stack = [(0, '')]
    while stack:
        d, path = stack.pop()
        _, sibling, child, first_file, _, nlen = struct.unpack_from('<6I', dirs, d)
        name = dirs[d + 0x18:d + 0x18 + nlen].decode('utf-8', 'replace')
        here = path + name + '/' if name else path
        if sibling != 0xffffffff:
            stack.append((sibling, path))
        if child != 0xffffffff:
            stack.append((child, here))
        f = first_file
        while f != 0xffffffff:
            _, nxt, off, size, _, nlen = struct.unpack_from('<IIQQII', files, f)
            fname = files[f + 0x20:f + 0x20 + nlen].decode('utf-8', 'replace')
            out.append((here + fname, data_off + off, size))
            f = nxt
    return out


def _safe_join(root, rel):
    parts = [p for p in rel.replace('\\', '/').split('/') if p]
    if any(p in ('.', '..') or ':' in p for p in parts):
        raise NxError(f'unsafe file name in the dump: {rel}')
    return os.path.join(root, *parts)


def write_storage(st, off, size, dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst + '.part', 'wb') as f:
        done = 0
        while done < size:
            d = st.read(off + done, min(CHUNK, size - done))
            if not d:
                raise NxError(f'unexpected end of data while writing {dst}')
            f.write(d)
            done += len(d)
    os.replace(dst + '.part', dst)


def extract_romfs(st, out, progress=None):
    files = romfs_files(st)
    total = sum(s for _, _, s in files) or 1
    done = 0
    for path, off, size in files:
        write_storage(st, off, size, _safe_join(out, path))
        done += size
        if progress:
            progress(done, total, path)
    return len(files)


# ------------------------------------------------------------------------------------------------------ the game

def find_program(containers, title_id=None):
    """(base Program NCA or None, newest update Program NCA or None) among the containers.

    The base game's data section is a plain RomFS; an update's is a patch. When several updates are present (a
    cartridge can carry one), an NSP wins over the cartridge and the larger file wins among equals."""
    base, patches = None, []
    for c in containers:
        for n in c.ncas:
            if n.content_type != 'Program' or (title_id and (n.title_id & ~0xfff) != (title_id & ~0xfff)):
                continue
            if n.is_patch:
                patches.append((c.kind == 'nsp', n.st.size, n))
            elif base is None or n.st.size > base.st.size:
                base = n
    patches.sort(key=lambda t: t[:2])
    return base, (patches[-1][2] if patches else None)


def extract_program(base, patch, out, progress=None):
    """Write exefs\\ (the executables) and romfs\\ (the data) of the game: the update's when there is one."""
    top = patch or base
    exe = top.section(1)
    if exe is None:
        raise NxError('the program has no executable file system')
    n = 0
    for name, st in pfs0_files(exe.content()):
        write_storage(st, 0, st.size, _safe_join(os.path.join(out, 'exefs'), name))
        n += 1
    data = top.section(0)
    if data is None:
        raise NxError('the program has no data file system')
    base_data = base.section(0) if (patch and base) else None
    n += extract_romfs(data.content(base_data), os.path.join(out, 'romfs'), progress)
    return n


def main():
    args = sys.argv[1:]
    keys_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'input', 'prod.keys')
    if '--keys' in args:
        i = args.index('--keys')
        keys_path = args[i + 1]
        del args[i:i + 2]
    if len(args) < 2 or args[0] not in ('info', 'extract'):
        sys.exit(__doc__)
    keys = Keys(keys_path)
    if args[0] == 'info':
        for p in args[1:]:
            c = Container(p, keys)
            print(f'{p}: {c.kind}, {len(c.ncas)} NCA, {len(c.tickets)} ticket(s)')
            for n in c.ncas:
                secs = ', '.join(f'{("romfs", "pfs0")[s.fs_type]}{" patch" if s.is_patch else ""} {s.size >> 20} MiB'
                                 for s in n.sections)
                print(f'  {n.name}  {n.content_type:10s} title {n.title_id:016x} keygen {n.key_gen}  [{secs}]')
    else:
        *srcs, out = args[1:]
        cs = [Container(p, keys) for p in srcs]
        base, patch = find_program(cs)
        if base is None and patch is None:
            sys.exit('no program found in these files')

        def prog(done, total, path, last=[-1]):
            pct = done * 100 // total
            if pct != last[0]:
                last[0] = pct
                print(f'\r{pct:3d}%', end='', flush=True)
        print(extract_program(base, patch, out, prog), 'files written to', out)


if __name__ == '__main__':
    try:
        main()
    except NxError as e:
        sys.exit(f'error: {e}')
