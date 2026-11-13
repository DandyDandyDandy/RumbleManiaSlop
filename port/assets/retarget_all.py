"""Retarget every asset bundle of the game to StandaloneWindows64, in parallel.

    python retarget_all.py <aa dir of the extracted game> <decrypted bundle dir> <out aa dir> [--jobs N]

Mirrors <aa>/Switch/** into <out>/Switch/**. Plain UnityFS bundles are rewritten with every SerializedFile's
target platform set to 19. The 145 encrypted bundles are taken from <decrypted bundle dir> (tools/decrypt_bundle.py
output, same file names) and written out decrypted + retargeted. Non-bundle files are copied.
Existing up-to-date outputs are skipped, so the run can be resumed. Prints a summary and writes retarget_report.tsv.
"""
import sys, os, shutil, argparse, multiprocessing as mp, traceback


def work(task):
    src, dst = task
    try:
        if os.path.exists(dst) and os.path.getmtime(dst) >= os.path.getmtime(src):
            return ('skip', src, 0)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, 'rb') as f:
            head = f.read(7)
        if head != b'UnityFS':
            shutil.copy2(src, dst)
            return ('copy', src, 0)
        import UnityPy
        from UnityPy.files import SerializedFile
        env = UnityPy.load(src)
        n = 0

        def walk(f):
            nonlocal n
            if isinstance(f, SerializedFile):
                f._m_target_platform = 19
                f.mark_changed()
                n += 1
            elif hasattr(f, 'files'):
                for c in f.files.values():
                    walk(c)
        walk(env.file)
        data = env.file.save(packer='lz4')
        tmp = dst + '.tmp'
        with open(tmp, 'wb') as f:
            f.write(data)
        os.replace(tmp, dst)
        return ('ok', src, n)
    except Exception as e:
        return ('err', src, traceback.format_exc(limit=2).strip().splitlines()[-1])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('aa'); ap.add_argument('decrypted'); ap.add_argument('out'); ap.add_argument('--jobs', type=int, default=8)
    a = ap.parse_args()
    dec = {f: os.path.join(a.decrypted, f) for f in os.listdir(a.decrypted)} if os.path.isdir(a.decrypted) else {}
    tasks = []
    for r, _, fs in os.walk(a.aa):
        for f in fs:
            src = os.path.join(r, f)
            rel = os.path.relpath(src, a.aa)
            if f in dec and os.path.dirname(rel).lower() == 'switch':
                src = dec[f]
            tasks.append((src, os.path.join(a.out, rel)))
    print(len(tasks), 'files', flush=True)
    stat = {}
    rows = []
    with mp.Pool(a.jobs) as pool:
        for i, (k, s, n) in enumerate(pool.imap_unordered(work, tasks, chunksize=16)):
            stat[k] = stat.get(k, 0) + 1
            if k == 'err':
                rows.append((s, n)); print('ERR', s, n, flush=True)
            if i % 2000 == 0:
                print(i, stat, flush=True)
    with open(os.path.join(a.out, 'retarget_report.tsv'), 'w', encoding='utf-8') as o:
        for s, n in rows:
            o.write(f'{s}\t{n}\n')
    print('done', stat)


if __name__ == '__main__':
    main()
