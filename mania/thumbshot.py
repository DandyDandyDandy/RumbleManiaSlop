"""Pictures of imported stages taken in the game itself, for Select Stage.

The editor's "From the view" keeps the point of view of its 3D view with the stage (overrides.json, "view": eye,
point looked at, vertical field of view of the square picture; stage coordinates). The import then lets the game
draw the stage from there, with the game's lighting and the stage's background: for every such stage the built
game is started on the test save (profile "T", a copy of the save made on first use; the real save is not touched),
sent from its title straight into the stage (the test switch BR_BOOT_STAGE), told to show that view with nothing else on the screen
(BR_THUMB_VIEW, port\\runtime\\thumb.c), and its window is photographed. One stage takes about half a minute
(a minute and a quarter while the menus were walked); up to INSTANCES copies of the game run side by side, each with its own test save ("T", "T1", ...), log
and input file. A picture is kept (build\\mania_views) and only taken again when the view changes or with build.py --retake.

    python thumbshot.py st<Mania stage number> <ex> <ey> <ez> <tx> <ty> <tz> [<fov>] [--out FILE]      one picture, as a test
"""
import ctypes
import ctypes.wintypes as wt
import hashlib
import math
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'port'))
import paths  # noqa: E402

FOV = 2 * math.degrees(0.4)     # the editor's 3D view (editor.html, updateMvp)
SIZE = 512                      # the kept picture is a square of this size
EXE = paths.NAME + '.exe'
DIR = paths.BUILD / 'mania_views'
INSTANCES = 3                   # copies of the game taking pictures at the same time


def view_key(view):
    return hashlib.md5(('view ' + ' '.join(f'{x:.4f}' for x in view)).encode()).hexdigest()[:12]


def kept(sid, view):
    """Where the picture of this view of the stage is kept (whether it is there or not)."""
    return str(DIR / f'st{sid}_{view_key(view)}.png')


def camera(view):
    """BR_THUMB_VIEW for a view: the point looked at, the distance, pitch and turn in degrees, the field of view."""
    e, t = view[:3], view[3:6]
    d = [a - b for a, b in zip(e, t)]
    dist = math.sqrt(sum(x * x for x in d)) or 1.0
    pitch = math.degrees(math.asin(max(-1.0, min(1.0, d[1] / dist))))
    turn = math.degrees(math.atan2(d[0], d[2]))
    fov = view[6] if len(view) > 6 else FOV
    return ','.join(f'{x:.4f}' for x in (*t, dist, pitch, turn, fov))


def game_runs():
    r = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {EXE}', '/NH'], capture_output=True, text=True)
    return EXE.lower() in r.stdout.lower()


def window_of(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def each(hwnd, _):
        p = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(p))
        if p.value == pid and ctypes.windll.user32.IsWindowVisible(hwnd) and ctypes.windll.user32.GetWindowTextLengthW(hwnd):
            found.append(hwnd)
        return True
    ctypes.windll.user32.EnumWindows(each, 0)
    return found[0] if found else None


