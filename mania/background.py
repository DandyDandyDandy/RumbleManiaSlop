"""Convert one Banana Mania background into two Banana Rumble scene bundles: far scenery and lighting.

A Mania stage names a background (`Smb1_Jungle`, ...: 21 of them). Everything the background draws is the prefab
`Bg_<name>` of the bundle `bg_<game>_<name>`: one tree of mesh renderers that holds the sky dome, the cloud rings and
the scenery, moved by one Animator. Its lights are the prefab `Light_<name>` of the same bundle, and fog and ambient
light are the `RenderSettings` of the scene bundle `scene_lightingsettings_light_<game>_<name>_unity`.

Rumble splits the same things over scenes that a stage row names (docs/MANIA.md): a far scenery scene (root with
`MainGameBg`, everything on layer 6, unlit), a sky scene (distant cards; empty in four worlds), an effect scene and a
lighting scene (three directional lights, the `RenderSettings` with the skybox material, a post-processing Volume,
`MainGameLight`). Two of them are made here, each from a copy of one of the game's own scenes:

    far scene       <root>                  MainGameBg (the template's root object, emptied)
      200000 + n        bg<NNNN>(Clone)     Mania's drawn tree, names unchanged (the clip binds by path), layer 6,
                                            Animator + ReplayTracker when the background's clip moves something
                    MainGameInitializer     template
    lighting scene  the template's objects; the lights get Mania's colours and directions, RenderSettings Mania's
      210000 + n    fog and ambient light, and the skybox becomes one flat colour (Mania's sky is the dome mesh)

n is the index of the background in sorted name order. Scene names are numbers because the port answers numeric
scene names (docs/MANIA.md, "Two places are closed").

What Mania's shaders do was read out of their compiled code (the bundle `shader`, DX11), so that the materials can
be put on the one Rumble shader that fits, `Shader Graphs/bg_unlit_abd` (unlit: albedo x `_Color` x vertex colour,
blend / depth write / culling as material floats, an optional UV scroll, a fog switch):

    Custom/TextureVc            unlit; texture x _Color x vertex colour, the vertex RGB taken as gamma (pow 2.2);
                                fogged unless the material has the keyword FOG_OFF; blend, ZWrite, ZTest, Cull are
                                material properties
    Custom/TextureVa            unlit; (texture x _Color) x vertex ALPHA on all four channels; never fogged
    Custom/TextureVcCutoutPattern  unlit cut-out flip book (_Column x _Row frames); no vertex colour, never fogged
    Custom/SurfaceVc, SurfacePtVc, SurfaceTrVc   Unity's standard lit model; albedo = texture x _Color x vertex
                                colour (gamma, as above); opaque / alpha test / alpha blend
    Custom/ToonRim, ToonRimTr, Legacy Reflective/Specular   lit; albedo = texture x _Color, no vertex colour
    Shader Forge/FlowmapScrollAllBlend   unlit alpha blend; UV = uv + frac((_USpeed, _VSpeed) x t / 20) - 0.5 (plus
                                a flow-map wobble); texture x vertex colour x _TintColor x mask
    Shader Forge/FlowmapScrollAddMask    unlit additive (rgb x alpha, blend One One); UV = uv + frac((_uspeed,
                                _vspeed) x t) + uv.w x (11.1 _Urandom, 7.77 _Vrandom); no tint
    Shader Forge/FlowmapScrollAdd, FlowmapScrollBlend   as the two above without a base scroll, with _TintColor
    Shader Forge/FlowmapOpaqueScroll     unlit opaque; UV = uv x _basescale + (_BaseUvel, _BaseVvel) x
                                _BaseUVSpeed x t + _baseoffset; texture x vertex colour x _Color
All of them transform the UV by the texture's scale / offset last.

What the one Rumble shader cannot be told is baked into copies of the meshes (the converter owns the vertex
buffers): the gamma of the vertex colours, TextureVa's "alpha on every channel", "no vertex colour", the constant
part of the UV transform (texture scale / offset, the -0.5 of the scrolling shaders, a flip book's first frame) and a
material alpha below one. The time-dependent part of a scroll goes into `_UVscroll` / `_Speed`. Mania's light on
the formerly lit materials becomes a constant per background multiplied into `_Color`.

Not converted: particle systems, the collision twin, the flow-map wobble, mask textures, flip book animation, toon
ramp / rim / specular / cube-map reflections, Mania's post-processing. The 29 stages that place the background
somewhere else (`BgRoot`) are listed in the result's `moved_stages`; build.py hands them to the port, which moves
the scenery's root (mania.c).

Every number that may want tuning in the running game is a constant below; `BackgroundConverter.convert` takes each
of them as a keyword argument in lower case (`convert('Smb1_Jungle', out, fog='volume', light_exposure=0.5)`).
"""
import copy
import hashlib
import math
import os
import sys
import time
import types
import zlib

import numpy as np
import UnityPy
from UnityPy.files import SerializedFile

from maniadata import ManiaData
from maniastage import BUNDLES, ManiaStage, Node
from stage import TAG_STGMOT, Scene, q4, qmul, qrot, walk_pptrs, world_rotation
from unityfile import NULL, Editor, overlay, pptr, serialized_files

HERE = os.path.dirname(os.path.abspath(__file__))
RT = '{UnityEngine.AddressableAssets.Addressables.RuntimePath}'

# ------------------------------------------------------------------------------------------------- identities
FAR_SCENE_BASE = 200000         # scene number (= scene name and catalog key) of a far scene: this + n
LIGHT_SCENE_BASE = 210000       # ... of a lighting scene
BUNDLE_DIR = 'Switch/mania'     # where the bundles go below the output folder (the catalog's "Switch/..." paths)
LAYER_BG = 6                    # Rumble's layer "Bg" (Mania's is 15)

# ------------------------------------------------------------------------------------------------- templates
FAR_TEMPLATE = 'wld05_w05_003'  # the Rumble far scene that is emptied and refilled. It has an object of every class a
#                                 converted scene needs (MeshRenderer, Animator, ReplayTracker, MainGameBg, and in its
#                                 shared file Mesh, Material, Texture2D, AnimationClip, AnimatorController)
LIGHT_TEMPLATE = 'lgt01_w01_001'    # the Rumble lighting scene a background without an entry below is made from
# Lighting scene template per background: what is kept of it is the post-processing Volume profile (Gradient,
# ColorCurves, Beautify, SC Fog), the reflection cubemap (what the ball mirrors) and the shadow settings. The choice
# follows build.py's WORLD_OF_BG (the Rumble world that stood in for the background so far), except Smb1_Masters:
# world 9's bloom washes its bright sky and floor out. To judge Mania's own
# colours without a world's grading on top, use one neutral template for all: light_template='lgt01_w01_001'.
LIGHT_TEMPLATE_OF_BG = {
    'Smb1_Jungle': 'lgt01_w01_001', 'Smb1_Water': 'lgt02_w02_001', 'Smb1_Night': 'lgt06_w06_001', 'Smb1_Sunset': 'lgt04_w04_001',
    'Smb1_Space': 'lgt10_w10_001', 'Smb1_Sands': 'lgt05_w05_001', 'Smb1_Ice': 'lgt07_w07_001', 'Smb1_Storm': 'lgt08_w08_001',
    'Smb1_Masters': 'lgt01_w01_001', 'Smb1_Bonus': 'lgt03_w03_001',
    'Smb2_Jungle': 'lgt01_w01_001', 'Smb2_Lava': 'lgt04_w04_001', 'Smb2_Water': 'lgt02_w02_001', 'Smb2_Whale': 'lgt03_w03_001',
    'Smb2_Park': 'lgt05_w05_001', 'Smb2_Pot': 'lgt08_w08_001', 'Smb2_Bubble': 'lgt07_w07_001', 'Smb2_Gear': 'lgt09_w09_001',
    'Smb2_Space': 'lgt10_w10_001', 'Smb2_Electric': 'lgt06_w06_001', 'Smb2_Bonus': 'lgt03_w03_001',
}
UNLIT_SHADER = 'Shader Graphs/bg_unlit_abd'
UNLIT_SHADER_BUNDLE = 'manual_additions_assets_design/shaders/bg_unlit_abd.shadergraph.bundle'
BUILTIN_SHADER_BUNDLE = '03d1427889f61b04428c4c00262fb03f_unitybuiltinshaders.bundle'   # Default-Skybox, Skybox/Cubemap
MATERIAL_MODEL = ('sky02_w02', 'bg_sky_w02_cloud01')    # (scene, material): a bg_unlit_abd material of the game, the
#                                                          property list every new material starts from
EMPTY_SKY_SCENE = 'sky05_w05'   # the game's own empty sky scene (only a MainGameInitializer): the stage rows' SkySceneID

# --------------------------------------------------------------------------------------- tunables: far scenery
KEEP_MANIA_QUEUE = True     # True: a material's render queue is Mania's (its own, or its shader's), so the order
#                             colour sphere (1950) < dome (2000..2050) < scenery < cloud rings (2900..3400) survives.
#                             False: Rumble's usual queues by kind (opaque shader default, cut-out 2450, blended 3000)
BAKE_VERTEX_COLORS = True   # True: write what Mania's shader does with the vertex colour into the mesh copy (gamma
#                             2.2 on RGB for the *Vc shaders, alpha into RGB for TextureVa, white where the shader
#                             ignores vertex colours). False: vertex colours are carried over untouched
BAKE_UVS = True             # True: the constant part of Mania's UV transform (texture scale / offset, the scroll
#                             shaders' offsets, a flip book's first frame) is written into the mesh copy's UV0.
#                             False: it is only stored as the scale / offset of `_Albedo` (which the shader may ignore)
COLOR_ALPHA_TO_VERTEX = True    # True: a blended material's colour alpha below one is multiplied into the vertex
#                                 alpha of its meshes (those with a colour channel) and the material gets alpha one.
#                                 Rumble's own additive materials have alpha zero in `_Color`, so the shader probably
#                                 does not read it. False: the alpha stays in `_Color`
UV_SCROLL = True            # True: scrolling layers get `_UVscroll` 1 and `_Speed`. False: they stand still
SCROLL_SCALE = (1.0, 1.0)   # multiplies `_Speed` (u, v), in UV units per second: the place to fix a scroll that runs
#                             the wrong way round or at the wrong speed (assumed: uv + `_Speed` x seconds)
LIGHT_BAKE = 'vertex'       # what Mania's light on the formerly lit materials becomes:
#                             'vertex' = computed per vertex from the normal (Mania's ambient light in that direction
#                             + its `Bg` lights x N.L) and multiplied into the vertex colours of the mesh copy, so
#                             the scenery has lit and shadowed sides as in Mania (no cast shadows; things that move
#                             keep the light of their rest pose);
#                             'lights' = one constant per background, multiplied into `_Color` (ambient + the `Bg`
#                             lights, the three constants below): flat; also what a mesh gets whose layout is not
#                             understood; a number or an (r, g, b) in linear light = that constant for every background
LIGHT_VERTEX_RANGE = 2.0    # 'vertex': the brightest light a vertex colour can hold (8 bits: stored as light / this,
#                             and `_Color` is multiplied by it)
LIGHT_BAKE_OF_BG = {}       # per background name: a number or (r, g, b) that replaces LIGHT_BAKE for it
LIGHT_BAKE_NDOTL = 0.5      # 'lights': the part of each `Bg` light that reaches a surface (the mean of N.L)
LIGHT_BAKE_AMBIENT = 1.0    # 'lights', 'vertex': the part of Mania's ambient light that is added
LIGHT_BAKE_GAIN = 1.0       # 'lights', 'vertex': multiplies the result
LIGHT_BAKE_MAX = 1.0        # 'lights': the brightest channel is brought down to this, the hue kept (Mania's tone curve
#                             folds light above one back; here an unlit colour above one just clips and blooms)
FOG_ON_MATERIALS = True     # True: `_FogOn` 1 on the materials Mania fogs (not TextureVa, not FOG_OFF). False: 0 on all
ADDITIVE_FOG = False        # `_FogOn` of additive materials: URP's fog blends towards the fog colour, which on an
#                             additive layer adds a haze instead of fading it out
CUTOUT_ALPHA_TO_MASK = True     # `_AlphaToMask` of cut-out materials (1 on the game's own cut-out materials)
TAG_ANIMATED = True         # the tag StgMot on the objects the clip moves, as Rumble's own far scenery has it
SKIP_CHILDREN = ('Collision',)  # children of the Bg_ prefab that are not copied: the collision twin of the drawn tree
FIND_MOVED_STAGES = True    # read the BgRoot of each stage of the background (the result's 'moved_stages')

