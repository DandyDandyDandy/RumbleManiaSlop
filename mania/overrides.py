"""What a person decided about the imported stages and worlds: mania\\overrides.json.

Banana Mania's stages lack things Banana Rumble's have, and the import cannot derive them: the three stage missions
(a challenge time, a banana count, a Golden Banana) and the look of a world in the menus. The editor
(mania\\editor.py) writes them into this file and mania\\build.py reads it:

    {"stages":  {"<Mania stage id>": {"gold": "<path of the banana that becomes the Golden Banana>",
                                      "time": <seconds of the time mission>,
                                      "time_perfect": <seconds for the mission's perfect mark; default: 45 % of time>,
                                      "bananas": <bananas of the banana mission; default: 75 % of the stage's>,
                                      "picture": "<file>"}},
     "courses": {"<Mania course name>": {"missions": true | false,
                                         "theme": <Rumble course id>, "thumbnail": "mania" | <Rumble course id>,
                                         "brochure": <id>, "icon": <id> | 0, "title": <id> | 0,
                                         "picture": "<file>", "big_picture": "<file>", "icon_picture": "<file>"}}}

Everything is optional. A course has stage missions when "missions" says so, and without the key when one of its
stages has a "gold" or a "time". "theme" is the Rumble world whose graphics the course borrows (the picture beside
the list in Select World, the world icon, the title card when a stage loads); "brochure", "icon" and "title" each
name another world for one of them, and 0 leaves the icon or the title card out. "thumbnail" is the course's small
picture in Select World: Banana Mania's own ("mania", the default where Mania has one) or a Rumble world's.

Pictures of one's own go before all of that: "picture" of a stage is its thumbnail in Select Stage, "picture",
"big_picture" and "icon_picture" of a course its small picture, the big picture beside the lists and the world
icon. Each names a PNG file in input\\pictures\\ (the editor puts uploads there, cut to the shape the game shows;
the folder is the user's and not part of the repository). A file that is missing is passed over.
"""
import json
import math
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.path.join(HERE, 'overrides.json')
PICTURES = os.path.join(os.path.dirname(HERE), 'input', 'pictures')
PICTURE_NAME = re.compile(r'[A-Za-z0-9_]{1,100}\.png')
# the shapes the game shows them in: (width, height, with transparency)
PICTURE_SHAPES = {'picture': (512, 512, False), 'big_picture': (804, 1004, False), 'icon_picture': (132, 132, True)}
# 'view': where a stage's picture was taken from in the editor's 3D view, for the picture the import takes in the
# game (thumbshot.py): eye x y z, point looked at x y z (stage coordinates), vertical field of view in degrees
STAGE_KEYS = {'gold': str, 'time': (int, float), 'time_perfect': (int, float), 'bananas': int, 'picture': str, 'view': list}
COURSE_KEYS = {'missions': bool, 'theme': int, 'thumbnail': (int, str), 'brochure': int, 'icon': int, 'title': int,
               'picture': str, 'big_picture': str, 'icon_picture': str}


def clean(data):
    """`data` with only the known keys of the right type; raises ValueError on a file of another shape."""
    if not isinstance(data, dict):
        raise ValueError('overrides: not an object')
    out = {'stages': {}, 'courses': {}}
    for section, keys in (('stages', STAGE_KEYS), ('courses', COURSE_KEYS)):
        entries = data.get(section, {})
        if not isinstance(entries, dict):
            raise ValueError(f'overrides: "{section}" is not an object')
        for name, entry in entries.items():
            if not isinstance(entry, dict):
                raise ValueError(f'overrides: {section}/{name} is not an object')
            kept = {}
            for k, v in entry.items():
                if k not in keys or v is None or v == '':
                    continue
                if keys[k] is list:
                    if not (isinstance(v, list) and len(v) == 7 and all(isinstance(x, (int, float)) and not isinstance(x, bool)
                                                                         and abs(x) < 1e6 for x in v) and 1 <= v[6] <= 170):
                        raise ValueError(f'overrides: {section}/{name}/{k} is not a view (seven numbers)')
                    kept[k] = [round(float(x), 4) for x in v]
                    continue
                if isinstance(v, bool) != (keys[k] is bool) or not isinstance(v, keys[k]):
                    raise ValueError(f'overrides: {section}/{name}/{k} has the wrong type')
                if isinstance(v, (int, float)) and not isinstance(v, bool) and (v < 0 or v > 100000):
                    raise ValueError(f'overrides: {section}/{name}/{k} is out of range')
                if k in PICTURE_SHAPES and not PICTURE_NAME.fullmatch(v):
                    raise ValueError(f'overrides: {section}/{name}/{k} is not the name of a PNG file')
                kept[k] = v
            if kept:
                out[section][str(name)] = kept
    return out


