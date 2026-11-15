"""The fork's main menu: the monkeys' beach under a starry night sky.

    python menu_sky.py              put the night sky into the built game (seconds; the import build.py does the
                                    same at its end)
    python menu_sky.py --off        give the game's own main menu back (day, evening, night in turn)
    python menu_sky.py --prepare HDR [--out FILE]
                                    make the sky picture from an equirectangular Radiance .hdr (a Poly Haven HDRI)

The game's main menu is one of three scenes (MainMenu3D_daytime, _evening, _night); the MainMenu_Environment table
moves on to the next every few visits. The fork shows the night scene always, with its sky cubemap made from the
picture mania\\menu_sky\\sky.jpg (an equirectangular sky; input\\menu_sky\\sky.jpg wins when it exists) and the
scene's lights, ambient colours and fog set from menu_sky.txt in the same folders (input\\menu_sky\\'s lines win).

The game's bundles are not changed: changed copies go to the override folder game\\mania\\Switch\\ (the runtime
reads it first, see docs\\MANIA.md).
"""
import argparse
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port'))

import paths  # noqa: E402

NIGHT_BUNDLE = 'scene_mainmenu3d_night_scenes_all.bundle'
ENV_BUNDLE = 'db_assets_db/mainmenu_environment.asset.bundle'
NIGHT_SCENE = 'MainMenu3D_night'
FOLDERS = (os.path.join(HERE, 'menu_sky'), str(paths.INPUT / 'menu_sky'))     # the fork's, then one's own (wins)
FACE = 1024             # edge of the sky cubemap (the game's is 1024)
ENV_FACE = 128          # edge of the reflection cubemap (the game's is 128)
FORMAT_BC7 = 25         # TextureFormat of the game's sky cubemaps

# what menu_sky.txt can set, with the values used when no file names them. A colour is #rrggbb, a light is
# "#rrggbb intensity"; the game's own night values are in docs\MANIA.md.
DEFAULTS = {
    'enabled': 'yes',               # no: the game's own main menu (day, evening, night in turn, the game's sky)
    'rotation': '80',               # turn of the sky round the vertical, degrees (the material's _Rotation)
    'exposure': '1.0',              # the sky material's _Exposure (1: the picture as it is)
    'tint': '#808080',              # the sky material's _Tint (#808080 is neutral: the shader doubles it)
    'light_main': '#e6efff 0.55',   # Directional Light_main (the game's night: #e6efff 0.55)
    'light_back': '#fffefd 0.35',   # Directional Light_back (the game's night: #fffefd 0.35)
    'ambient_sky': '#3c5aaa',       # ambient light from above, from the horizon, from below (trilight)
    'ambient_equator': '#6496dc',
    'ambient_ground': '#9696fa',
    'fog': '#324678 0.00055',       # fog colour and density (exponential squared)
    'grade_exposure': '1.1',        # the scene's Beautify grading: exposure before the tone mapping (game: 1.1),
    'grade_brightness': '1.2',      # brightness after it (game: 1.2),
    'grade_saturation': '1.1',      # saturation (game: 1.1)
}
GRADE = {'grade_exposure': 'tonemapExposurePre', 'grade_brightness': 'tonemapBrightnessPost', 'grade_saturation': 'saturate'}


def settings(folders=FOLDERS):
    """{key: value} of menu_sky.txt in the folders over DEFAULTS; a later folder's lines win."""
    out = dict(DEFAULTS)
    for folder in folders:
        path = os.path.join(folder, 'menu_sky.txt')
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                for line in f:
                    line = line.split('#', 1)[0] if line.lstrip().startswith('#') else line
                    k, sep, v = line.strip().partition('=')
                    if sep:
                        k = k.strip()
                        if k not in DEFAULTS:
                            raise ValueError(f'{path}: unknown setting {k!r} (known: {", ".join(DEFAULTS)})')
                        out[k] = v.strip()
    return out


def colour(text):
    """'#rrggbb' -> (r, g, b) in 0..1."""
    h = text.strip().lstrip('#')
    if len(h) != 6:
        raise ValueError(f'menu_sky.txt: a colour is #rrggbb, not {text!r}')
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def colour_and_number(text):
    c, n = text.split()
    return colour(c), float(n)


# ------------------------------------------------------------------------------------------------ the picture

