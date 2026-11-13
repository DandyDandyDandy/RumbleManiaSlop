"""Rewrite the build target of every SerializedFile in a UnityFS bundle (or a bare SerializedFile).

    python retarget.py <in> <out> [--target 19]

The Windows player refuses files whose m_TargetPlatform is Switch (38). 19 = StandaloneWindows64.
Only the header field changes; object data is copied as is.
"""
import sys, argparse
import UnityPy
from UnityPy.enums import BuildTarget
from UnityPy.files import SerializedFile, BundleFile

ap = argparse.ArgumentParser()
ap.add_argument('src'); ap.add_argument('dst'); ap.add_argument('--target', type=int, default=19)
a = ap.parse_args()
env = UnityPy.load(a.src)
tgt = BuildTarget(a.target)
n = 0


def walk(f):
    global n
    if isinstance(f, SerializedFile):
        print(f'  {f.name}: {f.target_platform!r} -> {tgt!r}  objects={len(f.objects)} typetree={f._enable_type_tree}')
        f.target_platform = tgt
        f._m_target_platform = int(a.target)   # the field UnityPy actually serialises
        f.mark_changed()
        n += 1
    elif hasattr(f, 'files'):
        for c in f.files.values():
            walk(c)


root = env.file
walk(root)
data = root.save(packer='lz4') if isinstance(root, BundleFile) else root.save()
open(a.dst, 'wb').write(data)
print(f'{n} serialized files retargeted, wrote {len(data)} bytes')