def photograph(pid):
    """The inside of the game's window as an image (the window's own content: other windows over it do not show),
    or None."""
    from PIL import Image
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    for f in (u.GetDC, u.GetWindowDC, g.CreateCompatibleDC, g.CreateCompatibleBitmap, g.SelectObject):
        f.restype = ctypes.c_void_p
    # This process must stay as it is about display scaling (python.exe does not declare itself aware of it):
    # declared aware, it gets the window's size in real pixels but its content in the game's, smaller, units.
    hwnd = window_of(pid)
    if not hwnd:
        return None
    wr, cr, pt = wt.RECT(), wt.RECT(), wt.POINT(0, 0)
    u.GetWindowRect(hwnd, ctypes.byref(wr))
    u.GetClientRect(hwnd, ctypes.byref(cr))
    u.ClientToScreen(hwnd, ctypes.byref(pt))
    w, h = wr.right - wr.left, wr.bottom - wr.top
    if w <= 0 or h <= 0 or cr.right <= 0 or cr.bottom <= 0:
        return None
    screen = u.GetDC(None)
    dc = g.CreateCompatibleDC(ctypes.c_void_p(screen))
    bmp = g.CreateCompatibleBitmap(ctypes.c_void_p(screen), w, h)
    old = g.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(bmp))
    ok = u.PrintWindow(wt.HWND(hwnd), ctypes.c_void_p(dc), 2)          # PW_RENDERFULLCONTENT
    head = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xffffffff, 1 | 32 << 16, 0, 0, 0, 0, 0, 0)     # BITMAPINFOHEADER, top-down 32 bit
    buf = ctypes.create_string_buffer(w * h * 4)
    got = g.GetDIBits(ctypes.c_void_p(dc), ctypes.c_void_p(bmp), 0, h, buf, head, 0)
    g.SelectObject(ctypes.c_void_p(dc), ctypes.c_void_p(old))
    g.DeleteObject(ctypes.c_void_p(bmp))
    g.DeleteDC(ctypes.c_void_p(dc))
    u.ReleaseDC(None, ctypes.c_void_p(screen))
    if not ok or not got:
        return None
    img = Image.frombuffer('RGBA', (w, h), buf, 'raw', 'BGRA', 0, 1).convert('RGB')
    x, y = pt.x - wr.left, pt.y - wr.top
    return img.crop((x, y, x + cr.right, y + cr.bottom))


def square(img):
    """The middle square of the window picture (what the editor's "From the view" shows), in the kept size."""
    from PIL import Image
    s = min(img.size)
    x, y = (img.width - s) // 2, (img.height - s) // 2
    return img.crop((x, y, x + s, y + s)).resize((SIZE, SIZE), Image.LANCZOS)


def place(game, sid):
    """(course number, stage number) of a stage in the Mania tab, from the import's stage list, or None."""
    try:
        for line in open(os.path.join(game, 'mania', 'mania_stages.txt'), encoding='utf-8'):
            f = line.rstrip('\n').split('\t')
            if len(f) > 2 and f[2] == f'st{sid}':
                return int(f[0]), int(f[1])
    except OSError:
        pass
    return None


def course_id(game, course):
    """The Course.eID of the import's course number `course` (the 4th number of its line in mania_courses.txt)."""
    k = 0
    for line in open(os.path.join(game, 'mania', 'mania_courses.txt'), encoding='utf-8'):
        f = line.split()
        if len(f) >= 4 and f[0].isdigit():
            if k == course:
                return int(f[3])
            k += 1
    return None


