"""Download and unpack the build tools into build\\toolchain. Nothing is installed on the PC and no downloaded
installer is run: archives are unpacked by Python.

    python fetch.py [name ...]        all tools, or the named ones (llvm ninja unity spirv-tools)

    llvm         llvm-mingw (clang, lld): compiles the recompiled game code           https://github.com/mstorsjo/llvm-mingw
    ninja        the build runner                                                    https://ninja-build.org
    unity        the Windows IL2CPP player of Unity 2022.3.30f1, from Unity's download server (the files are taken
                 out of the "Windows Build Support (IL2CPP)" installer; see nsis.py)
    spirv-tools  spirv-val / spirv-opt for the shader conversion (optional: without them the converted shaders are
                 neither validated nor optimised)                                     https://github.com/KhronosGroup/SPIRV-Tools

Every download is checked against a pinned SHA-256. Files already in build\\downloads are reused, so a download can
also be placed there by hand. Environment variables in port\\paths.py point the build at tools that are already on
the PC instead (LLVM_BIN, NINJA, UNITY_PLAYER, SPIRV_TOOLS_BIN).
"""
import hashlib
import io
import os
import shutil
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'port'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

UNITY_VARIATION = 'Variations/win64_player_nondevelopment_il2cpp/'

ITEMS = {
    'llvm': dict(
        url='https://github.com/mstorsjo/llvm-mingw/releases/download/20261104/llvm-mingw-20261104-ucrt-x86_64.zip',
        sha256='552191b5754c49a5a20723276a6fc56541ea1922c4c50b7b669022333fc1b40f', size=191,
        dest='llvm', check='bin/clang.exe'),
    'ninja': dict(
        url='https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-win.zip',
        sha256='07fc8261b42b20e71d1720b39068c2e14ffcee6396b76fb7a795fb460b78dc65', size=1,
        dest='ninja', check='ninja.exe'),
    'unity': dict(
        url='https://download.unity3d.com/download_unity/70558241b701/TargetSupportInstaller/'
            'UnitySetup-Windows-IL2CPP-Support-for-Editor-2022.3.30f1.exe',
        sha256='a24444d45762c4a0c44a9041100844cc433b90a23f8d8231b0ba16dd08c8fa3e', size=101,
        dest='unity', check=UNITY_VARIATION + 'UnityPlayer.dll'),
    'spirv-tools': dict(
        url='https://conda.anaconda.org/conda-forge/win-64/spirv-tools-2026.4-h49e36cd_2.conda',
        sha256='933e40fe9ca887a63ef742260f0ed801cda317354806504d864764a4ed9749e1', size=2,
        dest='spirv-tools', check='Library/bin/spirv-val.exe', optional=True),
}


def log(msg):
    print(msg, flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(1 << 22), b''):
            h.update(b)
    return h.hexdigest()


def download(name, item):
    paths.DOWNLOADS.mkdir(parents=True, exist_ok=True)
    dst = paths.DOWNLOADS / item['url'].rsplit('/', 1)[1]
    if dst.exists() and sha256(dst) == item['sha256']:
        return dst
    log(f'  downloading {name} (about {item["size"]} MB): {item["url"]}')
    tmp = dst.with_suffix(dst.suffix + '.part')
    req = urllib.request.Request(item['url'], headers={'User-Agent': 'setup'})
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, 'wb') as f:
        total = int(r.headers.get('Content-Length') or 0)
        done, last = 0, -1
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
            done += len(b)
            pct = done * 100 // total if total else 0
            if pct // 10 != last:
                last = pct // 10
                log(f'    {pct}%')
    got = sha256(tmp)
    if got != item['sha256']:
        tmp.unlink()
        raise SystemExit(f'{name}: the download does not have the expected SHA-256 (got {got}).\n'
                         f'Try again; if it keeps failing the file at {item["url"]} has changed.')
    os.replace(tmp, dst)
    return dst


def unzip(src, dest, strip_top=False):
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            name = info.filename
            if strip_top:
                name = name.split('/', 1)[1] if '/' in name else ''
            if not name or name.endswith('/'):
                continue
            out = (dest / name).resolve()
            if dest.resolve() not in out.parents:
                raise SystemExit(f'unsafe path in {src.name}: {info.filename}')
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as i, open(out, 'wb') as o:
                shutil.copyfileobj(i, o, 1 << 20)


def unpack_llvm(src, dest):
    unzip(src, dest, strip_top=True)


def unpack_ninja(src, dest):
    unzip(src, dest)


def unpack_unity(src, dest):
    import nsis
    n = nsis.Nsis(str(src))
    count = n.extract(str(dest), lambda p: p.startswith(UNITY_VARIATION) and '/Data/Managed/' not in p
                      and not p.endswith(('.pdb', '.lib')))
    if count < 5:
        raise SystemExit('unity: the player files were not found in the installer')


def unpack_spirv(src, dest):
    """A .conda package is a zip holding pkg-*.tar.zst."""
    try:
        import zstandard
    except ImportError:
        raise RuntimeError('the Python package "zstandard" is not installed') from None
    with zipfile.ZipFile(src) as z:
        inner = [n for n in z.namelist() if n.startswith('pkg-') and n.endswith('.tar.zst')][0]
        data = zstandard.ZstdDecompressor().decompress(z.read(inner), max_output_size=1 << 30)
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            if m.isfile() and m.name.startswith('Library/bin/'):
                out = (dest / m.name).resolve()
                if dest.resolve() not in out.parents:
                    raise RuntimeError('unsafe path in the package')
                out.parent.mkdir(parents=True, exist_ok=True)
                with t.extractfile(m) as i, open(out, 'wb') as o:
                    shutil.copyfileobj(i, o)


UNPACK = {'llvm': unpack_llvm, 'ninja': unpack_ninja, 'unity': unpack_unity, 'spirv-tools': unpack_spirv}
ENV = {'llvm': 'LLVM_BIN', 'ninja': 'NINJA', 'unity': 'UNITY_PLAYER', 'spirv-tools': 'SPIRV_TOOLS_BIN'}


def fetch(name):
    item = ITEMS[name]
    if os.environ.get(ENV[name]):
        log(f'  {name}: using {ENV[name]}={os.environ[ENV[name]]}')
        return True
    dest = paths.TOOLCHAIN / item['dest']
    mark = dest / '.ok'
    if mark.exists() and mark.read_text() == item['sha256'] and (dest / item['check']).exists():
        log(f'  {name}: ready')
        return True
    try:
        src = download(name, item)
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        log(f'  unpacking {name}')
        UNPACK[name](src, dest)
        if not (dest / item['check']).exists():
            raise RuntimeError(f'{item["check"]} is missing after unpacking')
    except (RuntimeError, OSError) as e:
        if item.get('optional'):
            log(f'  {name}: not available ({e}); continuing without it')
            return False
        raise SystemExit(f'{name}: {e}') from None
    mark.write_text(item['sha256'])
    log(f'  {name}: ready')
    return True


def main():
    names = sys.argv[1:] or list(ITEMS)
    for n in names:
        if n not in ITEMS:
            sys.exit(f'unknown tool {n!r}; known: {" ".join(ITEMS)}')
        fetch(n)


if __name__ == '__main__':
    main()