def read_hdr(path):
    """An equirectangular Radiance RGBE file -> float32 array (h, w, 3), linear."""
    with open(path, 'rb') as f:
        data = f.read()
    pos = 0
    while True:                                         # header lines up to an empty line
        end = data.index(b'\n', pos)
        line = data[pos:end]
        pos = end + 1
        if not line:
            break
    end = data.index(b'\n', pos)
    dims = data[pos:end].split()
    pos = end + 1
    if dims[0] != b'-Y' or dims[2] != b'+X':
        raise ValueError(f'{path}: unsupported orientation {dims}')
    h, w = int(dims[1]), int(dims[3])
    buf = np.frombuffer(data, dtype=np.uint8, offset=pos)
    out = np.empty((h, w, 4), dtype=np.uint8)
    i = 0
    for y in range(h):
        if buf[i] != 2 or buf[i + 1] != 2 or (int(buf[i + 2]) << 8 | int(buf[i + 3])) != w:
            raise ValueError(f'{path}: only new-style run-length scanlines are handled')
        i += 4
        for c in range(4):
            x = 0
            row = out[y, :, c]
            while x < w:
                n = int(buf[i])
                i += 1
                if n > 128:
                    n -= 128
                    row[x:x + n] = buf[i]
                    i += 1
                else:
                    row[x:x + n] = buf[i:i + n]
                    i += n
                x += n
    e = out[..., 3].astype(np.int32)
    scale = np.where(e > 0, np.ldexp(1.0, e - 136), 0.0).astype(np.float32)
    return out[..., :3].astype(np.float32) * scale[..., None]


