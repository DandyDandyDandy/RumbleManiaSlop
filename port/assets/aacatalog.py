"""aacatalog.py - read and extend an Addressables catalog (catalog.json, the JSON format of Addressables 1.x).

The catalog holds four base64 blobs:
  m_KeyDataString     int count; per key: type byte (0 ASCII string, 1 UTF-16 string, 4 int32, ...) + value
  m_BucketDataString  int count; per bucket (one per key): int offset of the key in the key data, int n, n entry indices
  m_EntryDataString   int count; per entry 7 ints: internal id index, provider index, dependency key index (-1 none),
                      dependency hash, extra-data offset (-1 none), primary key index, resource type index
  m_ExtraDataString   serialized objects (for bundles: a JSON AssetBundleRequestOptions), addressed by byte offset
A location (entry) is found under each of its keys (address, GUID, ...). A bundled asset's entry depends on a key
whose bucket lists the bundle entries to load (its own bundle first, then the bundles it depends on).
"""
import base64, json, struct

class Catalog:
    def __init__(self, path):
        self.j = json.load(open(path, encoding='utf-8'))
        j = self.j
        self.ids = j['m_InternalIds']
        kd = base64.b64decode(j['m_KeyDataString'])
        bd = base64.b64decode(j['m_BucketDataString'])
        ed = base64.b64decode(j['m_EntryDataString'])
        self.extra = bytearray(base64.b64decode(j['m_ExtraDataString']))
        n = struct.unpack_from('<i', bd, 0)[0]
        self.keys, self.buckets = [], []
        p = 4
        for _ in range(n):
            off, cnt = struct.unpack_from('<2i', bd, p); p += 8
            self.buckets.append(list(struct.unpack_from('<%di' % cnt, bd, p))); p += 4 * cnt
            self.keys.append(self._read_key(kd, off))
        n = struct.unpack_from('<i', ed, 0)[0]
        self.entries = [list(struct.unpack_from('<7i', ed, 4 + 28 * i)) for i in range(n)]
        self.key_index = {}
        for i, k in enumerate(self.keys):
            self.key_index.setdefault(k, i)

    @staticmethod
    def _read_key(kd, off):
        t = kd[off]
        if t == 0:
            n = struct.unpack_from('<i', kd, off + 1)[0]
            return kd[off + 5:off + 5 + n].decode('ascii')
        if t == 1:
            n = struct.unpack_from('<i', kd, off + 1)[0]
            return kd[off + 5:off + 5 + n].decode('utf-16-le')
        if t == 4:
            return struct.unpack_from('<i', kd, off + 1)[0]
        if t == 3:
            return struct.unpack_from('<I', kd, off + 1)[0]
        if t == 2:
            return struct.unpack_from('<H', kd, off + 1)[0]
        raise ValueError('key type %d' % t)

    # ---- queries
    def locations(self, key):
        """entries under a key -> list of dicts"""
        if key not in self.key_index:
            return []
        return [self.entry(i) for i in self.buckets[self.key_index[key]]]

    def entry(self, i):
        iid, prov, dep, dephash, data, pk, rt = self.entries[i]
        return dict(index=i, id=self.ids[iid], provider=self.j['m_ProviderIds'][prov], dep=dep, dephash=dephash, data=data,
                    primary=self.keys[pk], rtype=self.j['m_resourceTypes'][rt]['m_ClassName'], rt=rt, prov=prov)

    def extra_json(self, off):
        """the JSON object stored at an extra-data offset (type 7: assembly name, class name, UTF-16 JSON)"""
        d = self.extra
        assert d[off] == 7, d[off]
        p = off + 1
        n = d[p]; asm = bytes(d[p + 1:p + 1 + n]).decode('ascii'); p += 1 + n
        n = d[p]; cls = bytes(d[p + 1:p + 1 + n]).decode('ascii'); p += 1 + n
        n = struct.unpack_from('<i', d, p)[0]; p += 4
        return asm, cls, json.loads(bytes(d[p:p + n]).decode('utf-16-le'))

    # ---- additions
    def add_extra_json(self, asm, cls, obj):
        off = len(self.extra)
        js = json.dumps(obj, separators=(',', ':')).encode('utf-16-le')
        self.extra += bytes([7, len(asm)]) + asm.encode('ascii') + bytes([len(cls)]) + cls.encode('ascii') + struct.pack('<i', len(js)) + js
        return off

    def add_key(self, key):
        if key in self.key_index:
            return self.key_index[key]
        self.keys.append(key); self.buckets.append([])
        self.key_index[key] = len(self.keys) - 1
        return len(self.keys) - 1

    def add_id(self, internal_id):
        self.ids.append(internal_id)
        return len(self.ids) - 1

    def add_entry(self, internal_id, prov, dep_key, data, primary_key, rt, keys):
        """new location, listed under each of `keys` (and it must include the primary key); dep_key: key or None"""
        dep = self.add_key(dep_key) if dep_key is not None else -1
        dephash = 0 if dep_key is None else (hash(dep_key) & 0x7fffffff)
        pk = self.add_key(primary_key)
        self.entries.append([self.add_id(internal_id), prov, dep, dephash, data, pk, rt])
        e = len(self.entries) - 1
        for k in keys:
            self.buckets[self.add_key(k)].append(e)
        return e

    def save(self, path):
        kd = bytearray(struct.pack('<i', len(self.keys)))
        offs = []
        for k in self.keys:
            offs.append(len(kd))
            if isinstance(k, int):
                kd += b'\x04' + struct.pack('<i', k)
            else:
                try:
                    b = k.encode('ascii'); kd += b'\x00' + struct.pack('<i', len(b)) + b
                except UnicodeEncodeError:
                    b = k.encode('utf-16-le'); kd += b'\x01' + struct.pack('<i', len(b)) + b
        bd = bytearray(struct.pack('<i', len(self.keys)))
        for off, b in zip(offs, self.buckets):
            bd += struct.pack('<2i', off, len(b)) + struct.pack('<%di' % len(b), *b)
        ed = bytearray(struct.pack('<i', len(self.entries)))
        for e in self.entries:
            ed += struct.pack('<7i', *e)
        j = self.j
        j['m_KeyDataString'] = base64.b64encode(bytes(kd)).decode('ascii')
        j['m_BucketDataString'] = base64.b64encode(bytes(bd)).decode('ascii')
        j['m_EntryDataString'] = base64.b64encode(bytes(ed)).decode('ascii')
        j['m_ExtraDataString'] = base64.b64encode(bytes(self.extra)).decode('ascii')
        json.dump(j, open(path, 'w', encoding='utf-8'), separators=(',', ':'))

if __name__ == '__main__':
    import sys
    c = Catalog(sys.argv[1])
    print(len(c.keys), 'keys,', len(c.entries), 'entries,', len(c.ids), 'internal ids')
    for k in sys.argv[2:]:
        for loc in c.locations(k):
            print(k, '->', loc)
            if loc['dep'] >= 0:
                for d in c.buckets[loc['dep']]:
                    e = c.entry(d); print('     dep', e['id'], e['provider'], e['data'] >= 0 and c.extra_json(e['data'])[2])
