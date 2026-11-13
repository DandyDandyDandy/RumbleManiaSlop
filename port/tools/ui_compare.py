"""UI layout regression check for wide screens.

    python ui_compare.py <port.log of a 16:9 run> <port.log of a wide run> [tolerance px]

Both runs must use the same window height, the same input script and the same BR_SCREEN_DUMP times with
BR_SCREEN_TREE (e.g. 1280x720 and 2560x720). For every dump the script matches the UI elements of the two runs by
their path and compares each element's pixel box, with the wide run's boxes shifted so that its centred 16:9 area
lines up with the 16:9 run. Elements the wide-screen code widens on purpose (full height, centred, exactly as wide
as the screen) are listed separately. Anything else that differs is a layout regression or an animated element.
"""
import re, sys

LINE = re.compile(r'screen: ( *)(.*?)  x (-?\d+)\.\.(-?\d+)  y (-?\d+)\.\.(-?\d+)  \((\d+) children\)')


def load(path):
    dumps, cur, stack, seen, size = [], None, [], {}, None
    for line in open(path, encoding='utf-8', errors='replace'):
        m = re.search(r'screen: ==== ([\d.]+) s, Screen (\d+)x(\d+)', line)
        if m:
            cur = {}
            size = (int(m.group(2)), int(m.group(3)))
            dumps.append((float(m.group(1)), size, cur))
            stack, seen = [], {}
            continue
        m = LINE.search(line)
        if not m or cur is None:
            continue
        depth = (len(m.group(1)) - 2) // 2
        stack = stack[:depth]
        parent = '/'.join(stack)
        k = (parent, m.group(2))
        seen[k] = seen.get(k, 0) + 1
        name = m.group(2) + ('' if seen[k] == 1 else '#%d' % seen[k])
        stack.append(name)
        cur['/'.join(stack)] = tuple(int(m.group(i)) for i in (3, 4, 5, 6))
    return dumps


def main():
    a, b = load(sys.argv[1]), load(sys.argv[2])
    tol = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    if len(a) != len(b):
        print('different number of dumps: %d and %d' % (len(a), len(b)))
    total_bad = 0
    for (ta, (wa, ha), ea), (tb, (wb, hb), eb) in zip(a, b):
        off = (wb - wa) // 2
        same = widened = 0
        bad, only = [], []
        for path, box in ea.items():
            if path not in eb:
                only.append('only in the 16:9 run: ' + path)
                continue
            x0, x1, y0, y1 = eb[path]
            if all(abs(p - q) <= tol for p, q in zip(box, (x0 - off, x1 - off, y0, y1))):
                same += 1
            elif abs(x0) <= tol and abs(x1 - wb) <= tol and abs(box[0]) <= tol and abs(box[1] - wa) <= tol and \
                    abs(y0 - box[2]) <= tol and abs(y1 - box[3]) <= tol:
                widened += 1          # covers the whole screen in both runs
            else:
                bad.append('%s\n      16:9 x %d..%d y %d..%d   wide (shifted) x %d..%d y %d..%d' %
                           (path, box[0], box[1], box[2], box[3], x0 - off, x1 - off, y0, y1))
        only += ['only in the wide run: ' + p for p in eb if p not in ea]
        print('dump at %.0f s (%dx%d against %dx%d): %d elements in place, %d full-screen in both, %d differ, %d unmatched' %
              (ta, wa, ha, wb, hb, same, widened, len(bad), len(only)))
        for s in bad[:40] + only[:10]:
            print('   ' + s)
        total_bad += len(bad)
    print('total differing elements: %d' % total_bad)


main()