def blur(img, factor):
    """A soft copy of a float image: scaled down by `factor` and back up (smooth)."""
    from PIL import Image
    h, w = img.shape[:2]
    out = np.empty_like(img)
    for c in range(img.shape[2]):
        small = Image.fromarray(img[..., c]).resize((max(1, w // factor), max(1, h // factor)), Image.BOX)
        out[..., c] = np.asarray(small.resize((w, h), Image.BICUBIC))
    return out


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


# How a photographed night sky becomes the menu's sky (prepare): the sky glow is taken by its brightness only and
# coloured night blue, the stars keep their own colour; the land under the photo's horizon is hidden under a haze
# that the sea's horizon meets; below the horizon the sky is mirrored dimly (only seen past the sea's edges).
GLOW_TINT = np.array([0.30, 0.45, 1.00])    # colour of the sky glow (linear, times its brightness)
GLOW_LEVEL = 0.020                          # brightness of the median sky glow (linear)
GLOW_KEEP = 0.25                            # how much of the photo's own glow colour stays (Milky Way)
GLOW_CONTRAST = 2.2                         # power on the glow's brightness: the Milky Way stands out of the dark
STAR_GAIN = 0.13                            # brightness of the stars over the glow, per median glow
HAZE = np.array([0.030, 0.045, 0.110])      # the haze at the horizon (linear)
HAZE_TOP = 6.0                              # degrees: the haze fades out up to here
HAZE_FULL = 0.5                             # degrees: only haze below this
MIRROR = 0.30                               # brightness of the mirrored sky under the horizon
LAND_MAX = 30.0                             # degrees: the photo's land (hills, trees) is looked for below this
LAND_DARK = 0.55                            # land: darker than this part of the sky glow's median
LAND_MARGIN = 1.5                           # degrees kept clear above the land's top
SKY_LIFT = 0.6                              # < 1 brings the photo's higher sky down towards the horizon: the menu's
#                                             cameras see only the lowest ~20 degrees (0.6: 15 degrees shows 30)


def stretch_over_land(img, elev, lum_w):
    """The photo with its land taken out: in each column the sky above the land's top is stretched down to the
    horizon (the land's top is found as the highest dark point under LAND_MAX, smoothed along the horizon)."""
    from PIL import Image
    h, w = img.shape[:2]
    sw, sh = 512, 256
    small = np.asarray(Image.fromarray(np.ascontiguousarray(img @ lum_w)).resize((sw, sh), Image.BOX))
    se = (0.5 - (np.arange(sh) + 0.5) / sh) * 180.0
    ref = float(np.median(small[(se > LAND_MAX) & (se < 60)]))
    dark = (small < LAND_DARK * ref) & (se[:, None] > 0) & (se[:, None] < LAND_MAX)
    top = np.where(dark.any(axis=0), np.where(dark, se[:, None], -90).max(axis=0), 0.0)
    top = np.maximum(top, 0.0)
    # widen and soften along the horizon (wrapping round), then the margin
    k = 9
    pad = np.concatenate([top[-k:], top, top[:k]])
    top = np.array([pad[i:i + 2 * k + 1].max() for i in range(sw)])
    pad = np.concatenate([top[-k:], top, top[:k]])
    top = np.convolve(pad, np.ones(2 * k + 1) / (2 * k + 1), mode='valid')
    top = np.where(top > 0, top + LAND_MARGIN, 0.0)
    top = np.interp((np.arange(w) + 0.5) / w * sw - 0.5, np.arange(sw), top, period=sw)
    # e' = top + (90 - top) * (e / 90) ^ SKY_LIFT for e >= 0: the row of the source for each row of the result
    out = img.copy()
    rows = np.nonzero(elev >= 0)[0]
    e = elev[rows][:, None]
    src_e = top[None, :] + (90.0 - top[None, :]) * (e / 90.0) ** SKY_LIFT
    fy = (0.5 - src_e / 180.0) * h - 0.5
    y0 = np.clip(np.floor(fy).astype(np.int64), 0, h - 1)
    y1 = np.clip(y0 + 1, 0, h - 1)
    a = (fy - np.floor(fy))[..., None]
    cols = np.arange(w)[None, :]
    out[rows] = img[y0, cols] * (1 - a) + img[y1, cols] * a
    print(f'  land: up to {top.max():.1f} degrees, {np.mean(top > 0) * 100:.0f} % of the horizon')
    return out


def prepare(hdr_path, out_path, width=4096):
    """An equirectangular HDR -> the menu's sky picture (sRGB JPEG, width x width / 2)."""
    from PIL import Image
    img = read_hdr(hdr_path)
    h, w = img.shape[:2]
    if w != width:
        img = np.stack([np.asarray(Image.fromarray(img[..., c]).resize((width, width // 2), Image.BOX)) for c in range(3)], -1)
        h, w = img.shape[:2]
    lum_w = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)
    elev = (0.5 - (np.arange(h) + 0.5) / h) * 180.0                     # degrees, per row
    upper = img[(elev > LAND_MAX)]
    median = float(np.median(upper @ lum_w))
    img = stretch_over_land(img / median, elev, lum_w)
    glow = np.clip(blur(img, 32), 0.0, None)            # (bicubic rings can dip under zero)
    stars = np.clip(img - glow, 0.0, None)
    glow_lum = (glow @ lum_w)[..., None] ** GLOW_CONTRAST
    glow = GLOW_LEVEL * (glow_lum * GLOW_TINT * (1 - GLOW_KEEP) + glow * GLOW_KEEP * GLOW_TINT.mean())
    sky = glow + STAR_GAIN * GLOW_LEVEL * stars * 12.0
    # the haze: strongest at the horizon, gone at HAZE_TOP
    e = elev[:, None, None]
    keep = smoothstep(HAZE_FULL, HAZE_TOP, e)
    haze = HAZE * (1.0 - 0.6 * smoothstep(0.0, HAZE_TOP * 2, np.abs(e)))
    out = haze + (sky - haze) * keep
    # under the horizon: the sky above mirrored and dimmed, into the haze
    below = elev < 0
    mirror = out[::-1][below]                                           # row h-1-y mirrors row y
    k = smoothstep(0.0, HAZE_TOP, -e[below])
    out[below] = haze[below] * (1 - k) + (mirror * MIRROR + haze[below] * 0.4) * k
    srgb = np.where(out <= 0.0031308, out * 12.92, 1.055 * np.power(np.clip(out, 0.0031308, None), 1 / 2.4) - 0.055)
    pic = Image.fromarray((np.clip(srgb, 0, 1) * 255 + 0.5).astype(np.uint8))
    pic.save(out_path, quality=95, subsampling=0)
    return pic.size


# ------------------------------------------------------------------------------------------------ the cubemap

# Unity's cubemap faces (+X, -X, +Y, -Y, +Z, -Z), each row-major from its top left: the direction of the point
# (u, v) of a face, u and v from -1 (left, top) to 1
FACES = (
    lambda u, v: (np.ones_like(u), -v, -u),
    lambda u, v: (-np.ones_like(u), -v, u),
    lambda u, v: (u, np.ones_like(u), v),
    lambda u, v: (u, -np.ones_like(u), -v),
    lambda u, v: (u, -v, np.ones_like(u)),
    lambda u, v: (-u, -v, -np.ones_like(u)),
)


def sample(pano, x, y, z):
    """Bilinear samples of an equirectangular float picture (h, w, 3) in the directions (x, y, z)."""
    h, w = pano.shape[:2]
    n = np.sqrt(x * x + y * y + z * z)
    lon = np.arctan2(x, z)
    lat = np.arcsin(np.clip(y / n, -1, 1))
    fx = (0.5 + lon / (2 * np.pi)) * w - 0.5
    fy = (0.5 - lat / np.pi) * h - 0.5
    x0 = np.floor(fx).astype(np.int64)
    y0 = np.floor(fy).astype(np.int64)
    ax, ay = (fx - x0)[..., None], (fy - y0)[..., None]
    y0c, y1c = np.clip(y0, 0, h - 1), np.clip(y0 + 1, 0, h - 1)
    x0w, x1w = x0 % w, (x0 + 1) % w
    top = pano[y0c, x0w] * (1 - ax) + pano[y0c, x1w] * ax
    bot = pano[y1c, x0w] * (1 - ax) + pano[y1c, x1w] * ax
    return top * (1 - ay) + bot * ay


def cube_faces(pano_srgb, size, supersample=2):
    """Six RGBA uint8 faces (size x size) of an equirectangular sRGB picture (uint8 array), averaged over
    supersample^2 points per texel in linear light."""
    lin = (pano_srgb.astype(np.float32) / 255.0) ** 2.2
    n = size * supersample
    c = (np.arange(n) + 0.5) / n * 2 - 1
    u, v = np.meshgrid(c, c)
    faces = []
    for f in FACES:
        col = sample(lin, *f(u, v))
        col = col.reshape(size, supersample, size, supersample, 3).mean(axis=(1, 3))
        rgb = (np.clip(col, 0, 1) ** (1 / 2.2) * 255 + 0.5).astype(np.uint8)
        faces.append(np.concatenate([rgb, np.full((size, size, 1), 255, np.uint8)], -1))
    return faces


def set_cubemap(obj, faces):
    """Write six RGBA faces into a Cubemap object as BC7, one level, the data inside the bundle."""
    import etcpak
    tt = obj.read_typetree()
    size = faces[0].shape[0]
    data = b''.join(etcpak.compress_bc7(np.ascontiguousarray(f).tobytes(), size, size) for f in faces)
    tt.update({'m_Width': size, 'm_Height': size, 'm_CompleteImageSize': len(data) // 6, 'm_TextureFormat': FORMAT_BC7,
               'm_MipCount': 1, 'm_ImageCount': 6, 'm_IsReadable': False, 'image data': data,
               'm_StreamData': {'offset': 0, 'size': 0, 'path': ''}})
    if 'm_PlatformBlob' in tt:
        tt['m_PlatformBlob'] = []
    obj.save_typetree(tt)


# ------------------------------------------------------------------------------------------------ the game

def sky_picture(folders=FOLDERS):
    """Path of sky.jpg (or sky.png) in the folders; a later folder's wins. None when there is none."""
    found = None
    for folder in folders:
        for name in ('sky.jpg', 'sky.png'):
            if os.path.exists(os.path.join(folder, name)):
                found = os.path.join(folder, name)
    return found


def rgba(c):
    return {'r': float(c[0]), 'g': float(c[1]), 'b': float(c[2]), 'a': 1.0}


def night_scene(src, dst, pic_path, s, log=print):
    """A copy of the night main menu scene with the sky of `pic_path` and the lighting of the settings `s`."""
    import UnityPy
    from PIL import Image
    env = UnityPy.load(src)
    with Image.open(pic_path) as f:
        pano = np.asarray(f.convert('RGB'))
    rs = next(o for o in env.objects if o.type.name == 'RenderSettings')
    r = rs.read_typetree()

    def deref(holder, ptr):
        """The object a PPtr of an object of `holder`'s file points to (its file 0 = the same file)."""
        f = holder.assets_file
        if ptr['m_FileID']:
            want = os.path.basename(f.externals[ptr['m_FileID'] - 1].path).lower()
            f = next(o.assets_file for o in env.objects if o.assets_file.name.lower() == want)
        return f.objects[ptr['m_PathID']]

    sky_mat = deref(rs, r['m_SkyboxMaterial'])
    m = sky_mat.read_typetree()
    props = m['m_SavedProperties']
    cube = deref(sky_mat, dict(props['m_TexEnvs'])['_Tex']['m_Texture'])
    set_cubemap(cube, cube_faces(pano, FACE))
    env_cube = deref(rs, r['m_CustomReflection'])
    set_cubemap(env_cube, cube_faces(pano, ENV_FACE, supersample=8))
    props['m_Floats'] = [(k, {'_Exposure': float(s['exposure']), '_Rotation': float(s['rotation'])}.get(k, v)) for k, v in props['m_Floats']]
    props['m_Colors'] = [(k, rgba(colour(s['tint'])) if k == '_Tint' else v) for k, v in props['m_Colors']]
    sky_mat.save_typetree(m)
    # lighting
    fog_c, fog_d = colour_and_number(s['fog'])
    r.update({'m_AmbientSkyColor': rgba(colour(s['ambient_sky'])), 'm_AmbientEquatorColor': rgba(colour(s['ambient_equator'])),
              'm_AmbientGroundColor': rgba(colour(s['ambient_ground'])), 'm_FogColor': rgba(fog_c), 'm_FogDensity': fog_d})
    rs.save_typetree(r)
    lights = 0
    for o in env.objects:
        if o.type.name != 'Light':
            continue
        lt = o.read_typetree()
        name = deref(o, lt['m_GameObject']).read_typetree()['m_Name']
        key = {'Directional Light_main': 'light_main', 'Directional Light_back': 'light_back'}.get(name)
        if key:
            c, i = colour_and_number(s[key])
            lt['m_Color'] = rgba(c)
            lt['m_Intensity'] = i
            o.save_typetree(lt)
            lights += 1
    if lights != 2:
        raise ValueError(f'{src}: {lights} of the two directional lights found')
    graded = 0
    for o in env.objects:
        if o.type.name == 'MonoBehaviour' and o.assets_file is sky_mat.assets_file:
            tt = o.read_typetree()
            if tt.get('m_Name') == 'Beautify':
                for key, field in GRADE.items():
                    tt[field].update(m_OverrideState=1, m_Value=float(s[key]))
                o.save_typetree(tt)
                graded += 1
    if graded != 1:
        raise ValueError(f'{src}: {graded} Beautify settings found, not one')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(env.file.save(packer='lz4'))
    log(f'  menu sky: {os.path.basename(pic_path)}, rotation {s["rotation"]}')


def night_always(src, dst):
    """A copy of the MainMenu_Environment table whose every environment is the night scene."""
    import UnityPy
    env = UnityPy.load(src)
    n = 0
    for o in env.objects:
        if o.type.name == 'MonoBehaviour':
            tt = o.read_typetree()
            if tt.get('m_Name') != 'MainMenu_Environment':
                continue
            for rec in tt['m_RecordList']:
                if rec['m_RawRecord']['SceneID']:
                    rec['m_RawRecord']['SceneID'] = NIGHT_SCENE
                    n += 1
            o.save_typetree(tt)
    if not n:
        raise ValueError(f'{src}: no MainMenu_Environment rows')
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(env.file.save(packer='lz4'))


def apply(aa, out, folders=FOLDERS, log=print):
    """Write the night menu's bundles into the override tree `out` (game\\mania), or remove them when the sky is
    switched off or there is no picture. True when the starry sky is in."""
    rels = (NIGHT_BUNDLE, ENV_BUNDLE)
    dsts = [os.path.join(out, 'Switch', rel.replace('/', os.sep)) for rel in rels]
    for d in dsts:
        if os.path.exists(d):
            os.remove(d)
    s = settings(folders)
    pic = sky_picture(folders)
    if s['enabled'].lower() in ('no', 'off', '0', 'false') or pic is None:
        log('  menu sky: the game\'s own main menu')
        return False
    srcs = [os.path.join(aa, 'Switch', rel.replace('/', os.sep)) for rel in rels]
    night_scene(srcs[0], dsts[0], pic, s, log)
    night_always(srcs[1], dsts[1])
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--game', default=str(paths.GAME))
    ap.add_argument('--off', action='store_true', help='remove the night sky: the game\'s own main menu')
    ap.add_argument('--prepare', metavar='HDR', help='make the sky picture from an equirectangular .hdr instead')
    ap.add_argument('--out', default=os.path.join(FOLDERS[0], 'sky.jpg'), help='where --prepare writes (default mania\\menu_sky\\sky.jpg)')
    a = ap.parse_args()
    if a.prepare:
        print('%d x %d ->' % prepare(a.prepare, a.out), a.out)
        return 0
    aa = os.path.join(a.game, f'{paths.NAME}_Data', 'StreamingAssets', 'aa')
    apply(aa, os.path.join(a.game, 'mania'), folders=() if a.off else FOLDERS)
    return 0


if __name__ == '__main__':
    sys.exit(main())
