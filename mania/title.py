"""The fork's own title screen: the monkeys in their balls and the title logo.

    python title.py                 put the title pictures into the built game (seconds; the import build.py
                                    does the same at its end)
    python title.py --export DIR    write the game's own title pictures to DIR as PNG files: the names to use, and
                                    the starting point for new ones

The pictures come from two folders: mania\\title\\ (part of the fork, committed: RumbleMania's title screen, like a
mod's files) and input\\title\\ (one's own, not committed), whose files win over the fork's of the same name.
A picture is a PNG file named like the texture it replaces (letter case does not matter):

    ui_View_TitleLoop_Title_<Aiai|Meemee|Baby|Gongon|Yanyan|Doctor|Palette>.png   the monkeys, 760 x 760
    ui_View_TitleLoop_Title_Title.png       the animated logo: one sheet of 15 pieces (banana logo, plank, ball,
                                            the letters of BananaRumble); the pieces stay where the game cuts them
    ui_View_Title_titlelogo_<lang>.png      the finished logo per language (de en es es419 fr it ja ko ptbr zh zhs),
                                            1024 x 600; ui_View_Title_titlelogo.png stands for every language
                                            without a file of its own
    ui_View_TitleLoop_Title_<Eff|Bg_Press|Sega>.png   sparkle, the "press a button" bar, the small SEGA logo

A picture of another size is scaled to the texture's size. A fully transparent picture removes that monkey.
The game's bundles are not changed: changed copies go to the override folder game\\mania\\Switch\\ (the runtime
reads it first, see docs\\MANIA.md), and a picture removed from both folders gives the game's own back on the
next run.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port'))

import paths  # noqa: E402

LANGS = ('de', 'en', 'es', 'es419', 'fr', 'it', 'ja', 'ko', 'ptbr', 'zh', 'zhs')
LOOP_BUNDLE = 'ui_assets_ui/scenetitleloop/ui_view_titleloop_title.prefab.bundle'
BUNDLES = [LOOP_BUNDLE] + [f'ui_assets_ui/localizedsprite/{l}/ui_view_title_titlelogo_{l}.tga.bundle' for l in LANGS]
PICTURES = (os.path.join(HERE, 'title'), str(paths.INPUT / 'title'))     # the fork's, then one's own (wins)
ALL_LANGS_LOGO = 'ui_view_title_titlelogo'
SKIP = {'ui_Empty', 'TMP_DefaultSprite'}


def user_pictures(folders=PICTURES):
    """{lower-case texture name: path} of the PNG files in the folders; a later folder's file wins."""
    pics = {}
    for folder in folders:
        if os.path.isdir(folder):
            pics.update({f[:-4].lower(): os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith('.png')})
    return pics


def picture_for(name, pics):
    p = pics.get(name.lower())
    if p is None and name.lower().startswith(ALL_LANGS_LOGO + '_'):
        p = pics.get(ALL_LANGS_LOGO)
    return p


def full_quad(tt, tex_w, tex_h):
    """Make a Sprite (typetree) draw its whole rect: the game's sprites are trimmed to the opaque part of the
    original picture (textureRect) and cut to its outline (a tight mesh), which would clip a new picture that
    draws elsewhere. Two vertex streams as the game's sprites have: positions (3 floats), then UVs (2 floats)
    at the next 16-byte boundary."""
    import struct
    r, ppu, pv = tt['m_Rect'], tt['m_PixelsToUnits'], tt['m_Pivot']
    w, h = r['width'], r['height']
    x0, y0 = -pv['x'] * w, -pv['y'] * h
    corners = [(x0, y0), (x0 + w, y0), (x0, y0 + h), (x0 + w, y0 + h)]
    pos = b''.join(struct.pack('<3f', x / ppu, y / ppu, 0.0) for x, y in corners)
    uv = b''.join(struct.pack('<2f', (r['x'] + x - x0) / tex_w, (r['y'] + y - y0) / tex_h) for x, y in corners)
    pos += b'\0' * (-len(pos) % 16)
    rd = tt['m_RD']
    vd = rd['m_VertexData']
    chans = vd['m_Channels']
    if not (chans[0]['dimension'] == 3 and chans[0]['stream'] == 0 and chans[4]['dimension'] == 2 and chans[4]['stream'] == 1
            and all(c['dimension'] == 0 for i, c in enumerate(chans) if i not in (0, 4))):
        return False                            # another vertex layout: leave the sprite as it is
    vd['m_VertexCount'] = 4
    vd['m_DataSize'] = list(pos + uv) if isinstance(vd['m_DataSize'], list) else pos + uv
    idx = struct.pack('<6H', 0, 2, 1, 2, 3, 1)
    rd['m_IndexBuffer'] = list(idx) if isinstance(rd['m_IndexBuffer'], list) else idx
    sm = rd['m_SubMeshes'][0]
    sm.update(firstByte=0, indexCount=6, baseVertex=0, firstVertex=0, vertexCount=4)
    rd['m_SubMeshes'] = [sm]
    rd['textureRect'] = dict(r)
    rd['textureRectOffset'] = {'x': 0.0, 'y': 0.0}
    rd['settingsRaw'] = rd['settingsRaw'] & ~(1 << 6)     # mesh type Full Rect instead of Tight
    tt['m_PhysicsShape'] = []
    return True


