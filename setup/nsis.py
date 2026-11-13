"""Read files out of an NSIS installer (the format of Unity's "Windows Build Support (IL2CPP)" download) without
running it and without 7-Zip.

    python nsis.py list <installer.exe>
    python nsis.py extract <installer.exe> <out dir> [path prefix ...]

Supports what that installer uses: NSIS 3 (Unicode or ANSI strings), LZMA / zlib / bzip2, solid or not. Only the two
script instructions needed to place files are interpreted: "create directory + set output path" and "extract file".
The 64-bit variant Unity uses for large installers (9 words per instruction) is handled too.
"""
import bz2
import lzma
import os
import struct
import sys
import zlib

SIG = b'\xef\xbe\xad\xdeNullsoftInst'


class _Stream:
    """Sequential reader over a compressed stream (solid installers) or over raw bytes."""

    def __init__(self, f, decomp=None):
        self.f, self.d, self.buf, self.eof = f, decomp, bytearray(), False

    def read(self, n):
        while len(self.buf) < n and not self.eof:
            raw = self.f.read(1 << 20)
            if not raw:
                self.eof = True
                break
            self.buf += self.d.decompress(raw) if self.d else raw
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def skip(self, n):
        while n > 0:
            got = len(self.read(min(n, 1 << 22)))
            if not got:
                raise ValueError('unexpected end of installer data')
            n -= got


def _lzma_raw(props):
    d = props[0]
    lc, rest = d % 9, d // 9
    lp, pb = rest % 5, rest // 5
    dict_size = struct.unpack_from('<I', props, 1)[0]
    return lzma.LZMADecompressor(lzma.FORMAT_RAW, filters=[{'id': lzma.FILTER_LZMA1, 'dict_size': max(dict_size, 4096),
                                                            'lc': lc, 'lp': lp, 'pb': pb}])


def _is_lzma(b):
    return len(b) > 5 and b[0] == 0x5D and b[1] == 0 and b[2] == 0 and b[4] < 0x20 and b[5] == 0


def _decomp_for(head):
    """(kind, decompressor factory, bytes of method header to skip) from the first bytes of a compressed block."""
    if _is_lzma(head):
        return 'lzma', (lambda: _lzma_raw(head[:5])), 5
    if head[:1] == b'\x31' and head[1:2] < b'\x0e':
        return 'bzip2-nsis', None, 0
    return 'zlib', (lambda: zlib.decompressobj(-15)), 0


