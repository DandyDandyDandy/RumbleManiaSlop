"""What a person decided about the imported stages and worlds: mania\\overrides.json.

Banana Mania's stages lack things Banana Rumble's have, and the import cannot derive them: the three stage missions
(a challenge time, a banana count, a Golden Banana) and the look of a world in the menus. The editor
(mania\\editor.py) writes them into this file and mania\\build.py reads it:

    {"stages":  {"<Mania stage id>": {"gold": "<path of the banana that becomes the Golden Banana>",
                                      "time": <seconds of the time mission>,
                                      "time_perfect": <seconds for the mission's perfect mark; default: time>,
                                      "bananas": <bananas of the banana mission; default: half of the stage's>}},
     "courses": {"<Mania course name>": {"missions": true | false,
                                         "theme": <Rumble course id>, "thumbnail": "mania" | <Rumble course id>,
                                         "brochure": <id>, "icon": <id> | 0, "title": <id> | 0}}}

Everything is optional. A course has stage missions when "missions" says so, and without the key when one of its
stages has a "gold" or a "time". "theme" is the Rumble world whose graphics the course borrows (the picture beside
the list in Select World, the world icon, the title card when a stage loads); "brochure", "icon" and "title" each
name another world for one of them, and 0 leaves the icon or the title card out. "thumbnail" is the course's small
picture in Select World: Banana Mania's own ("mania", the default where Mania has one) or a Rumble world's.
"""
import json
import math
import os

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'overrides.json')
STAGE_KEYS = {'gold': str, 'time': (int, float), 'time_perfect': (int, float), 'bananas': int}
COURSE_KEYS = {'missions': bool, 'theme': int, 'thumbnail': (int, str), 'brochure': int, 'icon': int, 'title': int}


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
                if isinstance(v, bool) != (keys[k] is bool) or not isinstance(v, keys[k]):
                    raise ValueError(f'overrides: {section}/{name}/{k} has the wrong type')
                if isinstance(v, (int, float)) and not isinstance(v, bool) and (v < 0 or v > 100000):
                    raise ValueError(f'overrides: {section}/{name}/{k} is out of range')
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


def default_bananas(banana_count):
    return int(math.ceil(banana_count / 2))


def missions(data, stage_id, time_limit, banana_count):
    """(time, perfect time, bananas) of the stage's missions. banana_count: what all its bananas are worth."""
    s = data['stages'].get(str(stage_id), {})
    t = float(s.get('time') or default_time(time_limit))
    perfect = float(s.get('time_perfect') or t)
    bananas = s['bananas'] if 'bananas' in s else default_bananas(banana_count)
    return t, min(perfect, t), max(0, min(int(bananas), int(banana_count)))
