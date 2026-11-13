"""Print video/audio header info for CRI .usm files (codec, size, fps).  python usm_info.py <dir or file>..."""
import os, struct, sys


def utf_rows(b):
    assert b[:4] == b'@UTF', b[:4]
    b = b[8:]
    rows_off, str_off, data_off, name_off, ncol, row_w, nrow = struct.unpack_from('>HIIIHHI', b, 2) if False else (None,) * 7
    enc, rows_off, str_off, data_off, name_off, ncol, row_w, nrow = struct.unpack_from('>HHIIIHHI', b, 0)

    def s(o):
        e = b.index(b'\0', str_off + o)
        return b[str_off + o:e].decode('utf-8', 'replace')
    FM = {0: '>B', 1: '>b', 2: '>H', 3: '>h', 4: '>I', 5: '>i', 6: '>Q', 7: '>q', 8: '>f', 9: '>d'}
    p = 24
    cols = []
    for _ in range(ncol):
        fl = b[p]; nm = s(struct.unpack_from('>I', b, p + 1)[0]); p += 5
        st, ty = fl >> 4, fl & 15
        const = None
        if st & 2 and not st & 4:  # constant column (0x30) -> value follows
            const, p = rd(b, p, ty, FM, s)
        cols.append((nm, st, ty, const))
    out = []
    for r in range(nrow):
        q = rows_off + r * row_w
        row = {}
        for nm, st, ty, const in cols:
            if st & 4:
                row[nm], q = rd(b, q, ty, FM, s)
            else:
                row[nm] = const
        out.append(row)
    return out


def rd(b, p, ty, FM, s):
    if ty in FM:
        f = FM[ty]
        return struct.unpack_from(f, b, p)[0], p + struct.calcsize(f)
    if ty == 0xA:
        return s(struct.unpack_from('>I', b, p)[0]), p + 4
    if ty == 0xB:
        return '<data>', p + 8
    raise ValueError(ty)


def info(path):
    res = {}
    with open(path, 'rb') as f:
        for _ in range(64):
            h = f.read(0x20)
            if len(h) < 0x20:
                break
            sig = h[:4]
            size = struct.unpack_from('>I', h, 4)[0]
            off, pad = h[9], struct.unpack_from('>H', h, 10)[0]
            typ = h[15] & 3
            body = h[8:] + f.read(size - 0x18)
            payload = body[off:len(body) - pad]
            if typ == 1 and payload[:4] == b'@UTF' and sig in (b'@SFV', b'@SFA', b'@ALP'):
                try:
                    res[sig.decode() + str(h[12])] = utf_rows(payload)[0]
                except Exception as e:
                    res[sig.decode()] = 'ERR ' + str(e)
            if typ == 0 and sig == b'@SFV':
                break
    return res


CODEC = {1: 'Sofdec.Prime (MPEG)', 5: 'H.264', 9: 'VP9'}
if __name__ == '__main__':
    files = []
    for a in sys.argv[1:]:
        if os.path.isdir(a):
            files += [os.path.join(r, f) for r, _, fs in os.walk(a) for f in fs if f.lower().endswith('.usm')]
        else:
            files.append(a)
    for p in sorted(files):
        r = info(p)
        parts = []
        for k, v in r.items():
            if isinstance(v, dict) and k.startswith(('@SFV', '@ALP')):
                parts.append(f"{k}: codec={CODEC.get(v.get('mpeg_codec'), v.get('mpeg_codec'))} {v.get('width')}x{v.get('height')} fps={v.get('framerate_n', 0) / max(v.get('framerate_d', 1), 1):.2f} frames={v.get('total_frames')}")
            elif isinstance(v, dict):
                parts.append(f"{k}: audio_codec={v.get('audio_codec')} ch={v.get('num_channels')} rate={v.get('sampling_rate')}")
            else:
                parts.append(f'{k}: {v}')
        print(os.path.basename(p), os.path.getsize(p) >> 20, 'MB |', ' | '.join(parts))