class Nsis:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        size = os.path.getsize(path)
        pos = 0
        self.first = None
        while pos + 28 <= size:                      # the first header sits on a 512-byte boundary after the stub
            self.f.seek(pos)
            b = self.f.read(28)
            if b[4:20] == SIG:
                self.first = pos
                self.flags, _, _, _, self.hdr_len, self.all_len = struct.unpack('<I4s12sII', b[:28]) if False else \
                    (struct.unpack_from('<I', b, 0)[0], 0, 0, 0, struct.unpack_from('<I', b, 20)[0], struct.unpack_from('<I', b, 24)[0])
                break
            pos += 512
        if self.first is None:
            raise ValueError('not an NSIS installer: ' + path)
        # The data follows the 28-byte first header; builds for installers over 2 GB (the one Unity uses) store
        # 64-bit lengths and put 8 more bytes in between. solid: the compressed stream starts right there.
        # non-solid: a 4-byte block size (bit 31 = compressed) comes first.
        self.kind = None
        for skip in (0, 4, 8, 12):
            self.f.seek(self.first + 28 + skip)
            head = self.f.read(16)
            n = struct.unpack_from('<I', head, 0)[0]
            if _is_lzma(head):
                self.kind, self.solid = 'lzma', True
            elif n & 0x80000000 and (n & 0x7fffffff) < self.all_len and _is_lzma(head[4:]):
                self.kind, self.solid = 'lzma', False
            elif n == self.hdr_len:
                self.kind, self.solid = 'none', False
            else:
                continue
            self.data_start = self.first + 28 + skip
            break
        if self.kind is None:                        # zlib streams have no marker to recognise
            self.data_start = self.first + 28
            self.f.seek(self.data_start)
            n = struct.unpack('<I', self.f.read(4))[0]
            self.kind, self.solid = 'zlib', not (n & 0x80000000)
        if self.kind == 'bzip2-nsis':
            raise ValueError('NSIS bzip2 installers are not supported')
        self._load_header()

    # ---- header --------------------------------------------------------------------------------------------
    def _solid_stream(self):
        self.f.seek(self.data_start)
        if self.kind == 'lzma':
            d = _lzma_raw(self.f.read(5))
        else:
            d = zlib.decompressobj(-15)
        return _Stream(self.f, d)

    def _block(self, f):
        """One non-solid block at the file's position: (data, bytes consumed)."""
        n = struct.unpack('<I', f.read(4))[0]
        size = n & 0x7fffffff
        raw = f.read(size)
        if not n & 0x80000000:
            return raw
        if self.kind == 'lzma':
            return _lzma_raw(raw[:5]).decompress(raw[5:])
        return zlib.decompressobj(-15).decompress(raw)

    def _load_header(self):
        if self.solid:
            s = self._solid_stream()
            n = struct.unpack('<I', s.read(4))[0]
            self.header = s.read(n)
            self.files_base = None                   # file data follows in the same stream
        else:
            self.f.seek(self.data_start)
            self.header = self._block(self.f)
            self.files_base = self.f.tell()
        h = self.header
        # common header: flags (4), then 8 block headers {offset, count}
        blocks = [struct.unpack_from('<II', h, 4 + 8 * i) for i in range(8)]
        self.entries_off, self.entries_num = blocks[2]
        self.strings_off = blocks[3][0]
        # 28 bytes per instruction (number + 6 parameters); 36 in the builds with 64-bit data offsets
        self.entry_size = (self.strings_off - self.entries_off) // max(self.entries_num, 1)
        if self.entry_size not in (28, 36):
            raise ValueError(f'unexpected NSIS instruction size {self.entry_size}')
        self.lang_off = blocks[4][0]
        strs = h[self.strings_off:self.lang_off]
        # Unicode builds store UTF-16: the string table then starts with two zero bytes (an empty string)
        self.unicode = strs[:2] == b'\0\0'
        self.strs = strs
        self._find_opcodes()

    def _string(self, off):
        """The string at a string-table offset, with variables written as $<n> and other codes dropped."""
        s = self.strs
        out = []
        if self.unicode:
            p = off * 2
            while p + 1 < len(s):
                c = s[p] | s[p + 1] << 8
                p += 2
                if c == 0:
                    break
                if 1 <= c <= 4:                      # NS_LANG, NS_SHELL, NS_VAR, NS_SKIP (Unicode numbering)
                    w = s[p] | s[p + 1] << 8
                    p += 2
                    if c == 4:
                        out.append(chr(w))
                    elif c == 3:
                        out.append('$%d;' % ((w & 0x7f) | ((w >> 8) & 0x7f) << 7))
                    else:
                        out.append('$?;')
                else:
                    out.append(chr(c))
        else:
            p = off
            while p < len(s):
                c = s[p]
                p += 1
                if c == 0:
                    break
                if c in (1, 2, 3, 4) or c >= 0xfc:
                    w = s[p] | s[p + 1] << 8 if p + 1 < len(s) else 0
                    if c in (4, 0xfc):
                        out.append(chr(s[p]))
                        p += 1
                    else:
                        p += 2
                        var = c in (3, 0xfd)
                        out.append('$%d;' % ((w & 0x7f) | ((w >> 8) & 0x7f) << 7) if var else '$?;')
                else:
                    out.append(chr(c))
        return ''.join(out)

    def _entries(self):
        h = self.header
        n = self.entry_size // 4
        for i in range(self.entries_num):
            yield struct.unpack_from('<%di' % n, h, self.entries_off + self.entry_size * i)

    def _find_opcodes(self):
        """EW_CREATEDIR and EW_EXTRACTFILE have had the same numbers in every NSIS 2 and 3 release. Check that the
        extract instructions look like it (a name string and a data offset inside the installer)."""
        self.op_setdir, self.op_extract = 11, 20
        ex = [e for e in self._entries() if e[0] == self.op_extract]
        limit = len(self.strs) // (2 if self.unicode else 1)
        if not ex or not all(0 <= e[2] < limit and 0 <= e[3] <= self.all_len for e in ex):
            raise ValueError('the NSIS script does not use the expected instruction numbers')

    # ---- files ---------------------------------------------------------------------------------------------
    def files(self):
        """[(path, data offset)] in script order; paths are relative to the install folder, with forward slashes."""
        out = []
        cur = ''
        for e in self._entries():
            if e[0] == self.op_setdir and e[2] == 1:
                cur = self._clean(self._string(e[1]))
            elif e[0] == self.op_extract:
                raw_name = self._string(e[2])
                name = self._clean(raw_name)
                off = e[3] & 0xffffffff
                if self.entry_size == 36:
                    off |= (e[4] & 0xffffffff) << 32
                # a name that starts with a variable ($PLUGINSDIR\x.dll) is not under the output folder
                out.append((name if raw_name.startswith('$') else (cur + '/' + name).strip('/'), off))
        return out

    @staticmethod
    def _clean(s):
        s = s.replace('\\', '/')
        while s.startswith('$'):                     # $INSTDIR / $OUTDIR style variable at the front: drop it
            s = s.split(';', 1)[1] if ';' in s else ''
        return s.strip('/')

    def extract(self, out_dir, want=None, progress=None):
        """Write the files (those for which want(path) is true) under out_dir. Returns the number written."""
        todo = sorted(((off, p) for p, off in self.files() if want is None or want(p)))
        n = 0
        if self.solid:
            s = self._solid_stream()
            s.skip(4 + self.hdr_len)
            pos = 0
            for off, p in todo:
                if off < pos:
                    continue                          # the same data listed twice
                s.skip(off - pos)
                size = struct.unpack('<I', s.read(4))[0] & 0x7fffffff
                self._write(out_dir, p, s.read(size))
                pos = off + 4 + size
                n += 1
                if progress:
                    progress(n, len(todo), p)
        else:
            for off, p in todo:
                self.f.seek(self.files_base + off)
                self._write(out_dir, p, self._block(self.f))
                n += 1
                if progress:
                    progress(n, len(todo), p)
        return n

    @staticmethod
    def _write(out_dir, rel, data):
        dst = os.path.join(out_dir, *rel.split('/'))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(data)


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ('list', 'extract'):
        sys.exit(__doc__)
    n = Nsis(sys.argv[2])
    if sys.argv[1] == 'list':
        print(f'# {n.kind}, solid={n.solid}, unicode={n.unicode}, extract op {n.op_extract}, setdir op {n.op_setdir}')
        for p, off in n.files():
            print(off, p)
    else:
        pre = [p.replace('\\', '/').strip('/') for p in sys.argv[4:]]
        want = (lambda p: any(p.startswith(x) for x in pre)) if pre else None
        print(n.extract(sys.argv[3], want), 'files written')


if __name__ == '__main__':
    main()
