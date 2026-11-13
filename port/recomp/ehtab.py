"""Full reader for the Itanium C++ exception tables of an NSO module: every FDE of .eh_frame with its LSDA and the
LSDA's call-site table (start, length, landing pad, action).

Extends the landing-pad reader of xc2-recomp recomp/jumptables.py (`landing_pads`, MIT, Copyright (c) 2026 Peiikai;
that one keeps only {pad: ranges}); the pointer-encoding helpers are imported from it unchanged.
"""
from jumptables import _enc, _sleb, _uleb  # noqa: F401  (upstream helpers)


class Fde:
    __slots__ = ('start', 'end', 'lsda', 'sites')

    def __init__(self, start, end, lsda, sites):
        self.start = start    # absolute guest address of the function
        self.end = end
        self.lsda = lsda      # absolute guest address of the LSDA, 0 if none
        self.sites = sites    # [(start, end, pad or 0, action)] absolute, sorted by start


def read(mod):
    """[Fde] for every FDE of mod (a recomp Module), sorted by start. Zero-length FDEs are dropped."""
    img, hdr, base = mod.image, mod.nso.eh_start, mod.base
    out = []
    if not hdr or hdr >= len(img):
        return out
    o, _ = _enc(img, hdr + 4, img[hdr + 1])
    cies = {}
    while o + 8 <= len(img):
        length = int.from_bytes(img[o:o + 4], 'little')
        if length in (0, 0xFFFFFFFF):
            break
        nxt, cid = o + 4 + length, int.from_bytes(img[o + 4:o + 8], 'little')
        if cid == 0:
            p = o + 9
            aug = img[p:img.index(0, p)].decode('latin-1')
            p += len(aug) + 1
            _, p = _uleb(img, p)
            _, p = _sleb(img, p)
            p = p + 1 if img[o + 8] == 1 else _uleb(img, p)[1]
            info = {'R': 0, 'L': None}
            if aug.startswith('z'):
                _, p = _uleb(img, p)
                for ch in aug[1:]:
                    if ch == 'P':
                        _, p = _enc(img, p + 1, img[p])
                    elif ch in 'LR':
                        info[ch] = img[p]
                        p += 1
            cies[o] = info
        else:
            cie = cies.get(o + 4 - cid)
            if cie is not None:
                start, p = _enc(img, o + 8, cie['R'])
                size, p = _enc(img, p, cie['R'] & 0x0F)
                lsda, sites = 0, []
                if cie['L'] is not None:
                    _, p = _uleb(img, p)
                    lsda, _ = _enc(img, p, cie['L'])
                    if lsda:
                        sites = _sites(img, lsda, start, base)
                if size:
                    out.append(Fde(base + start, base + start + size, base + lsda if lsda else 0, sites))
        o = nxt
    out.sort(key=lambda f: f.start)
    return out


def _sites(img, o, func, base):
    lp_enc = img[o]
    lpstart, o = _enc(img, o + 1, lp_enc)
    if lp_enc == 0xFF:
        lpstart = func
    tt_enc = img[o]
    o += 1
    if tt_enc != 0xFF:
        _, o = _uleb(img, o)
    cs_enc = img[o]
    n, o = _uleb(img, o + 1)
    stop = o + n
    sites = []
    while o < stop:
        s, o = _enc(img, o, cs_enc & 0x0F)
        ln, o = _enc(img, o, cs_enc & 0x0F)
        lp, o = _enc(img, o, cs_enc & 0x0F)
        action, o = _uleb(img, o)
        sites.append((base + func + s, base + func + s + ln, base + lpstart + lp if lp else 0, action))
    sites.sort()
    return sites
