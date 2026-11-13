"""Minimal global-metadata.dat v29 reader (images, types, methods, fields, string literals)."""
import struct, sys

SECTIONS = ['stringLiteral', 'stringLiteralData', 'string', 'events', 'properties', 'methods',
            'parameterDefaultValues', 'fieldDefaultValues', 'fieldAndParameterDefaultValueData',
            'fieldMarshaledSizes', 'parameters', 'fields', 'genericParameters',
            'genericParameterConstraints', 'genericContainers', 'nestedTypes', 'interfaces',
            'vtableMethods', 'interfaceOffsets', 'typeDefinitions', 'images', 'assemblies',
            'fieldRefs', 'referencedAssemblies', 'attributeData', 'attributeDataRange',
            'unresolvedVirtualCallParameterTypes', 'unresolvedVirtualCallParameterRanges',
            'windowsRuntimeTypeNames', 'windowsRuntimeStrings', 'exportedTypeDefinitions']


class Meta:
    def __init__(self, path):
        d = self.d = open(path, 'rb').read()
        magic, ver = struct.unpack_from('<II', d, 0)
        assert magic == 0xFAB11BAF and ver == 29, (hex(magic), ver)
        self.sec = {}
        for i, n in enumerate(SECTIONS):
            self.sec[n] = struct.unpack_from('<II', d, 8 + 8 * i)
        so = self.sec['string'][0]
        self._so = so
        o, s = self.sec['images']
        self.images = []
        for i in range(s // 40):
            ni, ai, ts, tc = struct.unpack_from('<IiiI', d, o + 40 * i)
            self.images.append(dict(name=self.s(ni), typeStart=ts, typeCount=tc))
        o, s = self.sec['typeDefinitions']
        self.types = []
        for i in range(s // 88):
            v = struct.unpack_from('<16i8H2I', d, o + 88 * i)
            self.types.append(dict(index=i, name=self.s(v[0]), ns=self.s(v[1]), declaring=v[3], parent=v[4],
                                   flags=v[7] & 0xffffffff, fieldStart=v[8], methodStart=v[9],
                                   method_count=v[16], field_count=v[18]))
        o, s = self.sec['methods']
        self.mo, self.nmethods = o, s // 32
        o, s = self.sec['fields']
        self.fo, self.nfields = o, s // 12
        for im in self.images:
            for t in self.types[im['typeStart']:im['typeStart'] + im['typeCount']]:
                t['image'] = im['name']

    def s(self, idx):
        p = self._so + idx
        e = self.d.index(b'\0', p)
        return self.d[p:e].decode('utf-8', 'replace')

    def method(self, i):
        ni, dt, rt, ps, gc, tok, fl, ifl, slot, pc = struct.unpack_from('<IiiiiIHHHH', self.d, self.mo + 32 * i)
        return dict(index=i, name=self.s(ni), declaring=dt, flags=fl, iflags=ifl, token=tok, pcount=pc)

    def field(self, i):
        ni, ti, tok = struct.unpack_from('<IiI', self.d, self.fo + 12 * i)
        return dict(index=i, name=self.s(ni), type=ti)

    def methods_of(self, t):
        return [self.method(i) for i in range(t['methodStart'], t['methodStart'] + t['method_count'])]

    def fields_of(self, t):
        return [self.field(i) for i in range(t['fieldStart'], t['fieldStart'] + t['field_count'])]

    def fullname(self, t):
        n = t['name']
        while t['declaring'] != -1 and False:
            pass
        return (t['ns'] + '.' if t['ns'] else '') + n

    def literals(self):
        o, s = self.sec['stringLiteral']
        do = self.sec['stringLiteralData'][0]
        for i in range(s // 8):
            ln, di = struct.unpack_from('<Ii', self.d, o + 8 * i)
            yield i, self.d[do + di:do + di + ln].decode('utf-8', 'replace')


if __name__ == '__main__':
    m = Meta(sys.argv[1])
    cmd = sys.argv[2]
    if cmd == 'images':
        for im in m.images:
            print(im['name'], im['typeCount'])
    elif cmd == 'image':
        for t in m.types:
            if t.get('image') == sys.argv[3]:
                print('TYPE', t['index'], m.fullname(t), 'flags=%x' % t['flags'])
                for f in m.fields_of(t):
                    print('   F', f['name'])
                for me in m.methods_of(t):
                    print('   M', me['index'], me['name'], 'fl=%04x ifl=%04x pc=%d' % (me['flags'], me['iflags'], me['pcount']))
    elif cmd == 'lits':
        for i, s in m.literals():
            print(i, repr(s))
