"""Object type census of a bundle tree (checks that every bundle loads and what shader-like types exist).

    python scan_types.py <tree> [jobs]
"""
import collections
import os
import sys
from concurrent.futures import ProcessPoolExecutor

import UnityPy


def one(path):
    try:
        env = UnityPy.load(path)
        return path, collections.Counter(o.type.name for o in env.objects), None
    except Exception as e:
        return path, collections.Counter(), repr(e)[:200]


def main():
    files = []
    for r, _, fs in os.walk(sys.argv[1]):
        files += [os.path.join(r, f) for f in fs if f.endswith('.bundle')]
    tot = collections.Counter()
    empty, errors, holders = [], [], collections.Counter()
    with ProcessPoolExecutor(int(sys.argv[2]) if len(sys.argv) > 2 else 8) as ex:
        for path, c, err in ex.map(one, files, chunksize=32):
            tot.update(c)
            for k in c:
                holders[k] += 1
            if err:
                errors.append((path, err))
            elif not c:
                empty.append(path)
    print(f'{len(files)} bundles, {len(errors)} load errors, {len(empty)} with no objects, {sum(tot.values())} objects')
    for k in ('Shader', 'ComputeShader', 'ShaderVariantCollection', 'Material', 'RayTracingShader'):
        print(f'  {k}: {tot[k]} objects in {holders[k]} bundles')
    for p, e in errors[:10]:
        print('  error', p, e)
    for p in empty[:10]:
        print('  empty', p)


if __name__ == '__main__':
    main()