def load(path=None):
    path = path or PATH
    if not os.path.exists(path):
        return {'stages': {}, 'courses': {}}
    with open(path, encoding='utf-8') as f:
        return clean(json.load(f))


def save(data, path=None):
    """Write the file (keys sorted, one entry a line: changes read well in a diff)."""
    data = clean(data)
    lines = ['{']
    for i, section in enumerate(('stages', 'courses')):
        lines.append(f' "{section}": {{')
        entries = sorted(data[section].items(), key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0]))
        for k, (name, entry) in enumerate(entries):
            lines.append(f'  {json.dumps(name)}: {json.dumps(entry, sort_keys=True)}' + (',' if k + 1 < len(entries) else ''))
        lines.append(' }' + (',' if i == 0 else ''))
    lines.append('}')
    tmp = (path or PATH) + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, path or PATH)


def picture(entry, key):
    """The user's picture an entry names under `key` as an image, or None (no such key, or the file is missing)."""
    name = entry.get(key)
    path = os.path.join(PICTURES, name) if name and PICTURE_NAME.fullmatch(name) else None
    if not path or not os.path.exists(path):
        return None
    from PIL import Image
    with Image.open(path) as img:
        return img.convert('RGBA')


def fit_picture(img, key):
    """An uploaded picture in the shape the game shows it in: the small pictures and the big one fill their frame
    (the middle is kept, what sticks out is cut), the icon is fitted whole into its square, keeping transparency."""
    from PIL import Image, ImageOps
    w, h, alpha = PICTURE_SHAPES[key]
    img = ImageOps.exif_transpose(img).convert('RGBA')
    if not alpha:
        ground = Image.new('RGBA', img.size, (0, 0, 0, 255))
        ground.alpha_composite(img)
        return ImageOps.fit(ground, (w, h), Image.LANCZOS).convert('RGB')
    # the game's icons leave a few pixels free at the rim (the sprite's rectangle is smaller than the texture)
    inner = ImageOps.contain(img, (w - 12, h - 12), Image.LANCZOS)
    out = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    out.alpha_composite(inner, ((w - inner.width) // 2, (h - inner.height) // 2))
    return out


def gold(data, stage_id):
    return data['stages'].get(str(stage_id), {}).get('gold')


def has_missions(data, course_name, stage_ids):
    """Whether the course shows Rumble's stage missions."""
    c = data['courses'].get(course_name, {})
    if 'missions' in c:
        return c['missions']
    return any(k in data['stages'].get(str(i), {}) for i in stage_ids for k in ('gold', 'time'))


def default_time(time_limit):
    """The time mission of a stage nobody set one for: half of the stage's time limit."""
    return float(math.floor(time_limit / 2))


# Rumble sets its mission values by hand per stage; there is no formula. Over its 200 Adventure and challenge
# stages (game 2.20) the banana mission asks for a median 76 % of what the stage's bananas are worth (most often a
# multiple of 5), and the time mission's perfect mark is a median 45 % of its challenge time (one decimal). The
# defaults follow those medians. The perfect mark of the banana mission is always all of them (the game decides).
BANANA_SHARE, PERFECT_SHARE = 0.75, 0.45


def default_bananas(banana_count):
    n = banana_count * BANANA_SHARE
    return int(n // 5 * 5) if n >= 10 else max(1, int(math.ceil(n))) if banana_count else 0


def default_perfect(time):
    return max(0.1, round(time * PERFECT_SHARE, 1))


def missions(data, stage_id, time_limit, banana_count):
    """(time, perfect time, bananas) of the stage's missions. banana_count: what all its bananas are worth."""
    s = data['stages'].get(str(stage_id), {})
    t = float(s.get('time') or default_time(time_limit))
    perfect = float(s.get('time_perfect') or default_perfect(t))
    bananas = s['bananas'] if 'bananas' in s else default_bananas(banana_count)
    return t, min(perfect, t), max(0, min(int(bananas), int(banana_count)))
