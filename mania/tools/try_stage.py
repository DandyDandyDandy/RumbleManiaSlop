"""Start the built game, go into one imported stage and take pictures of it (a test aid).

    python try_stage.py <course number> <stage number> [--out DIR] [--hold MS] [--shots S,S,...] [--input "LINE;LINE"]
    python try_stage.py st<Mania stage number> ...

By default the game goes straight from the title into the stage (the port's test switch BR_BOOT_STAGE: about 25 s
from start to the stage's intro); --menus walks the title, main menu, Select World and Select Stage instead (about
70 s), for tests of those menus.

Course and stage numbers count from 0 in import order (game\\mania\\mania_courses.txt). The run uses the save
profile "T" (game\\saveT, a copy of game\\save made on first use), so the real save is not touched. Buttons are
sent through the port's live input file (BR_INPUT_LIVE); how far the menus are is read from the UI state lines of
port.log (BR_STATE_LOG), because the number of presses the title needs depends on what the save has already seen.
In the stage the stick is held forward for --hold ms, then the --input lines are sent one after the other, each
when the one before has run out ("WAIT <ms>" just waits). Pictures of the game window are written as
<out>\\c<course>_s<stage>_<n>.png (--shots: seconds after the stage was chosen), and the lines of port.log that
matter are printed. The exit code is 1 when the game was gone at the end.
"""
import argparse
import os
import shutil
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'port'))
import paths  # noqa: E402
sys.path.insert(0, os.path.join(HERE, '..'))
import thumbshot  # noqa: E402

WORLDS_BEFORE = 0       # entries above the first imported course in the Mania tab of Select World


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('course', help='course number, or st<Mania stage number> (then no stage number)')
    ap.add_argument('stage', type=int, nargs='?')
    ap.add_argument('--out', default=str(paths.BUILD / 'try'))
    ap.add_argument('--hold', type=int, default=6000)
    ap.add_argument('--shots', default='18,26,34')
    ap.add_argument('--before', type=int, default=WORLDS_BEFORE)
    ap.add_argument('--profile', default='T', help='save profile: the folder save<profile> in the game folder')
    ap.add_argument('--width', type=int, default=960, help='pictures are scaled down to this width')
    ap.add_argument('--input', help='live input lines sent once the stage has loaded, separated by ;')
    ap.add_argument('--menus', action='store_true', help='walk the menus instead of starting from the title straight into the stage')
    a = ap.parse_args()
    game = str(paths.GAME)
    if a.course.startswith('st'):                        # looked up in the import's stage list
        for line in open(os.path.join(game, 'mania', 'mania_stages.txt'), encoding='utf-8'):
            f = line.rstrip('\n').split('\t')
            if f[2] == a.course:
                print(f'{a.course}: course {f[0]} ({f[3]}), stage {f[1]} ({f[4]})')
                a.course, a.stage = f[0], int(f[1])
                break
        else:
            sys.exit(f'{a.course} is not in mania_stages.txt')
    a.course = int(a.course)
    if a.stage is None:
        sys.exit('stage number missing')
    course_id = thumbshot.course_id(game, a.course)      # Course.eID, for BR_BOOT_STAGE
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
    env = dict(os.environ, BR_PROFILE=a.profile, BR_INPUT_LIVE=live, BR_STATE_LOG='1', BR_NO_REAL_INPUT='1', BR_MANIA_LOG='1')
    if not a.menus:
        if course_id is None:
            sys.exit(f'course {a.course} is not in mania_courses.txt')
        env['BR_BOOT_STAGE'] = f'{course_id} {a.stage}'
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
        cmd = f"& ([scriptblock]::Create((Get-Content -Raw '{ps}'))) -Out '{os.path.join(a.out, tag)}' -At 0 -Process {paths.NAME} -MaxWidth {a.width}"
        subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, timeout=60)
        src = os.path.join(a.out, tag + '_0.png')
        if os.path.exists(src):
            os.replace(src, os.path.join(a.out, tag + '.png'))

    ok = True
    if not a.menus:                                      # the title hands over to the stage by itself
        t0 = time.time()
        while not logged('test: BR_BOOT_STAGE: course'):
            if time.time() - t0 > 90 or p.poll() is not None:
                ok = False
                break
            time.sleep(0.2)
        tsel = time.time()
    else:
        time.sleep(28)                                   # the title
        t0 = time.time()
        while not logged('UIStateTopMenu requests state 20'):   # A until the main menu has opened Adventure
            if time.time() - t0 > 90 or p.poll() is not None:
                ok = False
                break
            press('A')
            time.sleep(6)
    if ok and a.menus:
        time.sleep(7)                                    # Select World
        press('L')                                       # one tab to the left of Story: the Mania tab
        time.sleep(2)
        press(*['DOWN'] * (a.before + a.course))
        press('A')
        time.sleep(6)                                    # Select Stage
        press(*['DOWN'] * a.stage)
        press('A')
        tsel = time.time()
    if ok:
        def play():                                      # from GO (logged for imported stages), else 21 s after the choice
            while not logged('stage motion at GO') and time.time() < tsel + 21:
                time.sleep(0.1)
            for line in [f'LSU {a.hold}'] + [x.strip() for x in (a.input or '').split(';') if x.strip()]:
                word = line.split()
                ms = int(word[1]) if len(word) > 1 and word[1].isdigit() else 100
                if word[0] != 'WAIT':
                    press(line, gap=0)
                time.sleep(ms / 1000 + 0.2)

        threading.Thread(target=play, daemon=True).start()
        for i, s in enumerate(sorted(float(x) for x in a.shots.split(','))):
            while time.time() - tsel < s:
                time.sleep(0.1)
            shot(f'c{a.course}_s{a.stage}_{i}')
    time.sleep(2)
    alive = p.poll() is None
    subprocess.run(['taskkill', '/F', '/IM', paths.NAME + '.exe'], capture_output=True)
    subprocess.run(['taskkill', '/F', '/IM', 'UnityCrashHandler64.exe'], capture_output=True)
    time.sleep(1)
    print(f'course {a.course} stage {a.stage}: menus {"ok" if ok else "NOT reached"}, the game was {"still running" if alive else "NOT running"} at the end')
    try:
        for line in open(log, encoding='utf-8', errors='replace'):
            if any(k in line for k in ('FATAL', 'mania/scene', 'mania: ', 'mania\\Sound', 'exception', 'Exception')):
                print('   ' + line.rstrip()[:240])
    except OSError:
        print('   no port.log')
    return 0 if alive and ok else 1


if __name__ == '__main__':
    sys.exit(main())