# ------------------------------------------------------------------------------------- tunables: lighting scene
LIGHT_INTENSITY = 'mania'   # 'mania': intensities from Mania (below); 'template': keep the template's intensities and
#                             take only colours and directions from Mania
LIGHT_DIRECTIONS = 'mania'  # 'mania': the lights point as in Mania; 'template': as in the template
LIGHT_COLORS = 'mania'      # 'mania' / 'template', likewise for the lights' colours
LIGHT_GAMMA_INTENSITY = True    # Mania multiplies colour x intensity before the gamma decode (GraphicsSettings
#                                 m_LightsUseLinearIntensity = 0), URP after it: a Mania intensity i is i^2.2 in URP
LIGHT_EXPOSURE = 0.85       # multiplies all of Mania's light (the lights and the ambient colours): Mania renders
#                             HDR through a tone curve, Rumble does not. 0.6 puts Mania's key lights (1.0 .. 2.4 after
#                             the gamma rule) around Rumble's own 0.6 .. 1.2, but the stage floors came out dull
#                             next to pictures of Banana Mania; 0.85 with AMBIENT_GAIN 2 matched Jump Single
LIGHT_SCALE_KEY = 1.0       # further factor on the key light (Stage_MainLight <- Stage/Directional Light01)
LIGHT_SCALE_BACK = 1.0      # ... on the back light (BackLight <- Stage/Directional Light02, all of them merged)
LIGHT_SCALE_CHARA = 1.0     # ... on the character light (Chara_MainLight <- Chara/Directional Light01)
LIGHT_SCALE_FAR = 1.0       # ... on Far_MainLight, in the templates that have one (<- Mania's Bg lights; the far
#                             materials are unlit, so it only matters if they are ever made lit)
LIGHT_INTENSITY_MAX = 1.5   # upper limit of any converted intensity
SUN_IS_KEY_LIGHT = True     # RenderSettings.m_Sun = the key light. URP's main light (the only directional light with
#                             shadows) is the sun, or without one the brightest directional light - and Mania's fill
#                             light is the brighter one in four backgrounds (jungle, bonus, lava, electric)
LIGHT_OTHERS_BELOW_KEY = 0.95   # ... and for the case that the sun is not honoured: no other light of the scene is
#                                 brighter than this times the key light. None = leave Mania's ratios alone
SHADOW_STRENGTH = 'mania'   # the key light's shadow strength: 'mania' (0.75 everywhere: a quarter of the key light
#                             reaches shadowed ground), 'template' (1.0), or a number
AMBIENT = 'mania'           # 'mania': trilight colours from Mania (copied where Mania uses three colours, read off its
#                             baked ambient probe at up / horizon / down where it uses the skybox); 'template': keep
AMBIENT_GAIN = 2.0          # multiplies Mania's ambient colours (on top of LIGHT_EXPOSURE). The probe of the 15
#                             skybox backgrounds is dim and blue; raise this if shadowed sides come out too dark
FOG = 'render_settings'     # 'render_settings': RenderSettings linear fog with Mania's colour / start / end, the
#                             Volume's SC Fog switched off (what the game's own split-screen lighting scenes and
#                             world 11 do); the materials' `_FogOn` then decides per material, as in Mania.
#                             'volume': the SC Post Effects Fog of the Volume profile in linear mode with Mania's
#                             values, RenderSettings fog off (a screen effect: it fogs the domes too).
#                             'template': leave both as the template has them. 'off': no fog at all
FOG_DENSITY = 0.0001        # RenderSettings.m_FogDensity. Linear fog does not use it, but the game's shaders for bananas,
#                             characters and stage objects do: with a template's 0.01 everything near the camera was
#                             hazed in the fog colour. Keep it near zero
FOG_DISTANCE_SCALE = 1.0    # multiplies Mania's fog start and end
FOG_VOLUME_MIN_END = 0.0    # 'volume': the fog end is at least this far (push it past the sky dome, 1400 .. 30000)
SKY_COLOR = 'fog'           # the flat colour of the skybox cubemap (seen only through gaps of the dome): 'fog' =
#                             Mania's fog colour, black where Mania has no fog; or an (r, g, b) in 0..1
SKY_TINT = (0.5, 0.5, 0.5)  # `_Tint` of the Skybox/Cubemap material (0.5 is neutral: the shader doubles it)
SKY_EXPOSURE = 1.0          # `_Exposure` of it
SKY_CUBEMAP_SIZE = 16       # edge of the generated cubemap in pixels (RGBA32, no mips: 6 x 16 x 16 x 4 bytes)
REFLECTION_INTENSITY = None     # RenderSettings reflection intensity (the template's cubemap on the ball); None = keep

# Mania's shaders: what each does with the mesh, as read from its code (module docstring). Matched by the start of
# the lower-case name, first match wins; a shader that matches nothing is treated like the last entry and reported.
#   lit     Mania lights it (the light bake applies)
#   vc      vertex colour: 'gamma' RGB^2.2, 'alpha' RGB = alpha, 'raw' as it is, 'white' not used by the shader
#   fog     Mania fogs it (unless the material says FOG_OFF)
#   tex / color   the texture and colour properties
#   premul  the shader multiplies RGB by alpha itself and blends One One: here SrcAlpha One
#   uv      extra UV rule: 'allblend', 'addmask', 'opaquescroll', 'flipbook'
SHADERS = [
    ('custom/texturevccutoutpattern', dict(lit=False, vc='white', fog=False, tex='_MainTex', color='_Color', uv='flipbook', cutout=True)),
    ('custom/texturevc', dict(lit=False, vc='gamma', fog=True, tex='_MainTex', color='_Color')),
    ('custom/textureva', dict(lit=False, vc='alpha', fog=False, tex='_MainTex', color='_Color')),
    ('custom/surfaceptvc', dict(lit=True, vc='gamma', fog=True, tex='_MainTex', color='_Color', cutout=True)),
    ('custom/surface', dict(lit=True, vc='gamma', fog=True, tex='_MainTex', color='_Color')),
    ('custom/toonrim', dict(lit=True, vc='white', fog=True, tex='_MainTex', color='_Color')),
    ('shader forge/flowmapscrollallblend', dict(lit=False, vc='raw', fog=True, tex='_Texture', color='_TintColor', uv='allblend')),
    ('shader forge/flowmapscrolladdmask', dict(lit=False, vc='raw', fog=True, tex='_Texture', color=None, uv='addmask', premul=True)),
    ('shader forge/flowmapopaquescroll', dict(lit=False, vc='raw', fog=False, tex='_Texture', color='_Color', uv='opaquescroll')),
    ('shader forge/flowmapscrollblend', dict(lit=False, vc='raw', fog=True, tex='_Texture', color='_TintColor')),
    ('shader forge/flow', dict(lit=False, vc='raw', fog=True, tex='_Texture', color='_TintColor', premul=True)),
    ('particles/', dict(lit=False, vc='raw', fog=True, tex='_MainTex', color='_Color')),
    ('', dict(lit=True, vc='white', fog=True, tex='_MainTex', color='_Color')),     # Legacy Reflective / Diffuse, unknown
]
QUEUES = {'background': 1000, 'geometry': 2000, 'alphatest': 2450, 'transparent': 3000, 'overlay': 4000}
BLEND_ONE, BLEND_ZERO, BLEND_SRC_ALPHA, BLEND_ONE_MINUS_SRC_ALPHA = 1, 0, 5, 10
# script class <- a field only that class has (the scripts of the two prefabs; maniastage has the stage's)
SIGNATURES = [('CollisionStagePart', 'm_CollisionStage'), ('GravityTilt', 'm_IsEnableFixedUpdate'), ('PostProcessingHolder', 'm_ProfileSwitch'),
              ('KeyLightHolder', 'm_keyLight'), ('MgBgOptimizer', 'm_deactiveNameList')]
VERTEX_FORMATS = {0: '<f4', 1: '<f2', 2: 'u1', 3: 'i1', 4: '<u2', 5: '<i2', 6: 'u1', 7: 'i1', 8: '<u2', 9: '<i2', 10: '<u4', 11: '<i4'}
CHANNEL_NORMAL, CHANNEL_COLOR, CHANNEL_UV0 = 1, 3, 4
NO_STREAM = {'offset': 0, 'size': 0, 'path': ''}
IDENTITY_UV = ((1.0, 1.0), (0.0, 0.0), (0.0, 0.0))
PLAIN_OP = ('raw', 1.0, IDENTITY_UV, None)


# ------------------------------------------------------------------------------------------------ small things

