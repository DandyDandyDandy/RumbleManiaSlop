"""Start the built game, walk the menus into one imported stage and take pictures of it (a test aid).

    python try_stage.py <course number> <stage number> [--out DIR] [--hold MS] [--shots S,S,...] [--input "LINE;LINE"]

Course and stage numbers count from 0 in import order (game\\mania\\mania_courses.txt). The run uses the save
profile "T" (game\\saveT, a copy of game\\save made on first use), so the real save is not touched. Buttons are
sent through the port's live input file (BR_INPUT_LIVE); how far the menus are is read from the UI state lines of
port.log (BR_STATE_LOG), because the number of presses the title needs depends on what the save has already seen.
In the stage the stick is held forward for --hold ms. Pictures of the game window are written as
<out>\\c<course>_s<stage>_<n>.png (--shots: seconds after the stage was chosen), and the lines of port.log that
matter are printed. The exit code is 1 when the game was gone at the end.
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'port'))
import paths  # noqa: E402

WORLDS_BEFORE = 2       # entries above the first imported course in Select World on the test save (World 1, locked World 2)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('course', type=int)
    ap.add_argument('stage', type=int)
    ap.add_argument('--out', default=str(paths.BUILD / 'try'))
    ap.add_argument('--hold', type=int, default=6000)
    ap.add_argument('--shots', default='16,22,28')
    ap.add_argument('--before', type=int, default=WORLDS_BEFORE)
    ap.add_argument('--input', help='live input lines sent once the stage has loaded, separated by ;')
    a = ap.parse_args()
    game = str(paths.GAME)
    exe = os.path.join(game, paths.NAME + '.exe')
    os.makedirs(a.out, exist_ok=True)
    if not os.path.isdir(os.path.join(game, 'saveT')) and os.path.isdir(os.path.join(game, 'save')):
        shutil.copytree(os.path.join(game, 'save'), os.path.join(game, 'saveT'))
    live = os.path.join(a.out, 'live.txt')
    open(live, 'w').close()
    log = os.path.join(game, 'port.log')
    subprocess.run(['taskkill', '/F', '/IM', paths.NAME + '.exe'], capture_output=True)
    for f in ('port.log', 'player.log'):
        try:
            os.remove(os.path.join(game, f))
        except OSError:
            pass
    env = dict(os.environ, BR_PROFILE='T', BR_INPUT_LIVE=live, BR_STATE_LOG='1')
    p = subprocess.Popen([exe, '-screen-fullscreen', '0', '-screen-width', '1280', '-screen-height', '720', '-logFile', 'player.log'],
                         cwd=game, env=env)

    def press(*keys, gap=0.9):
        for k in keys:
            with open(live, 'a') as f:
                f.write(k + '\n')
            time.sleep(gap)

    def logged(text):
        try:
            return text in open(log, encoding='utf-8', errors='replace').read()
        except OSError:
            return False

    def shot(tag):
        ps = os.path.join(HERE, '..', '..', 'port', 'tools', 'shot_window.ps1')
        cmd = f"& ([scriptblock]::Create((Get-Content -Raw '{ps}'))) -Out '{os.path.join(a.out, tag)}' -At 0 -Process {paths.NAME} -MaxWidth 960"
        subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, timeout=60)
        src = os.path.join(a.out, tag + '_0.png')
        if os.path.exists(src):
            os.replace(src, os.path.join(a.out, tag + '.png'))

    ok = True
    time.sleep(28)                                       # the title
    t0 = time.time()
    while not logged('UIStateTopMenu requests state 20'):       # A until the main menu has opened Adventure
        if time.time() - t0 > 90 or p.poll() is not None:
            ok = False
            break
        press('A')
        time.sleep(6)
    if ok:
        time.sleep(7)                                    # Select World
        press(*['DOWN'] * (a.before + a.course))
        press('A')
        time.sleep(6)                                    # Select Stage
        press(*['DOWN'] * a.stage)
        press('A')
        tsel = time.time()
        sent = False
        for i, s in enumerate(sorted(int(x) for x in a.shots.split(','))):
            while time.time() - tsel < s:
                if not sent and time.time() - tsel > 17:
                    press(f'LSU {a.hold}', gap=0)
                    for line in (a.input or '').split(';'):
                        if line.strip():
                            press(line.strip(), gap=0.1)
                    sent = True
                time.sleep(0.2)
            shot(f'c{a.course}_s{a.stage}_{i}')
    time.sleep(2)
    alive = p.poll() is None
    subprocess.run(['taskkill', '/F', '/IM', paths.NAME + '.exe'], capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'UnityCrashHandler64.exe'], capture_output=True)
    time.sleep(1)
    print(f'course {a.course} stage {a.stage}: menus {"ok" if ok else "NOT reached"}, the game was {"still running" if alive else "NOT running"} at the end')
    try:
        for line in open(log, encoding='utf-8', errors='replace'):
            if any(k in line for k in ('FATAL', 'mania/scene', 'exception', 'Exception')):
                print('   ' + line.rstrip()[:240])
    except OSError:
        print('   no port.log')
    return 0 if alive and ok else 1


if __name__ == '__main__':
    sys.exit(main())
