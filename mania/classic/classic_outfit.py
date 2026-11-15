"""classic_outfit.py - the classic monkeys as an Outfit item in the game's Style menu.

The game's costume system (CharaCustomizeAssetAssign) dresses a character by putting a costume asset's mesh,
materials and bone list (by bone name) on the character's `*_cstm_body01` renderer. An "Outfit" item (item category
7) is a set of such assets, one per character. This script adds one new Outfit item, "Classic Outfit", whose body
asset for each of the six monkeys is the classic model from the user's Banana Mania install: body, hands, feet
and head in one mesh, bound to Rumble's bones (see classic_chara.py for how the mesh is fitted). The runtime
(port/runtime/classic.c) hides Rumble's own head, hands and shoes while that mesh is worn.

Everything is written to the override tree game\\mania\\, laid out like the game's aa folder, which the runtime
reads first; the game's own files are not modified:
  catalog.json                        the game's Addressables catalog plus the new bundles and assets
  Switch\\classic\\<name>\\pack.bundle   meshes, materials and textures of one classic monkey
  Switch\\classic\\<name>\\body.bundle   its costume asset (CharaCustomizeAssetData)
  Switch\\classic\\icon.bundle          the item's icon in the Style menu (classic AiAi, rendered here)
  Switch\\<hash>.bundle ...            copies of the item table, its text tables, the asset table and the UI
                                      sprite table with the new item (item id ITEM_ID, a free slot of the table)

mania\\build.py calls build() here.
"""
import os, sys, glob, shutil, struct, hashlib, json
import numpy as np
import UnityPy
from UnityPy.enums import TextureFormat
from PIL import Image
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_chara as cc
from aacatalog import Catalog

OUT = None                       # the override tree (game\mania), set by configure()
INDEX = None                     # cache file: which bundle holds which table


def configure(aa, mania_dir, out, work):
    """aa: the built game's StreamingAssets\\aa folder; out: the override tree; work: a folder for caches."""
    global OUT, INDEX
    cc.configure(aa, mania_dir, work)
    OUT = out
    INDEX = os.path.join(work, 'classic_db_index.json')

RT = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}'
ITEM_ID = 544                    # a blank record of CharaCustomize_Item (and of its text tables)
ITEM_CATEGORY_OUTFIT = 7
INITIAL_CONDITION = 4            # as the Resort Outfit: owned from the start
TEXT = {'en': ('Classic Outfit', 'The look from the original Super Monkey Ball games!')}
LANGS = ('de', 'en', 'es', 'es419', 'fr', 'it', 'ja', 'ko', 'ptbr', 'zh', 'zhs')

def md5(s): return hashlib.md5(s.encode()).hexdigest()
def aa(rel): return os.path.join(cc.AA, rel)

# ------------------------------------------------------------------------------------------------ raw MonoBehaviour helpers
def mb(env):
    return next(o for o in env.objects if o.type.name == 'MonoBehaviour')
def after_name(r):
    n = struct.unpack_from('<i', r, 28)[0]
    return 32 + ((n + 3) & ~3)
def rd_str(b, o):
    n = struct.unpack_from('<i', b, o)[0]
    return b[o + 4:o + 4 + n].decode('utf-8'), o + 4 + ((n + 3) & ~3)
def wr_str(s):
    b = s.encode('utf-8')
    return struct.pack('<i', len(b)) + b + b'\0' * (-len(b) % 4)
def save_bundle(env, rel):
    dst = os.path.join(OUT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, 'wb') as f:
        f.write(env.file.save(packer='lz4'))
    return dst
def rename_cab(env, cab):
    """give the bundle's serialized file (and its resource file) new internal names"""
    bf = env.file
    files = {}
    for k, f in bf.files.items():
        nk = cab + ('.resS' if k.endswith('.resS') else '.resource' if k.endswith('.resource') else '')
        f.name = nk
        files[nk] = f
    bf.files = files

