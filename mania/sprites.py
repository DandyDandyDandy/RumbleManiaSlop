"""UI pictures: read Banana Rumble's sprites and Banana Mania's thumbnails, and add new sprites to Rumble.

Rumble names a picture by a row of the table `UI_Sprite` (an AssetReference: the GUID of a sprite asset); the
Addressables catalog leads from the GUID to a bundle with one Texture2D and one Sprite. A new picture is a copy of
the bundle of World 1 Stage 1's thumbnail (512 x 512, DXT1) with another image, catalog entries under a GUID of
its own, and an unused row of the table (the table has two thousand of them; the Classic Outfit's icon takes the
last one, the pictures made here the first ones).

Banana Mania's thumbnails (bundle `ui_thumbnail_common`, `UI/thumbnail/Common/t_tmb_st<id>.tga`, 512 x 512) are
slanted cards with a yellow rim on a transparent ground; Rumble's are plain squares, so the largest square inside
the card is cut out.
"""
import hashlib
import os

import UnityPy
from UnityPy.enums import TextureFormat

from dbtable import SCHEMAS, Table
from maniastage import BUNDLES

SCHEMAS['UI_Sprite'] = [('AssetRef', 'a')]
RT = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}'
TEMPLATE_SPRITE = 502           # World 1 Stage 1's thumbnail: the model for new pictures
TABLE_REL = 'db_assets_db/ui_sprite.asset.bundle'
SIZE = 512


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def inner_square(img):
    """The largest centred square of an RGBA picture that is opaque all over (Mania's slanted cards), as a picture."""
    img = img.convert('RGBA')
    w, h = img.size
    alpha = img.getchannel('A')
    for k in range(96, 30, -2):
        s = int(min(w, h) * k / 100)
        box = ((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s)
        if alpha.crop(box).getextrema()[0] >= 250:
            s2 = int(s * 0.96)                  # off the rim
            box = ((w - s2) // 2, (h - s2) // 2, (w - s2) // 2 + s2, (h - s2) // 2 + s2)
            return img.crop(box)
    return img


class ManiaThumbnails:
    """Banana Mania's thumbnail pictures by their path in its tables (`UI/thumbnail/Common/t_tmb_st1001.tga`)."""

    def __init__(self, mania_dir):
        self.path = os.path.join(mania_dir, BUNDLES, 'ui_thumbnail_common')
        self._index = None

    def index(self):
        if self._index is None:
            self._index = {}
            if os.path.exists(self.path):
                for k, o in UnityPy.load(self.path).container.items():
                    if o.type.name == 'Texture2D':
                        self._index[k.lower().split('assetbundlesres/', 1)[-1]] = o
        return self._index

    def image(self, path):
        """The picture as Mania shows it (RGBA), or None."""
        o = self.index().get((path or '').lower())
        return o.read().image.convert('RGBA') if o is not None else None

    def square(self, path):
        img = self.image(path)
        return inner_square(img).convert('RGB') if img is not None else None


class Sprites:
    def __init__(self, aa, cat, db):
        """aa: <game>_Data/StreamingAssets/aa; cat: the Catalog new pictures are added to; db: a dbtable.Database."""
        self.aa, self.cat, self.db = aa, cat, db
        self.table = db.table('UI_Sprite')      # read only here: write_table makes the changed copy
        self.free = [r['_id'] for r in self.table.rows if r['_empty'] and r['_id'] > 0][:-1]
        self.new_rows = {}                      # sprite id -> GUID
        self._made = {}

    def bundle_of(self, sprite_id):
        """(path of the bundle that holds the sprite, its catalog locations) or (None, [])."""
        row = self.table.row(sprite_id)
        locs = self.cat.locations(row['AssetRef'][0]) if row and not row['_empty'] else []
        if not locs:
            return None, []
        bundle = self.cat.entry(self.cat.buckets[locs[0]['dep']][0])
        return bundle['id'].replace(RT, self.aa), locs

    def image(self, sprite_id):
        """A sprite of the game as a picture, or None."""
        path, _ = self.bundle_of(sprite_id)
        if path is None or not os.path.exists(path):
            return None
        for o in UnityPy.load(path).objects:
            if o.type.name == 'Texture2D':
                return o.read().image
        return None

    def add(self, key, img, out, template=TEMPLATE_SPRITE):
        """A new sprite with the picture `img`, written into the override tree `out`; its sprite id. `key` names
        it (the same key gives the same file and GUID in every import). template: the sprite of the game it is a
        copy of; the picture takes its size and texture format (with transparency where that format has it)."""
        if key in self._made:
            return self._made[key]
        if not self.free:
            raise ValueError('the sprite table has no unused row left')
        src, locs = self.bundle_of(template)
        if src is None:
            raise ValueError(f'sprite {template} of the game was not found')
        env = UnityPy.load(src)
        name = 'mania_' + key
        asset_path = f'Assets/Mania/Sprite/{name}.tga'
        for o in env.objects:
            if o.type.name == 'Texture2D':
                t = o.read()
                t.m_Name = name
                fmt = TextureFormat(t.m_TextureFormat)
                t.set_image(img.convert('RGB' if fmt == TextureFormat.DXT1 else 'RGBA').resize((t.m_Width, t.m_Height)),
                            target_format=fmt, mipmap_count=1)
                t.save()
            elif o.type.name == 'Sprite':
                tt = o.read_typetree()
                tt['m_Name'] = name
                o.save_typetree(tt)
            elif o.type.name == 'AssetBundle':
                tt = o.read_typetree()
                tt['m_Name'] = tt['m_AssetBundleName'] = name + '.bundle'
                tt['m_Container'] = [(asset_path, v) for _, v in tt['m_Container']]
                o.save_typetree(tt)
        cab = 'CAB-' + md5('mania sprite ' + key)
        files = {}
        for k, f in env.file.files.items():
            nk = cab + ('.resS' if k.endswith('.resS') else '.resource' if k.endswith('.resource') else '')
            f.name = nk
            files[nk] = f
        env.file.files = files
        rel = f'Switch/mania/thumb_{key}.bundle'
        dst = os.path.join(out, rel.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(env.file.save(packer='lz4'))
        # catalog: the bundle, and the texture and the sprite under an address and a GUID
        c = self.cat
        model = c.entries[c.buckets[locs[0]['dep']][0]]
        asm, cls, opts = c.extra_json(model[4])
        guid = md5('mania sprite guid ' + key)
        primary = rel[len('Switch/'):]
        o = dict(opts, m_Hash=md5('mania sprite ' + key), m_Crc=0, m_BundleName=name + '.bundle', m_BundleSize=os.path.getsize(dst))
        c.add_entry(RT + '/' + rel, model[1], None, c.add_extra_json(asm, cls, o), primary, model[6], [primary])
        address = f'Mania/Sprite/{name}.tga'
        for loc in locs:
            c.add_entry(asset_path, loc['prov'], primary, -1, address, loc['rt'], [address, guid])
        sid = self.free.pop(0)
        self.new_rows[sid] = guid
        self._made[key] = sid
        return sid

    def write_table(self, out_switch, base=None):
        """The sprite table with the new rows, into the override tree. base: the bundle to start from when
        something else changed the table in this import (the Classic Outfit's icon); else the game's own."""
        if not self.new_rows:
            return None
        env = UnityPy.load(base if base and os.path.exists(base) else os.path.join(self.aa, 'Switch', TABLE_REL.replace('/', os.sep)))
        obj = next(o for o in env.objects if o.type.name == 'MonoBehaviour' and o.peek_name() == 'UI_Sprite')
        t = Table('UI_Sprite', bytes(obj.get_raw_data()))
        for sid, guid in self.new_rows.items():
            if not t.row(sid)['_empty']:
                raise ValueError(f'sprite row {sid} is in use')
            t.use(sid, AssetRef=[guid, '', ''])
        obj.set_raw_data(t.encode())
        dst = os.path.join(out_switch, TABLE_REL.replace('/', os.sep))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, 'wb') as f:
            f.write(env.file.save(packer='lz4'))
        return TABLE_REL
