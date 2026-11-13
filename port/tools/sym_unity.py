"""Resolve UnityPlayer.dll offsets (as printed by BR_HANGDUMP host stacks) to function names with dbghelp and the
PDB of the installed player variation.   python sym_unity.py 0x1f68e22 0xb2898b ...   (or: UnityPlayer.dll+0x...)"""
import os as _os, sys as _sys
_sys.path.insert(0, _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))), 'tools'))
from _env import GAME, REPO, TOOLS, UNITY_EDITOR, W  # noqa: E402,F401
import ctypes, sys, os, glob, hashlib
from ctypes import wintypes

RUN = GAME + r'\UnityPlayer.dll'
VARIATIONS = UNITY_EDITOR + r'\PlaybackEngines\windowsstandalonesupport\Variations'


def find_pdb():
    h = hashlib.md5(open(RUN, 'rb').read()).hexdigest()
    for d in glob.glob(VARIATIONS + r'\win64_player_*il2cpp'):
        dll = os.path.join(d, 'UnityPlayer.dll')
        if os.path.exists(dll) and hashlib.md5(open(dll, 'rb').read()).hexdigest() == h:
            return d
    raise SystemExit('no installed variation matches game/UnityPlayer.dll (set UNITY_EDITOR_DATA to <Unity>/Editor/Data)')


class SYMBOL_INFO(ctypes.Structure):
    _fields_ = [('SizeOfStruct', wintypes.ULONG), ('TypeIndex', wintypes.ULONG), ('Reserved', ctypes.c_uint64 * 2),
                ('Index', wintypes.ULONG), ('Size', wintypes.ULONG), ('ModBase', ctypes.c_uint64), ('Flags', wintypes.ULONG),
                ('Value', ctypes.c_uint64), ('Address', ctypes.c_uint64), ('Register', wintypes.ULONG), ('Scope', wintypes.ULONG),
                ('Tag', wintypes.ULONG), ('NameLen', wintypes.ULONG), ('MaxNameLen', wintypes.ULONG), ('Name', ctypes.c_char * 1024)]


def main():
    d = find_pdb()
    dh = ctypes.WinDLL('dbghelp', use_last_error=True)
    proc = ctypes.c_void_p(0x1234)
    dh.SymSetOptions(0x2)
    dh.SymInitialize.argtypes = [ctypes.c_void_p, ctypes.c_char_p, wintypes.BOOL]
    if not dh.SymInitialize(proc, d.encode(), False):
        raise SystemExit('SymInitialize failed')
    dh.SymLoadModuleEx.restype = ctypes.c_uint64
    dh.SymLoadModuleEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint64,
                                   wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
    base = 0x180000000
    r = dh.SymLoadModuleEx(proc, None, os.path.join(d, 'UnityPlayer.dll').encode(), None, base, 0, None, 0)
    if '-v' in sys.argv:
        print('loaded at', hex(r), ctypes.get_last_error())
    if not r:
        raise SystemExit('SymLoadModuleEx failed')
    dh.SymFromAddr.argtypes = [ctypes.c_void_p, ctypes.c_uint64, ctypes.POINTER(ctypes.c_uint64), ctypes.POINTER(SYMBOL_INFO)]
    for a in sys.argv[1:]:
        if a == '-v':
            continue
        off = int(a.split('+')[-1], 16)
        si = SYMBOL_INFO()
        si.SizeOfStruct = 88
        si.MaxNameLen = 1000
        disp = ctypes.c_uint64()
        ok = dh.SymFromAddr(proc, base + off, ctypes.byref(disp), ctypes.byref(si))
        if not ok and '-v' in sys.argv:
            print('error', ctypes.get_last_error())
        print(f'{off:#x}  {si.Name.decode(errors="replace") if ok else "?"}+{disp.value:#x}')


if __name__ == '__main__':
    main()