def take(sid, view, out, say=print, game=None, slot=0):
    """Start the game, go into the stage, take the picture of `view` and write it to `out`. Returns None, or what
    went wrong. The game must not be running, except other copies started by take() with another `slot`."""
    game = game or str(paths.GAME)
    where = place(game, sid)
    if where is None:
        return 'the stage is not in the game'
    course, stage = where
    cid = course_id(game, course)
    if cid is None:
        return "the stage's world is not in mania_courses.txt"
    work = str(DIR)
    os.makedirs(work, exist_ok=True)
    tag = str(slot or '')                                    # slot 0 keeps the names of a single copy
    profile = 'T' + tag
    if not os.path.isdir(os.path.join(game, 'save' + profile)) and os.path.isdir(os.path.join(game, 'save')):
        shutil.copytree(os.path.join(game, 'save'), os.path.join(game, 'save' + profile))
    live, log = os.path.join(work, f'live{tag}.txt'), os.path.join(game, f'port{tag}.log')
    open(live, 'w').close()
    for f in (f'port{tag}.log', f'player{tag}.log'):
        try:
            os.remove(os.path.join(game, f))
        except OSError:
            pass
    env = dict(os.environ, BR_PROFILE=profile, BR_LOG=f'port{tag}.log', BR_INPUT_LIVE=live, BR_STATE_LOG='1', BR_NO_REAL_INPUT='1', BR_AUDIO='off',
               BR_THUMB_VIEW=camera(view), BR_BOOT_STAGE=f'{cid} {stage}')
    p = subprocess.Popen([os.path.join(game, EXE), '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720',
                          '-logFile', f'player{tag}.log'], cwd=game, env=env)

    def logged(*texts):
        try:
            s = open(log, encoding='utf-8', errors='replace').read()
        except OSError:
            return None
        return next((t for t in texts if t in s), None)

    def wait(seconds, *texts):
        t0 = time.time()
        while time.time() - t0 < seconds and p.poll() is None:
            hit = logged(*texts)
            if hit:
                return hit
            time.sleep(0.25)
        return None

    error = None
    try:
        if wait(90, 'test: BR_BOOT_STAGE: course', 'FATAL') != 'test: BR_BOOT_STAGE: course':   # the title hands over
            return 'the game closed' if p.poll() is not None else 'the game did not reach its title'
        hit = wait(90, 'thumb: ready', 'thumb: failed', 'FATAL')
        if hit != 'thumb: ready':
            return 'the game closed' if p.poll() is not None else 'the stage did not start' if hit is None else hit
        time.sleep(0.5)
        img = photograph(p.pid)
        if img is None:
            return 'the window could not be photographed'
        square(img).save(out + '.tmp', 'PNG')
        os.replace(out + '.tmp', out)
        say(f'  st{sid}: picture taken in the game')
    finally:
        if p.poll() is None:
            p.kill()
            try:
                p.wait(10)
            except subprocess.TimeoutExpired:
                pass
    return error


def take_all(views, say=print, game=None):
    """views: {stage id: view}. Takes the pictures that are not kept yet, INSTANCES at a time; returns the number taken."""
    import concurrent.futures
    import queue
    import threading
    todo = {sid: v for sid, v in views.items() if not os.path.exists(kept(sid, v))}
    if not todo:
        return 0
    if game_runs():
        say(f'  {len(todo)} stage pictures are to be taken in the game, but the game is running: close it and import again '
            '(until then the stages show the editor\'s picture)')
        return 0
    n = min(INSTANCES, len(todo))
    say(f'Taking {len(todo)} stage picture{"s" if len(todo) > 1 else ""} in the game, {n} at a time (about a minute and a '
        'quarter each; the game windows open by themselves, leave them alone)')
    slots, lock, done = queue.Queue(), threading.Lock(), [0]
    for i in range(n):
        slots.put(i)

    def one(sid, v):
        slot = slots.get()
        try:
            time.sleep(4 * slot if done[0] == 0 else 0)     # the first starts a little apart
            err = take(sid, v, kept(sid, v), say, game, slot)
        finally:
            slots.put(slot)
        with lock:
            if err:
                say(f'  st{sid}: no picture from the game ({err}); the editor\'s picture is shown')
                return
            done[0] += 1
            for name in os.listdir(str(DIR)):               # the stage's pictures of earlier views
                if name.startswith(f'st{sid}_') and name != os.path.basename(kept(sid, v)):
                    os.remove(os.path.join(str(DIR), name))

    with concurrent.futures.ThreadPoolExecutor(n) as pool:
        for f in [pool.submit(one, sid, v) for sid, v in sorted(todo.items())]:
            f.result()
    subprocess.run(['taskkill', '/F', '/IM', 'UnityCrashHandler64.exe'], capture_output=True)
    return done[0]


if __name__ == '__main__':
    args = sys.argv[1:]
    out = None
    if '--out' in args:
        i = args.index('--out')
        out = args[i + 1]
        del args[i:i + 2]
    if len(args) not in (7, 8) or not args[0].startswith('st'):
        sys.exit(__doc__)
    sid, view = int(args[0][2:]), [float(x) for x in args[1:]]
    if len(view) == 6:
        view.append(FOV)
    if game_runs():
        sys.exit('the game is running')
    os.makedirs(str(DIR), exist_ok=True)
    err = take(sid, view, out or kept(sid, view))
    sys.exit(err)