def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def srgb_to_linear(c):
    c = np.maximum(np.asarray(c, dtype=np.float64), 0.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.maximum(np.asarray(c, dtype=np.float64), 0.0)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def rgb(c):
    return np.array([c['r'], c['g'], c['b']], dtype=np.float64)


def color(c, a=1.0):
    return {'r': float(c[0]), 'g': float(c[1]), 'b': float(c[2]), 'a': float(a)}


def cab_of(external_path):
    """The internal file name an external reference points at ('archive:/CAB-x/CAB-x' -> 'CAB-x')."""
    return external_path.replace('\\', '/').rsplit('/', 1)[-1]


def pairs(lst):
    """A material's property list ([[name, value], ...]) as a dict."""
    return {k: v for k, v in lst}


def options(overrides):
    """The tunables: every upper-case constant of this module under its lower-case name, with `overrides` on top."""
    out = {k.lower(): v for k, v in globals().items() if k.isupper() and not k.startswith('_')}
    unknown = set(overrides) - set(out)
    if unknown:
        raise TypeError(f'unknown tunable(s): {sorted(unknown)}')
    out.update(overrides)
    return types.SimpleNamespace(**out)


# ------------------------------------------------------------------------------------------------ Mania's side

class ManiaBackground(ManiaStage):
    """The bundle bg_<game>_<name> read into nodes: `bg` is the root of the Bg_ prefab, `light` of the Light_ one."""

    def __init__(self, game_dir, bundle, bg_prefab, light_prefab):
        self._want = (os.path.basename(bg_prefab).lower(), os.path.basename(light_prefab).lower())
        super().__init__(game_dir, bundle)

    def _build(self):
        sf = self.main
        nodes, by_transform = {}, {}
        for o in sf.objects.values():
            if o.type.name != 'GameObject':
                continue
            g = self.tree(sf, o)
            n = Node()
            n.id, n.name, n.active, n.layer = o.path_id, g['m_Name'], bool(g['m_IsActive']), g['m_Layer']
            for comp in g['m_Component']:
                c = sf.objects.get(comp['component']['m_PathID'])
                if c is None:
                    continue
                t = self.tree(sf, c)
                kind = c.type.name
                if kind == 'Transform':
                    p, r, s = t['m_LocalPosition'], t['m_LocalRotation'], t['m_LocalScale']
                    n.pos, n.rot, n.scale = (p['x'], p['y'], p['z']), (r['x'], r['y'], r['z'], r['w']), (s['x'], s['y'], s['z'])
                    n.transform_id = c.path_id
                    by_transform[c.path_id] = (n, t)
                elif kind == 'MonoBehaviour':
                    kind = next((name for name, field in SIGNATURES if field in t), 'MonoBehaviour')
                n.components.append((kind, c.path_id, t))
            nodes[o.path_id] = n
        for n, t in by_transform.values():
            n.children = [by_transform[c['m_PathID']][0] for c in t['m_Children'] if c['m_PathID'] in by_transform]
            for c in n.children:
                c.parent = n
        self.nodes = nodes
        self.by_transform = {tid: n for tid, (n, _) in by_transform.items()}
        # the prefabs are the bundle's named assets
        found = {}
        for o in sf.objects.values():
            if o.type.name == 'AssetBundle':
                for path, entry in self.tree(sf, o)['m_Container']:
                    found[path.replace('\\', '/').rsplit('/', 1)[-1].lower()] = nodes.get(entry['asset']['m_PathID'])
        self.bg, self.light = found.get(self._want[0]), found.get(self._want[1])
        if self.bg is None or self.light is None:
            raise ValueError(f'{self.bundle}: prefabs {self._want} not found (has {sorted(found)})')


def render_settings(game_dir, light_scene):
    """The RenderSettings of Mania's lighting scene `light_scene` ('Light_smb1_Jungle'): fog and ambient light."""
    env = UnityPy.load(os.path.join(game_dir, BUNDLES, f'scene_lightingsettings_{light_scene.lower()}_unity'))
    for o in env.objects:
        if o.type.name == 'RenderSettings':
            return o.read_typetree()
    raise ValueError(f'{light_scene}: no RenderSettings')


def probe_colors(probe):
    """(sky, equator, ground) in linear light: Unity's ambient probe (27 numbers, 9 per colour channel, already in the
    form the shaders evaluate) read at straight up, around the horizon and straight down."""
    sh = np.array([probe[f'sh[{i:2d}]'] for i in range(27)], dtype=np.float64).reshape(3, 9)

    def at(n):
        x, y, z = n
        return np.array([c[3] * x + c[1] * y + c[2] * z + c[0] - c[6]
                         + c[4] * x * y + c[5] * y * z + 3.0 * c[6] * z * z + c[7] * z * x + c[8] * (x * x - y * y) for c in sh])
    horizon = sum(at(n) for n in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))) / 4.0
    return np.maximum(at((0, 1, 0)), 0), np.maximum(horizon, 0), np.maximum(at((0, -1, 0)), 0)


def ambient_colors(rs):
    """Mania's ambient light as three linear colours (sky, equator, ground), whatever mode it is in."""
    mode = rs['m_AmbientMode']
    if mode == 1:                                   # three colours
        cols = [srgb_to_linear(rgb(rs[k])) for k in ('m_AmbientSkyColor', 'm_AmbientEquatorColor', 'm_AmbientGroundColor')]
    elif mode == 3:                                 # one colour
        cols = [srgb_to_linear(rgb(rs['m_AmbientSkyColor']))] * 3
    else:                                           # the skybox: the probe baked from it
        cols = list(probe_colors(rs['m_AmbientProbe']))
    return [c * rs.get('m_AmbientIntensity', 1.0) for c in cols]


def ambient_at(rs, normals):
    """Mania's ambient light (linear RGB, [n, 3]) on surfaces with the world normals `normals` ([n, 3], unit)."""
    x, y, z = normals[:, 0], normals[:, 1], normals[:, 2]
    if rs['m_AmbientMode'] in (1, 3):
        sky, equator, ground = ambient_colors(rs)
        up, down = np.clip(y, 0, 1)[:, None], np.clip(-y, 0, 1)[:, None]
        return equator * (1 - up - down) + sky * up + ground * down
    probe = rs['m_AmbientProbe']
    sh = np.array([probe[f'sh[{i:2d}]'] for i in range(27)], dtype=np.float64).reshape(3, 9)
    out = np.stack([c[3] * x + c[1] * y + c[2] * z + c[0] - c[6] + c[4] * x * y + c[5] * y * z + 3.0 * c[6] * z * z + c[7] * z * x
                    + c[8] * (x * x - y * y) for c in sh], axis=1)
    return np.maximum(out, 0) * rs.get('m_AmbientIntensity', 1.0)


def mania_lights(bg):
    """The lights of the Light_ prefab by what they light: {'key': [...], 'back': [...], 'chara': [...], 'bg': [...]},
    each a dict {color (sRGB), intensity, rot (world quaternion), dir, shadows, strength, name}. Mania's layers: 15
    Bg, 16 Chara, 17 Stage; the stage lights light the characters too."""
    out = {'key': [], 'back': [], 'chara': [], 'bg': []}
    for n in bg.light.walk():
        c = n.component('Light')
        if c is None or not c[2]['m_Enabled'] or c[2]['m_Type'] != 1:
            continue
        up = n
        while up is not None and up.active:
            up = up.parent
        if up is not None:                          # switched off somewhere up the tree
            continue
        t = c[2]
        rot = world_rotation(n)
        entry = {'name': n.path(bg.light), 'color': rgb(t['m_Color']), 'intensity': float(t['m_Intensity']), 'rot': rot,
                 'dir': qrot(rot, (0.0, 0.0, 1.0)), 'shadows': t['m_Shadows']['m_Type'], 'strength': float(t['m_Shadows']['m_Strength'])}
        mask = t['m_CullingMask']['m_Bits']
        if mask & (1 << 17):
            out['key' if entry['shadows'] and not out['key'] else 'back'].append(entry)
        elif mask & (1 << 16):
            out['chara'].append(entry)
        elif mask & (1 << 15):
            out['bg'].append(entry)
    out['chara'].sort(key=lambda e: e['name'])      # "Directional Light01" is the main one
    if not out['key'] and out['back']:              # no shadow caster: the strongest stage light leads
        out['back'].sort(key=lambda e: -e['intensity'])
        out['key'].append(out['back'].pop(0))
    return out


def light_energy(light, opt):
    """A Mania light's colour x intensity in linear light, the way Mania's pipeline takes it."""
    if opt.light_gamma_intensity:
        return srgb_to_linear(light['color'] * light['intensity'])
    return srgb_to_linear(light['color']) * light['intensity']


def merged_light(lights, opt):
    """Several Mania lights as one for a Rumble light slot: (colour sRGB, URP intensity, rotation). The colour is the
    energy-weighted mix, the intensity the sum, the direction that of the strongest."""
    energy = [light_energy(x, opt) for x in lights]
    total = sum(energy)
    peak = float(total.max())
    if peak <= 0:
        return np.ones(3), 0.0, lights[0]['rot']
    lead = max(range(len(lights)), key=lambda i: float(energy[i].sum()))
    return linear_to_srgb(total / peak), peak, lights[lead]['rot']


# ------------------------------------------------------------------------------------------------- mesh copies

def mesh_layout(tree):
    """(vertex count, [(stream offset, stride)], channels) of a Mesh's vertex data, or None when it is not laid out
    the plain way (compressed, or the sizes do not add up)."""
    vd = tree['m_VertexData']
    n, chans = vd['m_VertexCount'], vd['m_Channels']
    if not n or tree['m_CompressedMesh']['m_Vertices']['m_NumItems']:
        return None
    streams, off = [], 0
    for s in range(max(c['stream'] for c in chans) + 1):
        stride = sum(np.dtype(VERTEX_FORMATS[c['format']]).itemsize * (c['dimension'] & 15) for c in chans if c['stream'] == s)
        streams.append((off, stride))
        end = off + n * stride
        off = (end + 15) & ~15
    if end > len(vd['m_DataSize']):
        return None
    return n, streams, chans


def read_channel(data, layout, index):
    """A vertex channel as float64 [vertices, components] (UNorm8 scaled to 0..1), or None when the mesh lacks it."""
    n, streams, chans = layout
    c = chans[index] if index < len(chans) else None
    if c is None or not c['dimension'] & 15:
        return None
    dt, dim = np.dtype(VERTEX_FORMATS[c['format']]), c['dimension'] & 15
    off, stride = streams[c['stream']]
    block = data[off:off + n * stride].reshape(n, stride)
    vals = np.ascontiguousarray(block[:, c['offset']:c['offset'] + dt.itemsize * dim]).view(dt).reshape(n, dim).astype(np.float64)
    return vals / 255.0 if c['format'] == 2 else vals


def write_channel(data, layout, index, vals):
    n, streams, chans = layout
    c = chans[index]
    dt, dim = np.dtype(VERTEX_FORMATS[c['format']]), c['dimension'] & 15
    off, stride = streams[c['stream']]
    if c['format'] == 2:
        vals = np.clip(np.rint(vals * 255.0), 0, 255)
    raw = np.ascontiguousarray(vals.astype(dt)).view(np.uint8).reshape(n, dt.itemsize * dim)
    data[off:off + n * stride].reshape(n, stride)[:, c['offset']:c['offset'] + dt.itemsize * dim] = raw


