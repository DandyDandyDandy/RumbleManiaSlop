"""Level editor for the imported Banana Mania stages: a page in the browser, served by this script on this PC only.

    python editor.py [<Banana Mania folder>] [--port N] [--no-browser]        (or editor.cmd in the repo folder)

What a person sets with it (saved at once into mania\\overrides.json, which mania\\build.py reads; overrides.py):

    per stage   the Golden Banana (click one of the stage's bananas in the 3D view), the time of the time mission
                and of its perfect mark, the number of bananas of the banana mission
    per world   whether it has stage missions, and the Rumble world whose graphics it borrows in the menus
    pictures    of one's own for a stage's thumbnail and a world's small picture, big picture and icon: uploaded
                in the page (or, for a stage, taken from the 3D view), cut to the game's shape and kept as PNG
                files in input\\pictures\\ (the user's folder, not part of the repo). A stage picture taken from
                the 3D view is a preview: its point of view is kept too ("view"), and the import lets the game
                itself draw the stage from there (thumbshot.py)

The page shows the stage as Banana Mania has it (the drawn meshes at rest, read from the Mania install with
maniastage.py; nothing is copied into the repo) and a mock-up of Select World and Select Stage with the pictures
the game will show. "Apply to game" runs mania\\build.py --no-stages: the tables are rewritten and only the stages
whose Golden Banana changed are converted again.

The server listens on 127.0.0.1 only and takes changes only from its own page (the Origin header is checked).
What it reads from the two games is cached in build\\mania_work\\editor\\.
"""
import argparse
import base64
import io
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
for p in (HERE, os.path.join(REPO, 'port'), os.path.join(REPO, 'port', 'assets'), os.path.join(REPO, 'setup')):
    sys.path.insert(0, p)

import numpy as np  # noqa: E402

import overrides  # noqa: E402
import paths  # noqa: E402


def importer():
    """The importer (build.py of this folder) as a module; the port folder has a build.py too, so not by name."""
    if 'mania_build' not in sys.modules:
        import importlib.util
        spec = importlib.util.spec_from_file_location('mania_build', os.path.join(HERE, 'build.py'))
        sys.modules['mania_build'] = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sys.modules['mania_build'])
    return sys.modules['mania_build']


TEXTURE_SIZE = 256              # stage textures are scaled down to this for the 3D view
MAX_BODY = 56 << 20             # of a request: a picture of 40 MB as base64
LOCK = threading.RLock()        # UnityPy objects are not used from two requests at once