def apply(aa, out, folders=PICTURES, log=print):
    """Write changed copies of the title bundles for the pictures in `folders` into the override tree `out`
    (game\\mania); remove the copies of earlier runs that no picture asks for any more. The number of textures."""
    import UnityPy
    from PIL import Image
    from UnityPy.enums import TextureFormat
    pics = user_pictures(folders)
    count = 0
    for rel in BUNDLES:
        src = os.path.join(aa, 'Switch', rel.replace('/', os.sep))
        dst = os.path.join(out, 'Switch', rel.replace('/', os.sep))
        if os.path.exists(dst):
            os.remove(dst)
        if not pics or not os.path.exists(src):
            continue
        env = UnityPy.load(src)
        changed, replaced = [], {}
        for o in env.objects:
            if o.type.name != 'Texture2D':
                continue
            t = o.read()
            path = picture_for(t.m_Name, pics)
            if path is None or t.m_Name in SKIP:
                continue
            with Image.open(path) as f:
                img = f.convert('RGBA')
            if img.size != (t.m_Width, t.m_Height):
                img = img.resize((t.m_Width, t.m_Height), Image.LANCZOS)
            fmt = TextureFormat(t.m_TextureFormat)
            if fmt == TextureFormat.DXT5Crunched:       # crunch cannot be written: plain DXT5, as most of these are
                fmt = TextureFormat.DXT5
            elif fmt == TextureFormat.DXT1Crunched:
                fmt = TextureFormat.DXT1
            t.set_image(img.convert('RGB') if fmt == TextureFormat.DXT1 else img, target_format=fmt,
                        mipmap_count=max(1, t.m_MipCount))
            t.save()
            changed.append(t.m_Name)
            replaced[o.path_id] = (t.m_Width, t.m_Height)
        # sprites that show a whole replaced texture draw all of it (an atlas's pieces keep their cut)
        for o in env.objects:
            if o.type.name != 'Sprite':
                continue
            tt = o.read_typetree()
            size = replaced.get(tt['m_RD']['texture']['m_PathID'])
            if size and (tt['m_Rect']['width'], tt['m_Rect']['height']) == size and full_quad(tt, *size):
                o.save_typetree(tt)
        if changed:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(env.file.save(packer='lz4'))
            count += len(changed)
            log(f'  title: {", ".join(sorted(changed))}')
    return count


def export(aa, folder):
    import UnityPy
    os.makedirs(folder, exist_ok=True)
    n = 0
    for rel in BUNDLES:
        src = os.path.join(aa, 'Switch', rel.replace('/', os.sep))
        if not os.path.exists(src):
            continue
        for o in UnityPy.load(src).objects:
            if o.type.name == 'Texture2D':
                t = o.read()
                if t.m_Name not in SKIP:
                    t.image.save(os.path.join(folder, t.m_Name + '.png'))
                    n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument('--game', default=str(paths.GAME))
    ap.add_argument('--pictures', help='take the pictures from this folder only (default: mania\\title, then input\\title)')
    ap.add_argument('--export', metavar='DIR', help='write the game\'s own title pictures to DIR instead')
    a = ap.parse_args()
    aa = os.path.join(a.game, f'{paths.NAME}_Data', 'StreamingAssets', 'aa')
    if a.export:
        print(f'{export(aa, a.export)} pictures -> {a.export}')
        return 0
    folders = (a.pictures,) if a.pictures else PICTURES
    n = apply(aa, os.path.join(a.game, 'mania'), folders)
    where = ' + '.join(folders)
    print(f'{n} title textures from {where}' if n else f'no title pictures in {where}: the game\'s own title')
    return 0


if __name__ == '__main__':
    sys.exit(main())