def submesh_vertices(tree):
    """Per sub-mesh the indices of the vertices its triangles use."""
    idx = np.frombuffer(bytes(tree['m_IndexBuffer']), dtype='<u4' if tree['m_IndexFormat'] else '<u2')
    size = idx.dtype.itemsize
    return [np.unique(idx[sm['firstByte'] // size:sm['firstByte'] // size + sm['indexCount']].astype(np.int64) + sm['baseVertex'])
            for sm in tree['m_SubMeshes']]


def with_color_channel(tree):
    """A copy of the Mesh dict `tree` with a white vertex colour channel (four bytes at the end of stream 0), or None
    when the layout is not understood."""
    layout = mesh_layout(tree)
    if layout is None:
        return None
    n, streams, chans = layout
    vd = tree['m_VertexData']
    data = np.frombuffer(bytes(vd['m_DataSize']), dtype=np.uint8)
    out = bytearray()
    for s, (off, stride) in enumerate(streams):
        out += b'\0' * (-len(out) % 16)
        block = data[off:off + n * stride].reshape(n, stride)
        if s == 0:
            block = np.concatenate([block, np.full((n, 4), 255, dtype=np.uint8)], axis=1)
        out += block.tobytes()
    new_chans = [dict(c) for c in chans]
    new_chans[CHANNEL_COLOR] = dict(chans[CHANNEL_COLOR], stream=0, offset=streams[0][1], format=2, dimension=4)
    return dict(tree, m_VertexData=dict(vd, m_Channels=new_chans, m_DataSize=bytes(out)))


def edited_mesh(tree, ops, light=None):
    """A copy of the (Rumble-side) Mesh dict `tree` with vertex colours and UV0 rewritten.

    ops: per sub-mesh (vertex colour rule, alpha factor, (uv scale, uv offset, uv.w factor), light key): the vertices
    of that sub-mesh get colour' = rule(colour) with alpha x factor, and uv' = uv x scale + offset + uv.w x factor
    (uv.w is 1 where UV0 has fewer than four components, which is what the GPU feeds a shader that asks for it).
    With a light key (not None) the colour is also multiplied by light(normals, key), an [n, 3] array in 0..1.
    Returns (dict, number of vertices two sub-meshes wanted differently), or None when the layout is not understood."""
    layout = mesh_layout(tree)
    if layout is None:
        return None
    data = np.frombuffer(bytes(tree['m_VertexData']['m_DataSize']), dtype=np.uint8).copy()
    col, uv = read_channel(data, layout, CHANNEL_COLOR), read_channel(data, layout, CHANNEL_UV0)
    normals = read_channel(data, layout, CHANNEL_NORMAL)
    done = np.zeros(layout[0], dtype=bool)
    clash = 0
    for verts, (rule, alpha, (scale, offset, wfac), lit) in zip(submesh_vertices(tree), ops):
        verts = verts[verts < layout[0]]
        clash += int(done[verts].sum())
        verts = verts[~done[verts]]
        done[verts] = True
        if col is not None and col.shape[1] >= 3:
            c = col[verts]
            if rule == 'gamma':
                c[:, :3] = np.maximum(c[:, :3], 0.0) ** 2.2
            elif rule == 'alpha' and c.shape[1] >= 4:
                c[:, :3] = c[:, 3:4]
            elif rule == 'white':
                c[:] = 1.0
            if c.shape[1] >= 4:
                c[:, 3] *= alpha
            if lit is not None and light is not None and normals is not None and normals.shape[1] >= 3:
                c[:, :3] *= light(normals[verts, :3], lit)
            col[verts] = c
        if uv is not None and uv.shape[1] >= 2:
            if uv.shape[1] >= 4:
                shift = uv[verts, 3:4] * np.array(wfac)
            else:                                   # a constant: whole tiles of it are left out (half-float UVs)
                shift = np.mod(np.array(wfac), 1.0)
            uv[verts, :2] = uv[verts, :2] * np.array(scale) + np.array(offset) + shift
    if col is not None:
        write_channel(data, layout, CHANNEL_COLOR, col)
    if uv is not None:
        write_channel(data, layout, CHANNEL_UV0, uv)
    new = dict(tree)
    new['m_VertexData'] = dict(tree['m_VertexData'], m_DataSize=data.tobytes())
    return new, clash


# ------------------------------------------------------------------------------------------- the Rumble scenes

class BgScene(Scene):
    """A Rumble scenery scene (far or lighting) being rewritten: stage.Scene without the stage's own needs, with
    the object layer of the far scenery, and a save that leaves nothing of the template behind in the bundle."""

    def __init__(self, template_bundle, layer=LAYER_BG):
        self.env = UnityPy.load(template_bundle)
        files = serialized_files(self.env)
        self.shared_name = [n for n in files if n.endswith('.sharedAssets')][0]
        self.scene_name = self.shared_name[:-len('.sharedAssets')]
        self.scene, self.shared = Editor(files[self.scene_name]), Editor(files[self.shared_name])
        self.shared_fid = 1 + [i for i, e in enumerate(self.scene.sf.externals) if e.path.endswith(self.shared_name)][0]
        self.layer = layer
        self.go_of_tr, self.tr_of_go, self._imported = {}, {}, {}
        for o in self.scene.objects('Transform'):
            t = self.scene.get(o.path_id)
            self.go_of_tr[o.path_id] = t['m_GameObject']['m_PathID']
            self.tr_of_go[t['m_GameObject']['m_PathID']] = o.path_id

    def new_object(self, name, parent_go, pos=(0, 0, 0), rot=(0, 0, 0, 1), scale=(1, 1, 1), active=True):
        go = super().new_object(name, parent_go, pos, rot, scale, active)
        self.scene.get(go)['m_Layer'] = self.layer
        return go

    def remove_component(self, go, pid):
        g = self.scene.get(go)
        g['m_Component'] = [c for c in g['m_Component'] if c['component']['m_PathID'] != pid]
        self.scene.remove(pid)

    def world_rotation(self, go):
        """World rotation of a scene object (the product of the local rotations up to the root)."""
        q, tr = (0.0, 0.0, 0.0, 1.0), self.tr_of_go[go]
        while tr:
            t = self.scene.get(tr)
            r = t['m_LocalRotation']
            q = qmul((r['x'], r['y'], r['z'], r['w']), q)
            tr = t['m_Father']['m_PathID']
        return q

    def set_world_rotation(self, go, rot):
        father = self.scene.get(self.tr_of_go[go])['m_Father']['m_PathID']
        if father:
            x, y, z, w = self.world_rotation(self.go_of_tr[father])
            rot = qmul((-x, -y, -z, w), rot)
        self.set_transform(go, rot=rot)

    # ---- finishing
    def collect_garbage(self):
        """stage.Scene's sweep of the shared file, then the preload list the way the game's own scenery scenes have
        it: the objects of *other* files that this scene refers to (shaders, a built-in resource), nothing of its own."""
        super().collect_garbage()
        sh, sc = self.shared, self.scene
        ext = {e.path: i + 1 for i, e in enumerate(sh.sf.externals)}
        refs = set()

        def own(p):
            if p['m_FileID']:
                refs.add((p['m_FileID'], p['m_PathID']))

        def from_scene(p):                          # the scene file numbers its externals differently
            if p['m_FileID'] and p['m_FileID'] != self.shared_fid and p['m_PathID']:
                fid = ext.get(sc.sf.externals[p['m_FileID'] - 1].path)
                if fid:
                    refs.add((fid, p['m_PathID']))
        for o in sh.objects():
            if o.type.name not in ('PreloadData', 'AssetBundle'):
                walk_pptrs(sh.get(o.path_id), own)
        for pid in list(sc.sf.objects):
            walk_pptrs(sc.get(pid), from_scene)
        for o in sh.objects('PreloadData'):
            sh.get(o.path_id)['m_Assets'] = [pptr(p, f) for f, p in sorted(refs)]

    def inline_streams(self):
        """Move the data that the kept objects still have in the bundle's resource file (.resS) into the objects, and
        drop the resource files: what is left in them belongs to objects of the template that are gone (lightmaps,
        the sky cubemap)."""
        files = self.env.file.files
        for ed in (self.scene, self.shared):
            for o in ed.objects():
                if o.type.name not in ('Mesh', 'Texture2D', 'Cubemap', 'Texture2DArray', 'Texture3D', 'CubemapArray'):
                    continue
                t = ed.get(o.path_id)
                sd = t.get('m_StreamData')
                if not sd or not sd.get('size'):
                    continue
                res = files[cab_of(sd['path'])]
                pos = res.Position
                res.Position = sd['offset']
                data = bytes(res.read_bytes(sd['size']))
                res.Position = pos
                if o.type.name == 'Mesh':
                    t['m_VertexData']['m_DataSize'] = data
                else:
                    t['image data'] = data
                t['m_StreamData'] = dict(NO_STREAM)
            for pid in list(ed.sf.objects):         # nothing else may point into a resource file
                t = ed.get(pid)
                for k in ('m_StreamData', 'm_Resource', 'm_ExternalResources'):
                    v = t.get(k) if isinstance(t, dict) else None
                    if isinstance(v, dict) and (v.get('size') or v.get('m_Size')):
                        raise ValueError(f'{ed.sf.objects[pid].type.name} {pid} keeps data in a resource file')
        for name in [n for n, f in files.items() if not isinstance(f, SerializedFile)]:
            del files[name]

    def prune_externals(self):
        """Drop the references to other files that nothing uses any more (the template's material bundle) and
        renumber the rest; the dependency lists of the bundle follow the shared file's references."""
        for ed in (self.scene, self.shared):
            sf = ed.sf
            used = {st.local_serialized_file_index for st in sf.script_types}
            for pid in list(sf.objects):
                walk_pptrs(ed.get(pid), lambda p: used.add(p['m_FileID']) if p['m_PathID'] else None)
            keep = [i for i in range(1, len(sf.externals) + 1) if i in used]
            if len(keep) == len(sf.externals):
                continue
            remap = {old: new for new, old in enumerate(keep, 1)}

            def fix(p):
                if p['m_FileID']:
                    p['m_FileID'] = remap.get(p['m_FileID'], 0) if p['m_PathID'] else 0
            for pid in list(sf.objects):
                walk_pptrs(ed.get(pid), fix)
            for st in sf.script_types:
                if st.local_serialized_file_index:
                    st.local_serialized_file_index = remap[st.local_serialized_file_index]
            sf.externals = [sf.externals[i - 1] for i in keep]
            if ed is self.scene:
                self.shared_fid = remap[self.shared_fid]
        deps = [cab_of(e.path).lower() for e in self.shared.sf.externals if e.path.startswith('archive:/')]
        for o in self.shared.objects():
            if o.type.name in ('AssetBundle', 'PreloadData'):
                self.shared.get(o.path_id)['m_Dependencies'] = list(deps)

    def external_cabs(self):
        """The internal file names of the other bundles this scene refers to."""
        refs = [e for i, e in enumerate(self.scene.sf.externals) if i + 1 != self.shared_fid] + list(self.shared.sf.externals)
        out = []
        for e in refs:
            if e.path.startswith('archive:/') and cab_of(e.path) not in out:
                out.append(cab_of(e.path))
        return out

    def save(self, out_path, bundle_name, scene_path, cab):
        self.collect_garbage()
        self.inline_streams()
        self.prune_externals()
        return super().save(out_path, bundle_name, scene_path, cab)


_cache = {}     # read-only inputs, per process: bundle path -> what was read from it


def cached(key, make):
    if key not in _cache:
        _cache[key] = make()
    return _cache[key]


def bundle_cabs(path):
    """The internal file names of a bundle."""
    return cached(('cabs', path), lambda: set(UnityPy.load(path).file.files))


def unlit_shader(aa_switch):
    """(internal file name, path id) of the shader bg_unlit_abd."""
    def find():
        for name, sf in serialized_files(UnityPy.load(os.path.join(aa_switch, UNLIT_SHADER_BUNDLE))).items():
            for o in sf.objects.values():
                if o.type.name == 'Shader' and o.read_typetree()['m_ParsedForm']['m_Name'] == UNLIT_SHADER:
                    return name, o.path_id
        raise ValueError(f'{UNLIT_SHADER} not found in {UNLIT_SHADER_BUNDLE}')
    return cached(('shader', aa_switch), find)


def material_model(aa_switch):
    """The type tree dict of the game's material MATERIAL_MODEL."""
    def find():
        scene, name = MATERIAL_MODEL
        for sf in serialized_files(UnityPy.load(os.path.join(aa_switch, f'scene_{scene}_scenes_all.bundle'))).values():
            for o in sf.objects.values():
                if o.type.name == 'Material' and o.peek_name() == name:
                    return o.read_typetree()
        raise ValueError(f'material {name} not found in scene {scene}')
    return copy.deepcopy(cached(('model', aa_switch), find))


def load_catalog(path):
    """port/assets/aacatalog.Catalog of a catalog.json (the module lives outside this folder)."""
    try:
        from aacatalog import Catalog
    except ImportError:
        sys.path.insert(0, os.path.join(os.path.dirname(HERE), 'port', 'assets'))
        from aacatalog import Catalog
    return Catalog(path)


# ---------------------------------------------------------------------------------------------- scene assets

ASSET_STATS = {'kinds': {}, 'shaders': {}, 'unmapped': {}, 'dropped': {}, 'queues': {}, 'scroll': 0, 'lit': 0, 'mesh_copies': 0, 'uv_baked': 0,
               'color_baked': 0, 'alpha_to_vertex': 0, 'alpha_in_material': 0, 'vertex_clashes': 0, 'vertex_lit': 0}


def scenery_assets(sc, m, opt, aa, stats, bake, light=None):
    """What turns Mania's materials, meshes and textures into objects of the scene `sc` (a stage.Scene) for the
    unlit shader: a namespace with describe(sf, ref) (what a Mania material is), mesh(sf, ref, slots, rot) and
    material(d, alpha_to_vertex, light_in_vertex), as BackgroundConverter uses them. The stage converter uses the
    same for the unlit materials of a stage (arrows, marks).

    m: the ManiaStage read; stats: a dict with the keys of ASSET_STATS; bake: the constant (linear RGB) for a lit
    material whose light is not in its vertices; light: None, or the function (normals, node rotation) -> light
    factor per vertex (then lit materials get their light per vertex)."""
    sh = sc.shared
    vertex_lit = light is not None
    shader_cab, shader_pid = unlit_shader(aa)
    model = material_model(aa)
    tex_ids, mat_ids, mat_info, mesh_base, mesh_ids = {}, {}, {}, {}, {}
    white = []

    def count(table, key, n=1):
        stats[table][key] = stats[table].get(key, 0) + n

    def texture(sf, ref):
        got = m.get(sf, ref)
        if got is None or got[3].type.name != 'Texture2D':
            return None
        key, t, tsf, _ = got
        if key not in tex_ids:
            new = overlay(sh.template('Texture2D'), t)
            data = bytes(t.get('image data') or b'')
            if not data and t.get('m_StreamData', {}).get('size'):
                data = m.resource(tsf, t['m_StreamData'])
            new.update({'image data': data, 'm_StreamData': dict(NO_STREAM), 'm_IsReadable': False})
            if 'm_PlatformBlob' in new:
                new['m_PlatformBlob'] = []
            tex_ids[key] = sh.add('Texture2D', new)
        return tex_ids[key]

    def white_texture():
        """4 x 4 white: the albedo of Mania's materials without a texture (flat colour spheres)."""
        if not white:
            t = sh.template('Texture2D')
            t.update({'m_Name': 'mania_white', 'm_Width': 4, 'm_Height': 4, 'm_CompleteImageSize': 64, 'm_TextureFormat': 4, 'm_MipCount': 1,
                      'm_MipsStripped': 0, 'm_ImageCount': 1, 'm_TextureDimension': 2, 'm_LightmapFormat': 0, 'm_ColorSpace': 1,
                      'm_IsReadable': False, 'm_StreamingMipmaps': False, 'm_IsAlphaChannelOptional': False,
                      'm_TextureSettings': {'m_FilterMode': 1, 'm_Aniso': 1, 'm_MipBias': 0.0, 'm_WrapU': 0, 'm_WrapV': 0, 'm_WrapW': 0},
                      'image data': b'\xff' * 64, 'm_StreamData': dict(NO_STREAM)})
            if 'm_PlatformBlob' in t:
                t['m_PlatformBlob'] = []
            white.append(sh.add('Texture2D', t))
        return white[0]

    def describe(sf, ref):
        """What a Mania material is, as a dict (no object is made): see `material`. None for a missing one."""
        got = m.get(sf, ref)
        if got is None:
            return None
        key, t, msf, _ = got
        if key in mat_info:
            return mat_info[key]
        props = t['m_SavedProperties']
        texs, cols, floats = pairs(props['m_TexEnvs']), pairs(props['m_Colors']), pairs(props['m_Floats'])
        shader = m.get(msf, t['m_Shader'])
        form = shader[1]['m_ParsedForm'] if shader else None
        sname = form['m_Name'] if form else ''
        rule = next(r for prefix, r in SHADERS if sname.lower().startswith(prefix))
        if rule is SHADERS[-1][1] and not sname.lower().startswith(('legacy shaders/', 'custom/reflective')):
            count('unmapped', sname or '(shader not in the bundles)')
        count('shaders', sname or '(shader not in the bundles)')
        declared = {p['m_Name'] for p in form['m_PropInfo']['m_Props']} if form else set()
        sub = form['m_SubShaders'][0] if form and form['m_SubShaders'] else None
        state = sub['m_Passes'][0]['m_State'] if sub and sub['m_Passes'] else None
        tags = {k.lower(): v for k, v in sub['m_Tags']['tags']} if sub else {}
        tags.update({k.lower(): v for k, v in (t.get('stringTagMap') or [])})

        def value(v, default):
            """A pass state value: a number, or the material's value of the property it is bound to."""
            if v is None:
                return default
            if v.get('name') and v['name'] != '<noninit>':
                return float(floats.get(v['name'], default))
            return float(v['val'])
        blend = state['rtBlend0'] if state else {}
        src, dst = int(value(blend.get('srcBlend'), BLEND_ONE)), int(value(blend.get('destBlend'), BLEND_ZERO))
        zwrite, ztest = int(value(state and state['zWrite'], 1)), int(value(state and state['zTest'], 4))
        cull = int(value(state and state['culling'], 2))
        if sname.lower().startswith('particles/'):          # Unity's own: the blend is the material's _Mode
            src, dst = int(floats.get('_SrcBlend', src)), int(floats.get('_DstBlend', dst))
            zwrite = int(floats.get('_ZWrite', zwrite))
        if rule.get('premul') and (src, dst) == (BLEND_ONE, BLEND_ONE):
            src = BLEND_SRC_ALPHA
        if rule.get('cutout') or tags.get('rendertype') == 'TransparentCutout' and (src, dst) == (BLEND_ONE, BLEND_ZERO):
            kind = 'cutout'
        elif (src, dst) == (BLEND_ONE, BLEND_ZERO):
            kind = 'opaque'
        else:
            kind = 'additive' if dst == BLEND_ONE else 'transparent'
        queue = t.get('m_CustomRenderQueue', -1)
        if queue < 0:
            name, _, offset = tags.get('queue', 'geometry').lower().partition('+')
            queue = QUEUES.get(name.strip(), 2000) + (int(offset) if offset.strip().lstrip('-').isdigit() else 0)
        keywords = t.get('m_ShaderKeywords') or ''
        keywords = set(keywords.split() if isinstance(keywords, str) else keywords) | set(t.get('m_ValidKeywords') or [])
        tint = cols.get(rule['color']) if rule['color'] and (rule['color'] in declared or not declared) else None
        tint = np.array([tint[k] for k in 'rgba'], dtype=np.float64) if tint else np.ones(4)
        env = texs.get(rule['tex']) if rule['tex'] in declared or not declared else None
        st = np.array([env['m_Scale']['x'], env['m_Scale']['y'], env['m_Offset']['x'], env['m_Offset']['y']]) if env else np.array([1.0, 1.0, 0, 0])
        # the UV transform: uv' = uv x scale + offset + uv.w x wfac, and the scroll in UV units per second
        scale, offset, wfac, speed = st[:2].copy(), st[2:].copy(), np.zeros(2), np.zeros(2)

        def f(name, default=0.0):
            return float(floats.get(name, default))
        if rule.get('uv') == 'allblend':
            offset -= 0.5 * st[:2]
            speed = np.array([f('_USpeed'), f('_VSpeed')]) / 20.0 * st[:2]
        elif rule.get('uv') == 'addmask':
            wfac = np.array([11.1 * f('_Urandom'), 7.77 * f('_Vrandom')]) * st[:2]
            speed = np.array([f('_uspeed'), f('_vspeed')]) * st[:2]
        elif rule.get('uv') == 'opaquescroll':
            base = np.array([f('_basescaleU', 1.0), f('_basescaleV', 1.0)])
            scale, offset = base * st[:2], np.array([f('_baseoffsetU'), f('_baseoffsetV')]) * st[:2] + st[2:]
            speed = np.array([f('_BaseUvel'), f('_BaseVvel')]) * f('_BaseUVSpeed') * st[:2]
        elif rule.get('uv') == 'flipbook':      # the first frame of the sheet, which reads from the top left
            cols_n, rows_n, frame = max(int(f('_Column', 1)), 1), max(int(f('_Row', 1)), 1), int(f('_StartFrame'))
            cell = np.array([1.0 / cols_n, 1.0 / rows_n])
            scale, offset = st[:2] * cell, st[2:] * cell + np.array([(frame % cols_n) * cell[0], 1.0 - (frame // cols_n + 1) * cell[1]])
            count('dropped', 'flip book animation')
        for prop, what in (('_FlowMap', 'flow map'), ('_Mask', 'mask texture'), ('_Cube', 'reflection cube'), ('_Ramp', 'toon ramp'),
                           ('_SubTex', 'second texture')):
            if prop in declared and (texs.get(prop) or {}).get('m_Texture', {}).get('m_PathID'):
                count('dropped', what)
        em = cols.get('_Emission')
        if rule['lit'] and '_Emission' in declared and em and max(em['r'], em['g'], em['b']) > 0:
            count('dropped', 'emission colour')
        d = dict(key=key, tree=t, sf=msf, name=t['m_Name'], shader=sname, rule=rule, kind=kind, src=src, dst=dst, zwrite=zwrite, ztest=ztest,
                 cull=cull, queue=queue, cutoff=f('_Cutoff', 0.5), tint=tint, env=env,
                 fog=bool(rule['fog'] and 'FOG_OFF' not in keywords), uv=(tuple(scale), tuple(offset), tuple(wfac)), speed=speed)
        mat_info[key] = d
        return d

    def material(d, alpha_to_vertex, light_in_vertex):
        """The bg_unlit_abd material for the Mania material described by `d`; its path id in the shared file.
        alpha_to_vertex: the colour's alpha is in the mesh copy's vertex alpha, so the material's is one.
        light_in_vertex: Mania's light is in the mesh copy's vertex colours (divided by light_vertex_range)."""
        key = (d['key'], alpha_to_vertex, light_in_vertex)
        if key in mat_ids:
            return mat_ids[key]
        kind, rule = d['kind'], d['rule']
        blended = kind in ('transparent', 'additive')
        new = copy.deepcopy(model)
        new['m_Name'] = 'mania_' + d['name']
        new['m_Shader'] = pptr(shader_pid, sc.add_external(shader_cab))
        new['m_ValidKeywords'] = ['_SURFACE_TYPE_TRANSPARENT'] if blended else ['_ALPHATEST_ON'] if kind == 'cutout' else []
        new['stringTagMap'] = [('RenderType', 'Transparent' if blended else 'TransparentCutout' if kind == 'cutout' else 'Opaque')]
        if opt.keep_mania_queue:
            queue = d['queue']
        else:
            queue = 3000 if blended else 2450 if kind == 'cutout' else -1
        new['m_CustomRenderQueue'] = queue
        count('queues', queue)
        # A material that does not write depth must not write it in a depth pre-pass either (the game's own
        # blended materials switch DepthOnly off). One that does - Mania's domes and colour spheres blend with
        # ZWrite on in the opaque queues - keeps the pass, so the depth texture has it like any solid thing.
        new['disabledShaderPasses'] = [] if d['zwrite'] else ['DepthOnly', 'DepthNormalsOnly', 'SHADOWCASTER']
        tex = texture(d['sf'], d['env']['m_Texture']) if d['env'] else None
        baked = opt.bake_uvs
        new['m_SavedProperties']['m_TexEnvs'] = [
            (k, {'m_Texture': pptr(tex or white_texture()) if k == '_Albedo' else dict(NULL),
                 'm_Scale': {'x': 1.0, 'y': 1.0} if baked or k != '_Albedo' or not d['env'] else copy.deepcopy(d['env']['m_Scale']),
                 'm_Offset': {'x': 0.0, 'y': 0.0} if baked or k != '_Albedo' or not d['env'] else copy.deepcopy(d['env']['m_Offset'])})
            for k, _ in new['m_SavedProperties']['m_TexEnvs']]
        tint = d['tint'].copy()
        lin = srgb_to_linear(tint[:3])
        if rule['lit']:
            lin = lin * (opt.light_vertex_range if light_in_vertex else bake)
            stats['lit'] += 1
        alpha, cutoff = float(tint[3]), d['cutoff']
        if kind == 'additive' and d['src'] == BLEND_SRC_ALPHA:      # rgb x alpha is added: the alpha can be in the rgb
            lin, alpha = lin * alpha, 1.0
        elif kind == 'cutout' and 0 < alpha < 1:                    # the test is on texture alpha x colour alpha
            cutoff, alpha = min(cutoff / alpha, 1.0), 1.0
        elif not blended or alpha_to_vertex:
            alpha = 1.0
        elif alpha != 1.0:
            stats['alpha_in_material'] += 1
        speed = d['speed'] * np.array(opt.scroll_scale) if opt.uv_scroll else np.zeros(2)
        scroll = bool(np.abs(speed).max() > 1e-9)
        stats['scroll'] += scroll
        fog = opt.fog_on_materials and d['fog'] and (kind != 'additive' or opt.additive_fog)
        floats = {'_Surface': float(blended), '_Blend': 2.0 if kind == 'additive' else 0.0, '_SrcBlend': float(d['src']), '_DstBlend': float(d['dst']),
                  '_ZWrite': float(d['zwrite']), '_ZTest': float(d['ztest']), '_Cull': float(d['cull']), '_AlphaClip': float(kind == 'cutout'),
                  '_AlphaCut': float(cutoff) if kind == 'cutout' else 0.5, '_AlphaToMask': float(kind == 'cutout' and opt.cutout_alpha_to_mask),
                  '_Emission': 0.0, '_UVscroll': float(scroll), '_FogOn': float(fog), '_QueueOffset': 0.0, '_QueueControl': 0.0, '_ZWriteControl': 0.0}
        new['m_SavedProperties']['m_Floats'] = [(k, floats.get(k, v)) for k, v in new['m_SavedProperties']['m_Floats']]
        colors = {'_Color': color(linear_to_srgb(lin), alpha), '_EmissionColor': color((0, 0, 0)), '_Tiling': color((1, 1, 0), 0),
                  '_Speed': color((speed[0], speed[1], 0), 0)}
        new['m_SavedProperties']['m_Colors'] = [(k, colors.get(k, v)) for k, v in new['m_SavedProperties']['m_Colors']]
        count('kinds', kind)
        mat_ids[key] = sh.add('Material', new)
        return mat_ids[key]

    def mesh(sf, ref, slots, rot):
        """The Mesh for a renderer; (path id, per material slot: is the colour alpha in the vertices, per slot: is
        Mania's light in the vertices). slots: the renderer's materials as `describe` gives them; rot: the
        node's world rotation."""
        got = m.get(sf, ref)
        if got is None:
            return 0, [False] * len(slots), [False] * len(slots)
        key, t, msf, _ = got
        if key not in mesh_base:
            new = overlay(sh.template('Mesh'), t)
            vd = new['m_VertexData']
            if not vd.get('m_DataSize') and t.get('m_StreamData', {}).get('size'):
                vd['m_DataSize'] = m.resource(msf, t['m_StreamData'])
            new.update(m_StreamData=dict(NO_STREAM), m_BakedConvexCollisionMesh=b'', m_BakedTriangleCollisionMesh=b'')
            chans = vd['m_Channels']
            mesh_base[key] = (new, bool(chans[CHANNEL_COLOR]['dimension'] & 15), bool(chans[CHANNEL_UV0]['dimension'] & 15))
        new, has_color, has_uv = mesh_base[key]
        want_light = vertex_lit and any(d and d['rule']['lit'] for d in slots)
        want_alpha = opt.color_alpha_to_vertex and opt.bake_vertex_colors and any(d and d['kind'] == 'transparent' and d['tint'][3] != 1.0
                                                                                  for d in slots)
        if (want_light or want_alpha) and not has_color:    # no vertex colours to put it in: give it white ones
            colored = with_color_channel(new)
            if colored is not None:
                mesh_base[key] = (colored, True, has_uv)
                new, has_color, has_uv = mesh_base[key]
        rot_key = tuple(round(float(x), 4) for x in rot)
        # a blended material's alpha goes into the vertices where the mesh has vertex colours (an additive
        # material's goes into its RGB, a cut-out's into the threshold: see `material`)
        in_vertex = [bool(d and opt.color_alpha_to_vertex and opt.bake_vertex_colors and has_color and d['tint'][3] != 1.0
                          and d['kind'] == 'transparent') for d in slots]
        ops = []
        for i in range(len(new['m_SubMeshes'])):
            j = min(i, len(slots) - 1)
            d = slots[j] if slots else None
            if d is None:
                ops.append(PLAIN_OP)
            else:
                ops.append((d['rule']['vc'] if opt.bake_vertex_colors and has_color else 'raw', float(d['tint'][3]) if in_vertex[j] else 1.0,
                            d['uv'] if opt.bake_uvs and has_uv else IDENTITY_UV,
                            rot_key if want_light and has_color and d['rule']['lit'] else None))
        ops = tuple(ops)
        lit = [bool(d) and ops[min(i, len(ops) - 1)][3] is not None if ops else False for i, d in enumerate(slots)]
        if (key, ops) not in mesh_ids:
            plain = all(o == PLAIN_OP for o in ops)
            edit = None if plain else edited_mesh(new, ops, light)
            if edit is None:                    # the mesh as it is (one object for all who want it so)
                if not plain:
                    count('dropped', 'mesh layout not understood (colours / UVs not baked)')
                if (key, None) not in mesh_ids:
                    mesh_ids[(key, None)] = (sh.add('Mesh', new), False)
                mesh_ids[(key, ops)] = mesh_ids[(key, None)]
            else:
                stats['vertex_clashes'] += edit[1]
                stats['mesh_copies'] += 1
                stats['color_baked'] += any(o[0] != 'raw' or o[1] != 1.0 for o in ops)
                stats['uv_baked'] += any(o[2] != IDENTITY_UV for o in ops)
                stats['alpha_to_vertex'] += any(o[1] != 1.0 for o in ops)
                stats['vertex_lit'] += any(o[3] is not None for o in ops)
                mesh_ids[(key, ops)] = (sh.add('Mesh', edit[0]), True)
        pid, edited = mesh_ids[(key, ops)]
        return pid, in_vertex if edited else [False] * len(slots), lit if edited else [False] * len(slots)

    return types.SimpleNamespace(count=count, texture=texture, describe=describe, material=material, mesh=mesh, tex_ids=tex_ids, white=white,
                                 mat_ids=mat_ids, mesh_ids=mesh_ids)


# ------------------------------------------------------------------------------------------------- conversion

class BackgroundConverter:
    def __init__(self, mania_dir, aa_switch):
        """mania_dir: the Banana Mania install; aa_switch: <Rumble>_Data/StreamingAssets/aa/Switch (converted tree;
        its catalog.json is expected one folder up)."""
        self.mania_dir, self.aa = mania_dir, aa_switch
        self._data = None

    # ---- tables
    @property
    def data(self):
        if self._data is None:
            self._data = cached(('data', self.mania_dir), lambda: ManiaData(self.mania_dir))
        return self._data

    def names(self):
        """The Mania background names in use, sorted: a background's place in this list is its number."""
        return sorted({s['bg'] for s in self.data.stages.values()})

    def identity(self, bg_name):
        """What names a background's two scenes: numbers, bundle paths (below the output folder), internal names."""
        n = self.names().index(bg_name)
        far, light = FAR_SCENE_BASE + n, LIGHT_SCENE_BASE + n
        return {'name': bg_name, 'index': n, 'far_scene': far, 'light_scene': light,
                'far_bundle': f'{BUNDLE_DIR}/bg_{far}.bundle', 'light_bundle': f'{BUNDLE_DIR}/bg_{light}.bundle'}

    def stages(self, bg_name):
        return sorted(i for i, s in self.data.stages.items() if s['bg'] == bg_name)

    def moved_stages(self, bg_name):
        """{stage id: placement} of the stages whose BgRoot prefab puts the background somewhere else than the origin
        (which this converter ignores): 'root' = the prefab root's position, 'pos' / 'rot' / 'scale' = its child trs."""
        out = {}
        for sid in self.stages(bg_name):
            bundle = self.data.bundles.get(sid)
            if not bundle:
                continue
            want = os.path.splitext(os.path.basename(self.data.stages[sid]['bgroot']))[0]
            sf = next(iter(serialized_files(UnityPy.load(os.path.join(self.mania_dir, BUNDLES, bundle))).values()), None)
            if sf is None:
                continue
            for o in sf.objects.values():
                if o.type.name != 'GameObject' or o.peek_name() != want:
                    continue
                tr = next(sf.objects[c['component']['m_PathID']].read_typetree() for c in o.read_typetree()['m_Component']
                          if sf.objects[c['component']['m_PathID']].type.name == 'Transform')
                place = {'root': [round(tr['m_LocalPosition'][k], 4) for k in 'xyz']}
                for ch in tr['m_Children'][:1]:
                    c = sf.objects[ch['m_PathID']].read_typetree()
                    place.update(pos=[round(c['m_LocalPosition'][k], 4) for k in 'xyz'], rot=[round(c['m_LocalRotation'][k], 4) for k in 'xyzw'],
                                 scale=[round(c['m_LocalScale'][k], 4) for k in 'xyz'])
                still = {'root': [0, 0, 0], 'pos': [0, 0, 0], 'scale': [1, 1, 1]}
                if any(place.get(k, v) != v for k, v in still.items()) or abs(abs(place.get('rot', [0, 0, 0, 1])[3]) - 1) > 1e-4:
                    out[sid] = place
        return out

    # ---- one background
    def convert(self, bg_name, out_dir, log=None, **tunables):
        """Convert Mania's background `bg_name` ('Smb1_Jungle') and write its two bundles below out_dir.

        tunables: any upper-case constant of this module, by its lower-case name. Returns a dict: the scene numbers
        and bundle paths (`identity`), 'far_deps' / 'light_deps' (the other bundles each scene needs loaded, as paths
        like the catalog's, 'Switch/...'), 'far_template' / 'light_template', 'moved_stages', 'stats'."""
        opt = options(tunables)
        say = log or (lambda *a: None)
        row = self.data.backgrounds[bg_name]
        info = self.identity(bg_name)
        bundle = 'bg_' + '_'.join(row['prefab'].replace('\\', '/').split('/')[1:3]).lower()     # Bg/smb1/Jungle/... -> bg_smb1_jungle
        t0 = time.time()
        m = ManiaBackground(self.mania_dir, bundle, row['prefab'], row['light'])
        rs = render_settings(self.mania_dir, row['light_scene'])
        lights = mania_lights(m)
        stats = {'bundle': bundle}
        info['far_template'] = opt.far_template
        info['light_template'] = tunables.get('light_template') or opt.light_template_of_bg.get(bg_name, opt.light_template)
        stats['far'], info['far_deps'] = self._far(m, rs, lights, info, out_dir, opt)
        t1 = time.time()
        stats['light'], info['light_deps'] = self._light(m, rs, lights, info, out_dir, opt)
        stats['seconds'] = {'far': round(t1 - t0, 2), 'light': round(time.time() - t1, 2)}
        info['moved_stages'] = self.moved_stages(bg_name) if opt.find_moved_stages else None
        info['stages'] = len(self.stages(bg_name))
        info['stats'] = stats
        say(info)
        return info

    def _dependencies(self, sc, candidates):
        """The bundles (paths below aa, 'Switch/...') among `candidates` that hold a file the finished scene `sc`
        refers to; every reference must be found in one of them."""
        need, out = sc.external_cabs(), []
        for rel in candidates:
            cabs = bundle_cabs(os.path.join(self.aa, rel[len('Switch/'):].replace('/', os.sep)))
            if any(c in cabs for c in need) and rel not in out:
                out.append(rel)
                need = [c for c in need if c not in cabs]
        if need:
            raise ValueError(f'no bundle known for the referenced file(s) {need}')
        return out

    def light_bake(self, bg_name, rs, lights, opt):
        """The constant (linear RGB) that stands for Mania's light on a formerly lit material."""
        fixed = opt.light_bake_of_bg.get(bg_name, opt.light_bake)
        if not isinstance(fixed, str):
            return np.ones(3) * np.asarray(fixed, dtype=np.float64)
        sky, equator, ground = ambient_colors(rs)
        direct = sum((light_energy(x, opt) for x in lights['bg']), np.zeros(3))
        f = opt.light_bake_gain * (opt.light_bake_ambient * (sky + 2 * equator + ground) / 4 + opt.light_bake_ndotl * direct)
        return f * min(1.0, opt.light_bake_max / max(float(f.max()), 1e-9))

    # ---- far scenery
    def _far(self, m, rs, lights, info, out_dir, opt):
        sc = BgScene(os.path.join(self.aa, f'scene_{opt.far_template}_scenes_all.bundle'))
        s, sh = sc.scene, sc.shared
        root = next(g for g in sc.roots() if sc.component(g, 'MonoBehaviour', 'MainGameBg'))
        init = next(g for g in sc.roots() if sc.component(g, 'MonoBehaviour', 'MainGameInitializer'))
        # models for new objects, taken before the template's content goes
        for cls in ('GameObject', 'Transform', 'MeshFilter', 'MeshRenderer', 'Animator'):
            s.donor(cls)
        s.donor('MonoBehaviour', 'ReplayTracker')
        for cls in ('Mesh', 'Material', 'Texture2D', 'AnimationClip', 'AnimatorController'):
            sh.donor(cls)

        # ---- the template's scenery goes: every object but the root (with MainGameBg) and the initializer, the
        # lightmaps, the combined meshes of its static batches
        for g in sc.roots():
            if g not in (root, init):
                sc.delete(g)
        for c in sc.children(root):
            sc.delete(c)
        for c in sc.components(root):
            o = s.sf.objects[c]
            if o.type.name != 'Transform' and not (o.type.name == 'MonoBehaviour' and s.script_class(o) == 'MainGameBg'):
                sc.remove_component(root, c)
        for o in s.objects('LightmapSettings'):
            s.get(o.path_id)['m_Lightmaps'] = []
        for o in s.objects('Mesh'):
            s.remove(o.path_id)
        s.get(root).update(m_Name=m.bg.name, m_Layer=LAYER_BG, m_IsActive=True)
        sc.set_transform(root, m.bg.pos, m.bg.rot, scale=m.bg.scale)

        stats = {'nodes': 0, 'renderers': 0, 'kinds': {}, 'shaders': {}, 'unmapped': {}, 'skipped': {}, 'dropped': {}, 'scroll': 0, 'lit': 0,
                 'mesh_copies': 0, 'uv_baked': 0, 'color_baked': 0, 'alpha_to_vertex': 0, 'alpha_in_material': 0, 'vertex_clashes': 0,
                 'queues': {}}
        bake = self.light_bake(info['name'], rs, lights, opt)
        stats['light_bake'] = [round(float(x), 3) for x in bake]
        vertex_lit = opt.light_bake_of_bg.get(info['name'], opt.light_bake) == 'vertex'
        bg_lights = [(np.asarray(x['dir'], dtype=np.float64), light_energy(x, opt)) for x in lights['bg']]
        stats['vertex_lit'] = 0

        def vertex_light(normals, rot):
            """Mania's light on vertices with the mesh normals `normals` of a node with the world rotation `rot`, as
            the factor that goes into the vertex colour (light / light_vertex_range, 0..1)."""
            n = np.array([qrot(rot, (1.0, 0.0, 0.0)), qrot(rot, (0.0, 1.0, 0.0)), qrot(rot, (0.0, 0.0, 1.0))], dtype=np.float64)
            world = normals @ n                 # rows of n are the images of the axes
            world /= np.maximum(np.linalg.norm(world, axis=1, keepdims=True), 1e-9)
            out = ambient_at(rs, world) * opt.light_bake_ambient
            for direction, energy in bg_lights:
                out = out + np.maximum(-(world @ direction), 0.0)[:, None] * energy
            return np.clip(out * opt.light_bake_gain / opt.light_vertex_range, 0.0, 1.0)
        assets = scenery_assets(sc, m, opt, self.aa, stats, bake, vertex_light if vertex_lit else None)
        count, describe, material, mesh = assets.count, assets.describe, assets.material, assets.mesh
        tex_ids, white, mat_ids, mesh_ids, clip_ids = assets.tex_ids, assets.white, assets.mat_ids, assets.mesh_ids, {}

        def controller(sf, ref):
            """Mania's AnimatorController (one layer, one state, one clip) with its clips, carried over as stage
            motion is; (path id or 0 when the clips move nothing, the path hashes the clips are bound to)."""
            got = m.get(sf, ref)
            if got is None:
                return 0, set()
            _, t, csf, _ = got
            new = overlay(sh.template('AnimatorController'), t)
            new['m_AnimationClips'], bound = [], set()
            for c in t['m_AnimationClips']:
                g = m.get(csf, c)
                if g is None:
                    new['m_AnimationClips'].append(dict(NULL))
                    continue
                if g[0] not in clip_ids:
                    clip_ids[g[0]] = sh.add('AnimationClip', overlay(sh.template('AnimationClip'), g[1]))
                new['m_AnimationClips'].append(pptr(clip_ids[g[0]]))
                bound.update(b['path'] for b in g[1]['m_ClipBindingConstant']['genericBindings'])
            return (sh.add('AnimatorController', new) if bound else 0), bound

        drawn = {}

        def draws(n):
            """Has this node a mesh to draw? (two backgrounds carry a renderer with an empty mesh)"""
            mf, mr = n.component('MeshFilter'), n.component('MeshRenderer')
            got = m.get(m.main, mf[2]['m_Mesh']) if mf and mr else None
            return bool(got and got[1]['m_VertexData']['m_VertexCount'])

        def has_drawn(n):
            """Is there anything to draw at or below this node?"""
            if n.id not in drawn:
                drawn[n.id] = draws(n) or any([has_drawn(c) for c in n.children])
            return drawn[n.id]

        animators = []

        def copy_node(n, parent):
            go = sc.new_object(n.name, parent, n.pos, n.rot, n.scale, n.active)
            stats['nodes'] += 1
            mf, mr = n.component('MeshFilter'), n.component('MeshRenderer')
            if mr and not draws(n):
                count('skipped', 'MeshRenderer without a mesh')
            if draws(n):
                slots = [describe(m.main, x) for x in mr[2]['m_Materials']]
                mesh_id, in_vertex, lit = mesh(m.main, mf[2]['m_Mesh'], slots, world_rotation(n))
                sc.add_component(go, 'MeshFilter', {'m_Mesh': sc.shared_ref(mesh_id)})
                r = s.template('MeshRenderer')
                r.update(m_Enabled=bool(mr[2]['m_Enabled']), m_CastShadows=0, m_ReceiveShadows=0, m_StaticShadowCaster=0, m_LightProbeUsage=0,
                         m_ReflectionProbeUsage=0, m_LightmapIndex=65535, m_LightmapIndexDynamic=65535,
                         m_LightmapTilingOffset={'x': 1.0, 'y': 1.0, 'z': 0.0, 'w': 0.0}, m_LightmapTilingOffsetDynamic={'x': 1.0, 'y': 1.0, 'z': 0.0, 'w': 0.0},
                         m_Materials=[sc.shared_ref(material(d, v, l)) if d else dict(NULL) for d, v, l in zip(slots, in_vertex, lit)],
                         m_StaticBatchInfo={'firstSubMesh': 0, 'subMeshCount': 0}, m_StaticBatchRoot=dict(NULL), m_ProbeAnchor=dict(NULL),
                         m_LightProbeVolumeOverride=dict(NULL), m_SortingLayerID=0, m_SortingLayer=0, m_SortingOrder=int(mr[2].get('m_SortingOrder', 0)),
                         m_AdditionalVertexStreams=dict(NULL), m_EnlightenVertexStream=dict(NULL))
                sc.add_component(go, 'MeshRenderer', r)
                stats['renderers'] += 1
            anim = n.component('Animator')
            if anim:
                animators.append((n, go, anim[2]['m_Controller']))
            for kind in {c[0] for c in n.components} - {'Transform', 'MeshFilter', 'MeshRenderer', 'Animator'}:
                count('skipped', kind)                  # particle systems, MgBgOptimizer
            for c in n.children:
                if has_drawn(c):
                    copy_node(c, go)
                else:
                    skip_tree(c)
            return go

        def skip_tree(n):
            for x in n.walk():
                for kind in {c[0] for c in x.components} - {'Transform'}:
                    count('skipped', kind)

        for c in m.bg.children:
            if c.name in opt.skip_children or not has_drawn(c):
                skip_tree(c)
                count('skipped', f'subtree {c.name}')
            else:
                copy_node(c, root)

        # ---- motion: an Animator (driven like Rumble's own far scenery: update mode 1, no avatar, a ReplayTracker
        # next to it) where the clip is bound to something, and the tag StgMot on what it moves
        stats.update(animators=0, animated_bindings=0, tagged=0)
        for n, go, ref in animators:
            ctrl, bound = controller(m.main, ref)
            if not ctrl:
                continue
            a = s.template('Animator')
            a.update(m_Enabled=1, m_Avatar=dict(NULL), m_Controller=sc.shared_ref(ctrl), m_CullingMode=0, m_UpdateMode=1, m_ApplyRootMotion=False)
            aid = sc.add_component(go, 'Animator', a)
            tracker = s.template('MonoBehaviour', 'ReplayTracker')
            tracker['m_RecordProperties']['m_AnimatorProperty'] = {'m_Animator': pptr(aid), 'm_isSelfUpdate': 0}
            sc.add_component(go, 'MonoBehaviour', tracker, 'ReplayTracker')
            stats['animators'] += 1
            stats['animated_bindings'] += len(bound)

            def tag(g, path, moving):
                moving = moving or (zlib.crc32(path.encode('utf-8')) & 0xffffffff) in bound
                if moving and opt.tag_animated:
                    s.get(g)['m_Tag'] = TAG_STGMOT
                    stats['tagged'] += 1
                for ch in sc.children(g):
                    tag(ch, (path + '/' if path else '') + sc.name(ch), moving)
            tag(go, '', False)

        out = os.path.join(out_dir, info['far_bundle'].replace('/', os.sep))
        n = info['far_scene']
        stats['bytes'] = sc.save(out, f'mania_bg_{n}', f'Assets/Mania/{n}.unity', 'CAB-' + md5(f'mania bg {n}'))
        stats.update(textures=len(tex_ids) + len(white), materials=len(mat_ids), meshes=len({v[0] for v in mesh_ids.values()}), clips=len(clip_ids))
        return stats, self._dependencies(sc, [f'Switch/{UNLIT_SHADER_BUNDLE}', f'Switch/{BUILTIN_SHADER_BUNDLE}'])

    # ---- lighting
    def _light(self, m, rs, lights, info, out_dir, opt):
        template = info['light_template']
        sc = BgScene(os.path.join(self.aa, f'scene_{template}_scenes_all.bundle'), layer=0)
        s, sh = sc.scene, sc.shared
        stats = {'lights': {}}

        # ---- the lights. Rumble's slots, by the object's name (the names vary a little between worlds: "Stage_MainLight1")
        slots = {}
        for o in s.objects('Light'):
            t = s.get(o.path_id)
            name = sc.name(t['m_GameObject']['m_PathID'])
            role = next((r for key, r in (('Stage_MainLight', 'key'), ('BackLight', 'back'), ('Chara_MainLight', 'chara'), ('Far_MainLight', 'far'))
                         if name.startswith(key)), None)
            if role and (role not in slots or sc.scene.get(t['m_GameObject']['m_PathID'])['m_IsActive'] and t['m_Enabled']):
                slots[role] = (t['m_GameObject']['m_PathID'], t)
        sources = {'key': lights['key'], 'back': lights['back'], 'chara': lights['chara'][:1], 'far': lights['bg']}
        for role, (go, t) in slots.items():
            src = sources[role]
            if not src:
                stats['lights'][role] = 'kept (Mania has none)'
                continue
            col, energy, rot = merged_light(src, opt)
            if opt.light_intensity == 'mania':
                t['m_Intensity'] = float(min(energy * opt.light_exposure * getattr(opt, 'light_scale_' + role), opt.light_intensity_max))
            if opt.light_colors == 'mania':
                t['m_Color'] = color(col, t['m_Color']['a'])
            if opt.light_directions == 'mania':
                sc.set_world_rotation(go, rot)
            if role == 'key' and opt.shadow_strength != 'template':
                t['m_Shadows']['m_Strength'] = float(src[0]['strength'] if opt.shadow_strength == 'mania' else opt.shadow_strength)
            stats['lights'][role] = {'from': [x['name'] for x in src], 'color': [round(float(x), 3) for x in col], 'intensity': round(t['m_Intensity'], 3),
                                     'dir': [round(float(x), 3) for x in qrot(rot, (0.0, 0.0, 1.0))], 'mask': hex(t['m_CullingMask']['m_Bits'])}
        stats['lights']['not converted'] = [x['name'] for x in lights['chara'][1:]]
        # the key light must stay URP's main light: it is the one that casts the shadows
        key = slots.get('key')
        if key and opt.light_others_below_key is not None:
            limit = key[1]['m_Intensity'] * opt.light_others_below_key
            for o in s.objects('Light'):
                t = s.get(o.path_id)
                if t is not key[1] and t['m_Type'] == 1 and t['m_Intensity'] > limit:
                    stats['lights'].setdefault('held below the key light', {})[sc.name(t['m_GameObject']['m_PathID'])] = round(t['m_Intensity'], 3)
                    t['m_Intensity'] = float(limit)
        for role, (go, t) in slots.items():
            if isinstance(stats['lights'].get(role), dict):
                stats['lights'][role]['intensity'] = round(t['m_Intensity'], 3)

        # ---- RenderSettings: ambient light, fog, the sky
        r = next(s.get(o.path_id) for o in s.objects('RenderSettings'))
        if key and opt.sun_is_key_light:
            r['m_Sun'] = pptr(sc.component(key[0], 'Light'))
        if opt.ambient == 'mania':
            cols = [np.minimum(linear_to_srgb(c * opt.light_exposure * opt.ambient_gain), 1.0) for c in ambient_colors(rs)]
            r['m_AmbientMode'] = 1
            for k, c in zip(('m_AmbientSkyColor', 'm_AmbientEquatorColor', 'm_AmbientGroundColor'), cols):
                r[k] = color(c)
            r['m_AmbientIntensity'] = 1.0
        stats['ambient'] = {'mania_mode': rs['m_AmbientMode'],
                            **{k: [round(r[f'm_Ambient{k}Color'][c], 3) for c in 'rgb'] for k in ('Sky', 'Equator', 'Ground')}}
        fog_color = rgb(rs['m_FogColor'])
        start, end = rs['m_LinearFogStart'] * opt.fog_distance_scale, rs['m_LinearFogEnd'] * opt.fog_distance_scale
        fog_parts = [sh.get(o.path_id) for o in sh.objects('MonoBehaviour') if sh.script_class(o) == 'Fog']    # of the Volume profile
        mode = opt.fog
        if mode == 'volume' and not fog_parts:
            mode = 'render_settings'
            stats['fog_note'] = f'{template} has no SC Fog in its Volume profile: RenderSettings fog instead'
        if mode != 'template':
            on = bool(rs['m_Fog']) and mode != 'off'
            r.update(m_Fog=on and mode == 'render_settings', m_FogMode=1, m_FogDensity=float(opt.fog_density), m_FogColor=color(fog_color), m_LinearFogStart=float(start), m_LinearFogEnd=float(end))
            for f in fog_parts:
                f['active'] = int(on and mode == 'volume')
                if on and mode == 'volume':
                    for k, v in (('useSceneSettings', 0), ('fogMode', 1), ('fogStartDistance', float(start)),
                                 ('fogEndDistance', float(max(end, opt.fog_volume_min_end))), ('colorSource', 0), ('fogColor', color(fog_color)),
                                 ('distanceFog', 1), ('heightFog', 0), ('skyboxInfluence', 0.0)):
                        f[k] = {**f[k], 'm_OverrideState': 1, 'm_Value': v}
        stats['fog'] = {'mode': mode, 'mania_on': bool(rs['m_Fog']), 'color': [round(float(x), 3) for x in fog_color], 'start': start, 'end': end,
                        'render_settings': bool(r['m_Fog']), 'volume': [f['active'] for f in fog_parts]}
        if opt.reflection_intensity is not None:
            r['m_ReflectionIntensity'] = float(opt.reflection_intensity)

        # the skybox: the template's Skybox/Cubemap material with its cubemap made one flat colour (in place: the
        # material and the cubemap keep their objects, the cubemap's megabytes go)
        sky = sh.get(r['m_SkyboxMaterial']['m_PathID'])
        props = sky['m_SavedProperties']
        tex = pairs(props['m_TexEnvs']).get('_Tex')
        if r['m_SkyboxMaterial']['m_FileID'] != sc.shared_fid or tex is None or not tex['m_Texture']['m_PathID']:
            raise ValueError(f'{template}: the skybox material is not a Skybox/Cubemap material of the scene')
        sky_color = (fog_color if rs['m_Fog'] else np.zeros(3)) if isinstance(opt.sky_color, str) else np.asarray(opt.sky_color, dtype=np.float64)
        size = int(opt.sky_cubemap_size)
        cube = sh.get(tex['m_Texture']['m_PathID'])
        texel = bytes(int(round(min(max(float(x), 0.0), 1.0) * 255)) for x in sky_color) + b'\xff'
        cube.update({'m_Name': 'mania_sky_' + info['name'], 'm_Width': size, 'm_Height': size, 'm_CompleteImageSize': size * size * 4,
                     'm_TextureFormat': 4, 'm_MipCount': 1, 'm_MipsStripped': 0, 'm_ImageCount': 6, 'm_ColorSpace': 1, 'm_IsReadable': False,
                     'm_StreamingMipmaps': False, 'image data': texel * (size * size * 6), 'm_StreamData': dict(NO_STREAM)})
        if 'm_PlatformBlob' in cube:
            cube['m_PlatformBlob'] = []
        sky['m_Name'] = 'mania_sky_' + info['name']
        props['m_Floats'] = [(k, {'_Exposure': float(opt.sky_exposure), '_Rotation': 0.0}.get(k, v)) for k, v in props['m_Floats']]
        props['m_Colors'] = [(k, color(opt.sky_tint) if k == '_Tint' else v) for k, v in props['m_Colors']]
        stats['sky_color'] = [round(float(x), 3) for x in sky_color]

        out = os.path.join(out_dir, info['light_bundle'].replace('/', os.sep))
        n = info['light_scene']
        stats['bytes'] = sc.save(out, f'mania_bg_{n}', f'Assets/Mania/{n}.unity', 'CAB-' + md5(f'mania bg {n}'))
        # what the scene needs loaded is what the template's scene needs, as the catalog lists it
        cat = cached(('catalog', self.aa), lambda: load_catalog(os.path.join(os.path.dirname(self.aa), 'catalog.json')))
        loc = cat.locations(template)
        if not loc:
            raise ValueError(f'{template} is not in the catalog')
        candidates = [cat.entry(e)['id'][len(RT) + 1:] for e in cat.buckets[loc[0]['dep']][1:]]
        return stats, self._dependencies(sc, candidates)


# ---------------------------------------------------------------------------------------- stage rows, catalog

def stage_fields(info):
    """The Stage-row fields of a stage that uses the converted background `info` (what `convert` returned).

    The far and lighting scenes are the converted ones, for split screen as well (they are light enough). The sky
    scene is the game's own empty one: Mania's sky is the dome in the far scene. No effect scene and no screen effect:
    Mania's particle systems and camera weather are not converted (an empty EffectSceneID is what world 7's rows
    have, empty screen effects what worlds 9 and 10 have)."""
    far, light = str(info['far_scene']), str(info['light_scene'])
    return {'FarSceneID': far, 'LightSceneID': light, 'SkySceneID': EMPTY_SKY_SCENE, 'EffectSceneID': '', 'ScreenEffectAssetRef': ['', '', ''],
            'FarSceneSplitScreenID': far, 'LightSceneSplitScrenID': light, 'SkySceneSplitScreenID': EMPTY_SKY_SCENE,
            'EffectSceneSplitScreenID': '', 'ScreenEffectSplitScreenAssetRef': ['', '', '']}


def add_to_catalog(cat, info, out_dir):
    """Add the two bundles and the two scenes of a converted background to an aacatalog.Catalog, the way the game's
    own scenery scenes are listed (and build.add_scenes lists stage scenes): a bundle location (AssetBundleProvider,
    with its AssetBundleRequestOptions) and a scene location (BundledAssetProvider, SceneInstance) under the scene's
    number, depending on a key whose bucket is the scene's own bundle followed by the bundles it refers to."""
    model = cat.locations(info['far_template'])[0]              # a scene of the game: provider, resource type
    own = cat.buckets[model['dep']][0]                          # ... and its bundle's location
    asm, cls, opts = cat.extra_json(cat.entries[own][4])
    prov_bundle, rt_bundle = cat.entries[own][1], cat.entries[own][6]
    by_id = {cat.ids[e[0]]: i for i, e in enumerate(cat.entries)}
    for kind in ('far', 'light'):
        name, rel = str(info[f'{kind}_scene']), info[f'{kind}_bundle']
        deps = []
        for d in info[f'{kind}_deps']:
            if RT + '/' + d not in by_id:
                raise KeyError(f'{d} (needed by scene {name}) is not in the catalog')
            deps.append(by_id[RT + '/' + d])
        size = os.path.getsize(os.path.join(out_dir, rel.replace('/', os.sep)))
        o = dict(opts, m_Hash=md5('mania ' + name), m_Crc=0, m_BundleName=f'mania_bg_{name}', m_BundleSize=size)
        primary = rel[len('Switch/'):]
        depkey = 'mania-deps-' + name
        cat.add_entry(RT + '/' + rel, prov_bundle, None, cat.add_extra_json(asm, cls, o), primary, rt_bundle, [primary, depkey])
        cat.buckets[cat.add_key(depkey)] += deps
        cat.add_entry(f'Assets/Mania/{name}.unity', model['prov'], depkey, -1, name, model['rt'], [name])


if __name__ == '__main__':
    import json
    if len(sys.argv) < 4:
        sys.exit('usage: background.py <Banana Mania folder> <aa/Switch folder> <output folder> [background name ...]')
    conv = BackgroundConverter(sys.argv[1], sys.argv[2])
    for bg in sys.argv[4:] or conv.names():
        print(json.dumps(conv.convert(bg, sys.argv[3]), default=str))