class Game:
    """What the page needs from the two games, read when first asked for."""

    def __init__(self, mania_dir):
        self.mania_dir = mania_dir
        self.aa = os.path.join(str(paths.GAME), f'{paths.NAME}_Data', 'StreamingAssets', 'aa')
        self.cache = os.path.join(str(paths.BUILD), 'mania_work', 'editor')
        os.makedirs(self.cache, exist_ok=True)
        self._mania = self._sprites = self._thumbs = self._db = None

    @property
    def mania(self):
        if self._mania is None:
            from maniadata import ManiaData
            self._mania = ManiaData(self.mania_dir)
        return self._mania

    @property
    def db(self):
        if self._db is None:
            from dbtable import Database
            self._db = Database(os.path.join(self.aa, 'Switch'), cache=str(paths.BUILD / 'mania_table_index.json'))
        return self._db

    @property
    def sprites(self):
        if self._sprites is None:
            from aacatalog import Catalog
            from sprites import Sprites
            self._sprites = Sprites(self.aa, Catalog(os.path.join(self.aa, 'catalog.json')), self.db)
        return self._sprites

    @property
    def thumbs(self):
        if self._thumbs is None:
            from sprites import ManiaThumbnails
            self._thumbs = ManiaThumbnails(self.mania_dir)
        return self._thumbs

    # ---- the lists ------------------------------------------------------------------------------------------
    def index(self):
        build = importer()
        mania = self.mania
        extras = {}
        try:
            with open(os.path.join(str(paths.GAME), 'mania', 'stage_extras.json'), encoding='utf-8') as f:
                extras = json.load(f)
        except (OSError, ValueError):
            pass
        courses = []
        for name, prefix, title, ids in build.plan_courses(mania):
            courses.append({'name': name, 'prefix': prefix, 'title': title, 'world': build.default_world(mania, ids),
                            'thumb': bool(build.course_thumb(mania, name)),
                            'stages': [{'id': i, 'name': mania.stage_name(i), 'limit': mania.time_limit(i),
                                        'bananas': extras.get(str(i), {}).get('banana_count')} for i in ids]})
        course_t, text_t = self.db.table('Course'), self.db.table('Course_Text_en')
        worlds = []
        for r in sorted((r for r in course_t.rows if not r['_empty']), key=lambda r: r['_order']):
            t = text_t.row(r['_id'])
            worlds.append({'id': r['_id'], 'name': t['Name'], 'serial': t['SerialName'], 'thumbnail': r['ThumbnailSpriteID'],
                           'brochure': r['BrochureSpriteID'], 'icon': r['IconSpriteID'], 'title': bool(r['BeginningTitle'][0])})
        return {'courses': courses, 'worlds': worlds, 'overrides': overrides.load(), 'bunch': 10}

    # ---- pictures -------------------------------------------------------------------------------------------
    def picture(self, kind, name):
        """PNG bytes of a menu picture, or None: 'stage' / 'course' = Banana Mania's thumbnail as the import cuts
        it, 'sprite' = a sprite of Banana Rumble."""
        safe = ''.join(ch if ch.isalnum() else '_' for ch in name)
        path = os.path.join(self.cache, f'{kind}_{safe}.png')
        if not os.path.exists(path):
            build = importer()
            if kind == 'stage':
                img = self.thumbs.square(self.mania.stages.get(int(name), {}).get('thumb'))
            elif kind == 'course':
                img = self.thumbs.square(build.course_thumb(self.mania, name))
            else:
                img = self.sprites.image(int(name))
            if img is None:
                return None
            img.thumbnail((512, 640))
            img.save(path)
        with open(path, 'rb') as f:
            return f.read()

    def user_picture(self, name):
        """PNG bytes of one of the user's pictures (input\\pictures), or None."""
        if not overrides.PICTURE_NAME.fullmatch(name):
            return None
        try:
            with open(os.path.join(overrides.PICTURES, name), 'rb') as f:
                return f.read()
        except OSError:
            return None

    def set_picture(self, section, name, key, data):
        """Keep an uploaded picture (data: a data URL or base64 of an image file; None removes it) for the stage
        or course `name` in the shape of `key`; returns the file's name (None when removed)."""
        if section not in ('stages', 'courses') or key not in overrides.PICTURE_SHAPES or (section == 'stages' and key != 'picture'):
            raise ValueError('no such picture')
        safe = ''.join(ch if ch.isascii() and ch.isalnum() else '_' for ch in str(name))[:60]
        if not safe:
            raise ValueError('no such stage or world')
        file = ('st' if section == 'stages' else 'world_') + safe + ('' if section == 'stages' else '_' + key) + '.png'
        path = os.path.join(overrides.PICTURES, file)
        if data is None:
            if os.path.exists(path):
                os.remove(path)
            return None
        from PIL import Image
        try:
            raw = base64.b64decode(data.split(',', 1)[-1], validate=True)
            img = Image.open(io.BytesIO(raw))
            img.load()
        except Exception:
            raise ValueError('this file is not a picture the editor can read (PNG, JPEG, WebP, BMP, GIF)')
        os.makedirs(overrides.PICTURES, exist_ok=True)
        overrides.fit_picture(img, key).save(path + '.tmp', 'PNG')
        os.replace(path + '.tmp', path)
        return file

    # ---- a stage --------------------------------------------------------------------------------------------
    def stage(self, sid):
        """The stage for the 3D view as JSON bytes (cached)."""
        path = os.path.join(self.cache, f'st{sid}.json')
        if not os.path.exists(path):
            data = json.dumps(self.read_stage(sid), separators=(',', ':')).encode()
            with open(path, 'wb') as f:
                f.write(data)
        with open(path, 'rb') as f:
            return f.read()

    def read_stage(self, sid):
        from background import mesh_layout, read_channel
        from maniastage import ManiaStage
        from stage import world_matrix
        m = ManiaStage(self.mania_dir, self.mania.bundles[sid])
        far = set()                     # the renderers of the far detail levels: not drawn (as in the import)
        for n in m.nodes.values():
            lod = n.component('LODGroup')
            if lod:
                for level in lod[2].get('m_LODs', [])[1:]:
                    far.update(r['renderer']['m_PathID'] for r in level.get('renderers', []))
        groups, textures, meshes = {}, {}, {}

        def texture(sf, ref):
            """Index of the texture in the stage's list (a PNG data URL each, scaled down), or -1."""
            got = m.get(sf, ref)
            if got is None:
                return -1, False
            key, _, _, obj = got
            if key not in textures:
                try:
                    img = obj.read().image.convert('RGBA')
                except Exception:
                    textures[key] = (-1, False)
                    return textures[key]
                img.thumbnail((TEXTURE_SIZE, TEXTURE_SIZE))
                alpha = img.getchannel('A').getextrema()[0] < 128
                buf = io.BytesIO()
                (img if alpha else img.convert('RGB')).save(buf, 'PNG')
                textures[key] = (sum(1 for v in textures.values() if v[0] >= 0), alpha,
                                 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode())
            return textures[key][0], textures[key][1]

        def material(ref):
            got = m.get(m.main, ref)
            if got is None:
                return ('none',), {'tex': -1, 'color': [0.7, 0.7, 0.7, 1.0], 'mode': 0, 'st': [1, 1, 0, 0]}
            key, t, msf, _ = got
            props = t['m_SavedProperties']
            main = dict(props['m_TexEnvs']).get('_MainTex') or {}
            c = dict(props['m_Colors']).get('_Color') or {'r': 1, 'g': 1, 'b': 1, 'a': 1}
            tex, alpha = texture(msf, main['m_Texture']) if main else (-1, False)
            st = [main['m_Scale']['x'], main['m_Scale']['y'], main['m_Offset']['x'], main['m_Offset']['y']] if main else [1, 1, 0, 0]
            # 0 opaque, 1 cut out (a texture with holes), 2 blended (a see-through colour)
            return key, {'tex': tex, 'color': [c['r'], c['g'], c['b'], c['a']], 'mode': 2 if c['a'] < 0.99 else 1 if alpha else 0,
                         'st': st}

        def mesh(ref):
            got = m.get(m.main, ref)
            if got is None:
                return None
            key, t, msf, _ = got
            if key not in meshes:
                meshes[key] = None
                vd = t['m_VertexData']
                raw = bytes(vd.get('m_DataSize') or b'')
                if not raw and t.get('m_StreamData', {}).get('size'):
                    raw = m.resource(msf, t['m_StreamData'])
                layout = mesh_layout(dict(t, m_VertexData=dict(vd, m_DataSize=raw)))
                if layout is not None:
                    data = np.frombuffer(raw, dtype=np.uint8)
                    pos, nrm, uv = (read_channel(data, layout, i) for i in (0, 1, 4))
                    idx = np.frombuffer(bytes(t['m_IndexBuffer']), dtype='<u4' if t['m_IndexFormat'] else '<u2').astype(np.int64)
                    size = 4 if t['m_IndexFormat'] else 2
                    subs = [idx[s['firstByte'] // size:s['firstByte'] // size + s['indexCount']] + s['baseVertex']
                            for s in t['m_SubMeshes'] if s.get('topology', 0) == 0]
                    if pos is not None:
                        meshes[key] = (pos[:, :3], nrm[:, :3] if nrm is not None else None, uv[:, :2] if uv is not None else None, subs)
            return meshes[key]

        def shown(n):
            while n is not None:
                if not n.active:
                    return False
                n = n.parent
            return True

        drawn = [c for c in m.root.children if c is not m.collision]
        for top in drawn:
            for n in top.walk():
                mf, mr = n.component('MeshFilter'), n.component('MeshRenderer')
                if not (mf and mr and mr[2]['m_Enabled'] and mr[1] not in far and shown(n)):
                    continue
                got = mesh(mf[2]['m_Mesh'])
                if got is None:
                    continue
                pos, nrm, uv, subs = got
                w = world_matrix(n, m.root)
                wp = pos @ w[:3, :3].T + w[:3, 3]
                normal_m = np.linalg.inv(w[:3, :3]).T if abs(np.linalg.det(w[:3, :3])) > 1e-12 else np.eye(3)
                wn = (nrm @ normal_m.T) if nrm is not None else np.tile([0.0, 1.0, 0.0], (len(pos), 1))
                wn /= np.maximum(np.linalg.norm(wn, axis=1, keepdims=True), 1e-9)
                flip = np.linalg.det(w[:3, :3]) < 0
                for sub, ref in zip(subs, mr[2]['m_Materials']):
                    if not len(sub):
                        continue
                    key, mat = material(ref)
                    g = groups.setdefault(key, dict(mat, pos=[], nrm=[], uv=[], idx=[], count=0))
                    used, inv = np.unique(sub, return_inverse=True)
                    tri = inv.reshape(-1, 3)
                    if flip:
                        tri = tri[:, ::-1]
                    g['pos'].append(wp[used])
                    g['nrm'].append(wn[used])
                    u = uv[used] if uv is not None else np.zeros((len(used), 2))
                    g['uv'].append(u * np.array(mat['st'][:2]) + np.array(mat['st'][2:]))
                    g['idx'].append(tri.reshape(-1) + g['count'])
                    g['count'] += len(used)

        def b64(arrays, dtype):
            return base64.b64encode(np.concatenate(arrays).astype(dtype).tobytes()).decode()

        out_groups = []
        lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
        for g in groups.values():
            p = np.concatenate(g['pos'])
            lo, hi = np.minimum(lo, p.min(axis=0)), np.maximum(hi, p.max(axis=0))
            out_groups.append({'tex': g['tex'], 'color': g['color'], 'mode': g['mode'], 'pos': b64(g['pos'], '<f4'),
                               'nrm': b64(g['nrm'], '<f4'), 'uv': b64(g['uv'], '<f4'), 'idx': b64(g['idx'], '<u4')})
        bananas, goals, start = [], [], None
        for n in (m.collision.walk() if m.collision is not None else []):
            b = n.component('BananaPos')
            p = [float(x) for x in world_matrix(n, m.root)[:3, 3]]
            if b and b[2]['m_Kind'] in (0, 1):
                bananas.append({'path': n.path(m.root), 'kind': int(b[2]['m_Kind']), 'pos': p})
            elif n.component('MgGoalColi'):
                goals.append({'pos': p, 'kind': int(n.component('MgGoalColi')[2]['m_GoalKind'])})
            elif n.name == 'START' and start is None:
                start = p
        if not out_groups:
            pts = np.array([b['pos'] for b in bananas] + ([start] if start else []) + [[0.0, 0.0, 0.0]])
            lo, hi = pts.min(axis=0), pts.max(axis=0)
        ordered = sorted((v for v in textures.values() if v[0] >= 0), key=lambda v: v[0])
        return {'id': sid, 'groups': out_groups, 'textures': [v[2] for v in ordered], 'bananas': bananas, 'goals': goals,
                'start': start, 'lo': [float(x) for x in lo], 'hi': [float(x) for x in hi]}


class Apply:
    """One run of mania\\build.py at a time, with its output kept for the page."""

    def __init__(self, mania_dir):
        self.mania_dir, self.proc, self.lines, self.code = mania_dir, None, [], None

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def start(self):
        if self.running():
            return 'An import is already running.'
        exe = paths.NAME + '.exe'
        try:
            listed = subprocess.run(['tasklist', '/FI', f'IMAGENAME eq {exe}', '/FO', 'CSV', '/NH'], capture_output=True, text=True).stdout
        except OSError:
            listed = ''
        if exe.lower() in listed.lower():
            return 'The game is running. Close it first: it keeps the files open that the import rewrites.'
        self.lines, self.code = [], None
        self.proc = subprocess.Popen([sys.executable, '-u', os.path.join(HERE, 'build.py'), self.mania_dir, '--no-stages'],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace', cwd=REPO)
        threading.Thread(target=self._read, daemon=True).start()
        return None

    def _read(self):
        for line in self.proc.stdout:
            self.lines.append(line.rstrip())
        self.code = self.proc.wait()

    def status(self):
        return {'running': self.running(), 'code': self.code, 'log': self.lines[-12:]}


def make_handler(game, apply):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = 'HTTP/1.1'

        def log_message(self, *a):
            pass

        def send(self, code, body, ctype='application/json', cache=False):
            if isinstance(body, (dict, list)):
                body = json.dumps(body).encode()
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'max-age=86400' if cache else 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def own_page(self):
            """Changes are taken from this server's own page only (not from another site open in the browser)."""
            host = self.headers.get('Host', '')
            origin = self.headers.get('Origin')
            return host.split(':')[0] in ('127.0.0.1', 'localhost') and (origin is None or origin == f'http://{host}')

        def do_GET(self):
            path = self.path.split('?')[0]
            try:
                if path in ('/', '/index.html'):
                    with open(os.path.join(HERE, 'editor.html'), 'rb') as f:
                        return self.send(200, f.read(), 'text/html; charset=utf-8')
                if path == '/api/index':
                    with LOCK:
                        return self.send(200, game.index())
                if path == '/api/apply':
                    return self.send(200, apply.status())
                parts = path.strip('/').split('/')
                if parts[0] == 'api' and parts[1] == 'stage' and parts[2].isdigit():
                    with LOCK:
                        return self.send(200, game.stage(int(parts[2])))
                if parts[0] == 'img' and len(parts) == 3 and parts[1] == 'user':
                    png = game.user_picture(parts[2])
                    return self.send(200, png, 'image/png') if png else self.send(404, b'', 'text/plain')
                if parts[0] == 'img' and len(parts) == 3 and parts[1] in ('stage', 'course', 'sprite'):
                    name = parts[2].rsplit('.', 1)[0]
                    if parts[1] != 'course' and not name.isdigit():
                        return self.send(404, b'', 'text/plain')
                    with LOCK:
                        png = game.picture(parts[1], name)
                    return self.send(200, png, 'image/png', cache=True) if png else self.send(404, b'', 'text/plain')
                self.send(404, b'not found', 'text/plain')
            except Exception as e:                      # shown by the page; the server goes on
                import traceback
                traceback.print_exc()
                self.send(500, {'error': f'{type(e).__name__}: {e}'})

        def do_POST(self):
            if not self.own_page() or 'application/json' not in self.headers.get('Content-Type', ''):
                return self.send(403, {'error': 'not from the editor page'})
            size = int(self.headers.get('Content-Length') or 0)
            if size > MAX_BODY:
                self.close_connection = True
                return self.send(413, {'error': 'the picture is too big (40 MB at most)'})
            body = self.rfile.read(size)
            try:
                if self.path == '/api/picture':
                    j = json.loads(body)
                    file = game.set_picture(j.get('section'), j.get('name'), j.get('key'), j.get('data'))
                    return self.send(200, {'file': file})
                if self.path == '/api/save':
                    overrides.save(json.loads(body))
                    return self.send(200, {'ok': True})
                if self.path == '/api/apply':
                    err = apply.start()
                    return self.send(409 if err else 200, {'error': err} if err else {'ok': True})
                self.send(404, {'error': 'not found'})
            except ValueError as e:
                self.send(400, {'error': str(e)})

    return Handler


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('mania', nargs='?', help='the Banana Mania folder (default: the one the setup uses)')
    ap.add_argument('--port', type=int, default=8765)
    ap.add_argument('--no-browser', action='store_true')
    a = ap.parse_args()
    mania_dir = a.mania
    if not mania_dir:
        import setup as rs_setup
        found = rs_setup.find_mania(rs_setup.mania_config())
        if found is None:
            sys.exit('Banana Mania was not found: name its folder in input\\mania.txt (path=...) or on the command line')
        mania_dir = str(found)
    if not os.path.exists(os.path.join(str(paths.GAME), f'{paths.NAME}_Data', 'StreamingAssets', 'aa', 'catalog.json')):
        sys.exit('The game is not built yet: run setup.cmd first.')
    game, server = Game(mania_dir), None
    for port in range(a.port, a.port + 20):
        try:
            server = ThreadingHTTPServer(('127.0.0.1', port), make_handler(game, Apply(mania_dir)))
            break
        except OSError:
            continue
    if server is None:
        sys.exit(f'no free port from {a.port} on')
    url = f'http://127.0.0.1:{server.server_address[1]}/'
    print(f'Level editor: {url}   (Ctrl+C ends it)', flush=True)
    if not a.no_browser:
        threading.Timer(0.5, webbrowser.open, [url]).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