# ------------------------------------------------------------------------------------------------ one character
def build_char(name):
    cfg = cc.config(name)
    num = cc.CHARS[name][2]
    classic, croot = cc.load_classic(cfg)
    baked = cc.bake_transparent(cfg, classic)
    for rel in cfg['prefabs'] + [cfg['design']]:
        if not os.path.exists(os.path.join(cc.ORIG, rel)):
            os.makedirs(os.path.dirname(os.path.join(cc.ORIG, rel)), exist_ok=True)
            shutil.copy2(aa(rel), os.path.join(cc.ORIG, rel))
    envd = UnityPy.load(os.path.join(cc.ORIG, cfg['design']))
    shade_f, shade_c = cc.shading_of(envd)
    d_name = {o.path_id: o.peek_name() for o in envd.objects if o.type.name in ('Material', 'Texture2D', 'Mesh')}
    free_mats = sorted((o for o in envd.objects if o.type.name == 'Material' and not any(k in o.peek_name() for k in ('LOD', 'ghost'))), key=lambda o: o.peek_name())
    free_texs = sorted((o for o in envd.objects if o.type.name == 'Texture2D'), key=lambda o: (not o.peek_name().endswith('_ab'), o.peek_name()))
    mat_of = {}
    def material(cmat):
        if cmat not in mat_of:
            mo, to = free_mats.pop(0), free_texs.pop(0)
            img = baked[cmat] if cmat in baked else cc.classic_image(cfg, cmat)[0]
            side = min(1024, max(img.size))
            if img.size != (side, side): img = img.resize((side, side), Image.LANCZOS)
            t = to.read()
            t.m_ColorSpace = 1
            t.set_image(img, target_format=TextureFormat.RGBA32, mipmap_count=1)
            t.m_Name = 'classic_%s' % cmat
            t.save()
            mt = mo.read_typetree()
            mt['m_Name'] = 'classic_%s' % cmat
            sp = mt['m_SavedProperties']
            for key, env_ in sp['m_TexEnvs']:
                env_['m_Texture'] = dict(m_FileID=0, m_PathID=to.path_id if key == '_BaseMap' else 0)
                env_['m_Scale'] = dict(x=1.0, y=1.0); env_['m_Offset'] = dict(x=0.0, y=0.0)
            sp['m_Floats'] = [(k, shade_f.get(k, v)) for k, v in sp['m_Floats']]
            sp['m_Colors'] = [(k, dict(shade_c[k]) if k in shade_c else v) for k, v in sp['m_Colors']]
            mo.save_typetree(mt)
            mat_of[cmat] = mo.path_id
        return mat_of[cmat]

    # fit on the selector prefab's full-detail skeleton; every prefab and LOD has the same bones by name
    envp = UnityPy.load(os.path.join(cc.ORIG, cfg['prefabs'][1]))
    root = cc.hierarchy(envp)
    top = next(n for n in root.walk() if any(ch.name == 'Hips' for ch in n.children))
    body = cc.fit(classic['body'], croot, root, top, cfg)
    head = cc.rigid(cc.fit(classic['face'], croot, root, top, cfg), top.find('Head'))
    if name == 'doctor':
        head = cc.merge(head, cc.rigid(cc.fit(classic['expr'], croot, root, top, cfg), top.find('Head')))
    decal = [i for i, m in enumerate(head['mats']) if m in baked]
    if decal and len(decal) < len(head['mats']):       # decals are lit like the skin under them
        dv = np.unique(np.concatenate([head['tris'][i] for i in decal]))
        sv = np.unique(np.concatenate([t for i, t in enumerate(head['tris']) if i not in decal]))
        near = ((head['pos'][dv][:, None, :] - head['pos'][sv][None, :, :]) ** 2).sum(-1).argmin(1)
        head['nrm'] = head['nrm'].copy(); head['nrm'][dv] = head['nrm'][sv[near]]
    # body + head in one mesh: the head's vertices all follow the Head bone
    bones = list(body['bones'])
    hb = top.find('Head')
    if hb not in bones: bones.append(hb)
    nb = len(body['pos'])
    hbi = np.zeros_like(head['bi']); hbi[:, 0] = bones.index(hb)
    fm = dict(pos=np.r_[body['pos'], head['pos']], nrm=np.r_[body['nrm'], head['nrm']], uv=np.r_[body['uv'], head['uv']],
              tris=body['tris'] + [t + nb for t in head['tris']], bones=bones, w=np.r_[body['w'], head['w']], bi=np.r_[body['bi'], hbi],
              mats=body['mats'] + head['mats'])
    names = [b.name for b in bones]
    assert len(set(names)) == len(names), 'bone names must be unique'

    mesh_obj = next(o for o in envd.objects if o.type.name == 'Mesh' and o.peek_name().endswith('_cstm_body01'))
    mt = mesh_obj.read_typetree()
    cc.write_mesh(mt, fm, top)
    mt['m_Name'] = 'classic_%s_body' % name
    mesh_obj.save_typetree(mt)
    mat_ids = [material(m) for m in fm['mats']]

    pack_cab = 'CAB-' + md5('classic pack ' + name)
    for o in envd.objects:
        if o.type.name == 'AssetBundle':
            tt = o.read_typetree()
            tt['m_Name'] = tt['m_AssetBundleName'] = 'classic_%s_pack.bundle' % name
            o.save_typetree(tt)
    rename_cab(envd, pack_cab)
    pack_rel = os.path.join('Switch', 'classic', name, 'pack.bundle')
    pack_file = save_bundle(envd, pack_rel)

    # the costume asset: a copy of the character's default body asset pointed at the pack
    src = glob.glob(aa(os.path.join('Switch', 'chara_cstm_assets_chara', 'cstmasset', 'body', '%02d*' % num, 'body001c01_body01_ch%02d.asset.bundle' % num)))[0]
    enva = UnityPy.load(src)
    sf = enva.assets[0]
    o = mb(enva)
    r = bytes(o.get_raw_data())
    p = after_name(r)
    chara, cat = struct.unpack_from('<2i', r, p)
    mesh_file = struct.unpack_from('<i', r, p + 20)[0]          # the external the default mesh comes from
    asset_name = 'classic001c01_body01_ch%02d' % num
    new = r[:28] + wr_str(asset_name) + struct.pack('<2i', chara, cat) + struct.pack('<iq', 0, 0) + struct.pack('<iq', mesh_file, mesh_obj.path_id)
    new += struct.pack('<i', len(names)) + b''.join(wr_str(n) for n in names)
    new += struct.pack('<i', len(mat_ids)) + b''.join(struct.pack('<iq', mesh_file, m) for m in mat_ids)
    o.set_raw_data(new)
    old_cab = sf.externals[mesh_file - 1].path.split('/')[-1]
    sf.externals[mesh_file - 1].path = 'archive:/%s/%s' % (pack_cab, pack_cab)
    asset_path = 'Assets/Application/AssetBundlesRes/Chara/CstmAsset/Classic/classic001c01_body01_ch%02d.asset' % num
    for ob in enva.objects:
        if ob.type.name == 'AssetBundle':
            tt = ob.read_typetree()
            tt['m_Name'] = tt['m_AssetBundleName'] = 'classic_%s_body.bundle' % name
            (key, val), = tt['m_Container']
            tt['m_Container'] = [(asset_path, val)]
            tt['m_PreloadTable'] = [dict(m_FileID=mesh_file, m_PathID=mesh_obj.path_id) if e['m_FileID'] == mesh_file else e for e in tt['m_PreloadTable']]
            tt['m_Dependencies'] = [pack_cab.lower() if d == old_cab.lower() else d for d in tt['m_Dependencies']]
            ob.save_typetree(tt)
    rename_cab(enva, 'CAB-' + md5('classic body ' + name))
    body_rel = os.path.join('Switch', 'classic', name, 'body.bundle')
    body_file = save_bundle(enva, body_rel)
    print('  %-7s %5d verts, %2d bones, %d materials; pack %d KB' % (name, len(fm['pos']), len(names), len(mat_ids), os.path.getsize(pack_file) // 1024))
    return dict(name=name, num=num, guid=md5('classic body asset ' + name), asset_path=asset_path, design=cfg['design'],
                address='Chara/CstmAsset/Classic/classic001c01_body01_ch%02d.asset' % num,
                pack_rel=pack_rel.replace('\\', '/'), body_rel=body_rel.replace('\\', '/'), pack_file=pack_file, body_file=body_file)

# ------------------------------------------------------------------------------------------------ icon
ICON_GUID = md5('classic outfit icon')
ICON_PATH = 'Assets/Application/AssetBundlesRes/UI/Sprite/CharaCustomize/Item/Special/ui_CharaCustomize_Item_classic001c01.tga'
ICON_ADDRESS = 'UI/Sprite/CharaCustomize/Item/Special/ui_CharaCustomize_Item_classic001c01.tga'
ICON_REL = 'Switch/classic/icon.bundle'

def build_icon():
    """the Style menu icon: classic AiAi from the front on a transparent 256 x 256 picture. It replaces the picture
    in a copy of a ball item's icon bundle, whose sprite outline covers nearly the whole picture."""
    from classic_preview import raster
    cfg = cc.config('aiai')
    classic, croot = cc.load_classic(cfg)
    envp = UnityPy.load(os.path.join(cc.ORIG, cfg['prefabs'][1]))
    root = cc.hierarchy(envp)
    top = next(n for n in root.walk() if any(ch.name == 'Hips' for ch in n.children))
    S = 512
    img = np.zeros((S, S, 3), dtype=np.uint8)
    zbuf = np.full((S, S), -1e9)
    for part in ('body', 'face'):
        fm = cc.fit(classic[part], croot, root, top, cfg)
        k = S * 0.78 / 0.74                                    # the model is about 0.74 units tall
        P = np.c_[S / 2 - fm['pos'][:, 0] * k, S * 0.89 - fm['pos'][:, 1] * k, fm['pos'][:, 2]]
        for t, mat in zip(fm['tris'], fm['mats']):
            raster(img, zbuf, P, fm['uv'], t, np.array(cc.classic_image(cfg, mat)[0]), False)
    rgba = np.dstack([img, np.where(zbuf > -1e8, 255, 0).astype(np.uint8)])
    icon = Image.fromarray(rgba, 'RGBA').resize((256, 256), Image.LANCZOS)
    src = aa(os.path.join('Switch', 'sprite_assets_ui', 'sprite', 'characustomize', 'item', 'ball', 'ui_characustomize_item_ball001c01.tga.bundle'))
    env = UnityPy.load(src)
    for o in env.objects:
        if o.type.name == 'Texture2D':
            t = o.read()
            assert (t.m_Width, t.m_Height) == (256, 256)
            t.set_image(icon, target_format=TextureFormat.RGBA32, mipmap_count=1)
            t.save()
        elif o.type.name == 'AssetBundle':
            tt = o.read_typetree()
            tt['m_Name'] = tt['m_AssetBundleName'] = 'classic_icon.bundle'
            tt['m_Container'] = [(ICON_PATH, v) for _, v in tt['m_Container']]
            o.save_typetree(tt)
    rename_cab(env, 'CAB-' + md5('classic outfit icon bundle'))
    return save_bundle(env, ICON_REL.replace('/', os.sep))

# ------------------------------------------------------------------------------------------------ catalog
def patch_catalog(chars, c=None):
    """Add the new bundles and assets to catalog `c` (the caller saves it), or to the game's own catalog, saved
    into the override tree."""
    own = c is None
    if own:
        c = Catalog(aa('catalog.json'))
    ref = next(i for i, e in enumerate(c.entries) if c.ids[e[0]].endswith('/body001c01_body01_ch01.asset.bundle'))
    asm, cls, opts = c.extra_json(c.entries[ref][4])
    shader = next(i for i, e in enumerate(c.entries) if c.ids[e[0]].endswith('/shaders/ch_lit_toon.shader.bundle'))
    aref = next(i for i, e in enumerate(c.entries) if c.ids[e[0]].endswith('/body001c01_body01_ch01.asset'))
    rt_asset, prov_asset, prov_bundle, rt_bundle = c.entries[aref][6], c.entries[aref][1], c.entries[ref][1], c.entries[ref][6]
    for ch in chars:
        depkey = 'classic-deps-' + ch['name']
        for rel, f, label in ((ch['body_rel'], ch['body_file'], 'body'), (ch['pack_rel'], ch['pack_file'], 'pack')):
            o = dict(opts, m_Hash=md5(open(f, 'rb').read().hex()[:4096] + rel), m_Crc=0, m_BundleName='classic_%s_%s.bundle' % (ch['name'], label), m_BundleSize=os.path.getsize(f))
            primary = rel[len('Switch/'):]
            c.add_entry(RT + '/' + rel, prov_bundle, None, c.add_extra_json(asm, cls, o), primary, rt_bundle, [primary, depkey])
        design = next(i for i, e in enumerate(c.entries) if c.ids[e[0]].endswith('/' + os.path.basename(ch['design'])))
        c.buckets[c.add_key(depkey)] += [design, shader]
        c.add_entry(ch['asset_path'], prov_asset, depkey, -1, ch['address'], rt_asset, [ch['address'], ch['guid']])
    # the icon: one bundle, found as a Texture2D and as a Sprite under its address and GUID
    icon_file = os.path.join(OUT, ICON_REL.replace('/', os.sep))
    sref = [i for i, e in enumerate(c.entries) if c.ids[e[0]].endswith('/ui_CharaCustomize_Item_special003c01.tga')]
    o = dict(opts, m_Hash=md5('classic icon'), m_Crc=0, m_BundleName='classic_icon.bundle', m_BundleSize=os.path.getsize(icon_file))
    primary = ICON_REL[len('Switch/'):]
    c.add_entry(RT + '/' + ICON_REL, prov_bundle, None, c.add_extra_json(asm, cls, o), primary, rt_bundle, [primary])
    for i in sref:
        c.add_entry(ICON_PATH, c.entries[i][1], primary, -1, ICON_ADDRESS, c.entries[i][6], [ICON_ADDRESS, ICON_GUID])
    if not own:
        return
    dst = os.path.join(OUT, 'catalog.json')
    c.save(dst)
    chk = Catalog(dst)                                   # read back
    for ch in chars:
        loc = chk.locations(ch['guid'])
        assert len(loc) == 1 and loc[0]['id'] == ch['asset_path'], ch['name']
        deps = [chk.entry(i)['id'].split('/')[-1] for i in chk.buckets[loc[0]['dep']]]
        assert deps[:2] == ['body.bundle', 'pack.bundle'] and deps[-1] == 'ch_lit_toon.shader.bundle' and len(deps) == 4, deps
    assert sorted(l['rtype'] for l in chk.locations(ICON_GUID)) == ['UnityEngine.Sprite', 'UnityEngine.Texture2D']
    print('  catalog: %d entries (%d new)' % (len(chk.entries), 3 * len(chars) + 3))

# ------------------------------------------------------------------------------------------------ database
def db_bundle(object_name):
    """the aa-relative path of the bundle holding the DB object `object_name` (decrypted DB bundles have hash names)"""
    idx = INDEX
    if not os.path.exists(idx):
        found = {}
        for f in sorted(glob.glob(aa(os.path.join('Switch', '*.bundle')))) + sorted(glob.glob(aa(os.path.join('Switch', 'db_assets_db', 'characustomize_asset.asset.bundle')))):
            if os.path.getsize(f) > 3_000_000: continue
            try: env = UnityPy.load(f)
            except Exception: continue
            for o in env.objects:
                if o.type.name == 'MonoBehaviour':
                    r = o.get_raw_data()
                    n = struct.unpack_from('<i', r, 28)[0]
                    if 0 < n < 80: found[bytes(r[32:32 + n]).decode('ascii', 'replace')] = os.path.relpath(f, cc.AA)
        os.makedirs(os.path.dirname(idx), exist_ok=True)
        json.dump(found, open(idx, 'w'))
    return json.load(open(idx))[object_name]

def patch_db(chars):
    # asset table: a new record with one asset reference per character slot (0 unused, 1..7)
    rel = db_bundle('CharaCustomize_Asset')
    env = UnityPy.load(aa(rel)); o = mb(env); r = bytes(o.get_raw_data())
    p0 = after_name(r); cnt = struct.unpack_from('<i', r, p0)[0]
    p = p0 + 4; ids, orders = [], []
    for _ in range(cnt):
        rid, n = struct.unpack_from('<2i', r, p); p += 8
        for _k in range(3 * n): _, p = rd_str(r, p)
        t0, t1 = struct.unpack_from('<2i', r, p); p += 8
        ids.append(rid); orders.append(t1)
    assert p == len(r)
    asset_id = max(ids) + 1
    guid_of = {ch['num']: ch['guid'] for ch in chars}
    rec = struct.pack('<2i', asset_id, 8) + b''.join(wr_str(guid_of.get(i, '')) + wr_str('') + wr_str('') for i in range(8)) + struct.pack('<2i', 0, max(orders) + 1)
    o.set_raw_data(r[:p0] + struct.pack('<i', cnt + 1) + r[p0 + 4:] + rec)
    save_bundle(env, rel)

    # UI sprite table: a blank record becomes the icon's
    rel = os.path.join('Switch', 'db_assets_db', 'ui_sprite.asset.bundle')
    env = UnityPy.load(aa(rel)); o = mb(env); r = bytes(o.get_raw_data())
    p0 = after_name(r); cnt = struct.unpack_from('<i', r, p0)[0]
    p = p0 + 4; recs = []
    for _ in range(cnt):
        rid = struct.unpack_from('<i', r, p)[0]; p += 4
        g, p = rd_str(r, p); s1, p = rd_str(r, p); s2, p = rd_str(r, p)
        t0, t1 = struct.unpack_from('<2i', r, p); p += 8
        recs.append([rid, g, s1, s2, t0, t1])
    assert p == len(r)
    blank = [rec for rec in recs if rec[4] == 1 and rec[0] > 0]
    sprite_id = blank[-1][0]
    blank[-1][1:] = [ICON_GUID, '', '', 0, max(rec[5] for rec in recs) + 1]
    o.set_raw_data(r[:p0 + 4] + b''.join(struct.pack('<i', a[0]) + wr_str(a[1]) + wr_str(a[2]) + wr_str(a[3]) + struct.pack('<2i', a[4], a[5]) for a in recs))
    save_bundle(env, rel)

    # item table: fill the blank record ITEM_ID
    rel = db_bundle('CharaCustomize_Item')
    env = UnityPy.load(aa(rel)); o = mb(env); r = bytearray(o.get_raw_data())
    p0 = after_name(r); cnt = struct.unpack_from('<i', r, p0)[0]
    # a row: _id, Name, Explanation, ColorID, CategoryID, SpriteID, IsDefault, InitialCondition, 10 + ten asset ids,
    # SeasonID, SeasonStepNum, the flags (IsNotCoordinate; game 2.2.0 added IsDole), _empty, _order
    w = (len(r) - p0 - 4) // (4 * cnt)
    assert w >= 24 and 4 + 4 * w * cnt == len(r) - p0, 'item table: unexpected row size'
    rows = [struct.unpack_from('<%di' % w, r, p0 + 4 + 4 * w * i) for i in range(cnt)]
    i = next(k for k, row in enumerate(rows) if row[0] == ITEM_ID)
    assert rows[i][-2] == 1 and rows[i][-1] == -1, 'item record %d is not blank' % ITEM_ID
    order = max(row[-1] for row in rows) + 1
    row = [ITEM_ID, ITEM_ID, ITEM_ID, 0, ITEM_CATEGORY_OUTFIT, sprite_id, 0, INITIAL_CONDITION, 10, asset_id] + [0] * 9 + [0, 0] + [0] * (w - 23) + [0, order]
    struct.pack_into('<%di' % w, r, p0 + 4 + 4 * w * i, *row)
    o.set_raw_data(bytes(r))
    save_bundle(env, rel)

    # text tables
    for lang in LANGS:
        rel = db_bundle('CharaCustomize_Item_Text_' + lang)
        env = UnityPy.load(aa(rel)); o = mb(env); r = bytes(o.get_raw_data())
        p0 = after_name(r); cnt = struct.unpack_from('<i', r, p0)[0]
        p = p0 + 4; out = b''; done = False; maxo = -1
        recs = []
        for _ in range(cnt):
            rid = struct.unpack_from('<i', r, p)[0]; p += 4
            nm, p = rd_str(r, p); ex, p = rd_str(r, p)
            t0, t1 = struct.unpack_from('<2i', r, p); p += 8
            recs.append([rid, nm, ex, t0, t1]); maxo = max(maxo, t1)
        assert p == len(r)
        for rec in recs:
            if rec[0] == ITEM_ID:
                # (the text tables may carry left-over text for an unused item id)
                rec[1], rec[2] = TEXT.get(lang, TEXT['en'])
                if rec[3] == 1: rec[3], rec[4] = 0, maxo + 1
                done = True
            out += struct.pack('<i', rec[0]) + wr_str(rec[1]) + wr_str(rec[2]) + struct.pack('<2i', rec[3], rec[4])
        assert done
        o.set_raw_data(r[:p0 + 4] + out)
        save_bundle(env, rel)
    print('  database: item %d (category %d) -> asset record %d, sprite %d; %d text tables' % (ITEM_ID, ITEM_CATEGORY_OUTFIT, asset_id, sprite_id, len(LANGS)))

def build(catalog=None):
    """Make the classic outfit in the override tree. With `catalog` the entries go into that Catalog object."""
    if os.path.isdir(os.path.join(OUT, 'Switch', 'classic')): shutil.rmtree(os.path.join(OUT, 'Switch', 'classic'))
    chars = [build_char(n) for n in cc.CHARS]
    build_icon()
    patch_catalog(chars, catalog)
    patch_db(chars)
    return chars

if __name__ == '__main__':
    raise SystemExit('run mania\\build.py: it builds the classic outfit together with the stages')
