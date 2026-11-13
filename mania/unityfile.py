"""Authoring Unity serialized files with UnityPy: add, remove and transplant objects.

The game's bundles cannot be built with the Unity editor here, so new content is made from copies of the game's own
files. UnityPy has no call to add an object, but a serialized file is a dictionary of object records, and a record
is plain data: a new one is a copy of an existing record of the same type (the "donor", which fixes the class and,
for a MonoBehaviour, the script) with a new id and new contents.

Contents are written through type trees. The stage scene bundles of the game carry their type trees, so that also
works for the game's own MonoBehaviour classes there.
"""
import copy

import attrs
from UnityPy.files import SerializedFile


def serialized_files(env):
    """{internal name: SerializedFile} of a loaded bundle."""
    return {name: f for name, f in env.file.files.items() if isinstance(f, SerializedFile)}


def pptr(path_id=0, file_id=0):
    return {'m_FileID': file_id, 'm_PathID': path_id}


NULL = {'m_FileID': 0, 'm_PathID': 0}


def overlay(base, src, defaults=None, path=''):
    """`base` (a type tree dict of the target engine version) with every value that `src` also has taken from `src`.

    Keys only `base` has keep their value (fields the newer engine added); keys only `src` has are dropped (fields
    it removed). A list is taken from `src`; when its elements are dicts they are overlaid on the first element of
    the base list, or on `defaults[path]` when the base list is empty."""
    if isinstance(base, dict) and isinstance(src, dict):
        out = {}
        for k, v in base.items():
            out[k] = overlay(v, src[k], defaults, path + '.' + k if path else k) if k in src else copy.deepcopy(v)
        return out
    if isinstance(base, list) and isinstance(src, list):
        if src and isinstance(src[0], dict):
            proto = base[0] if base and isinstance(base[0], dict) else (defaults or {}).get(path)
            if proto is None:
                return copy.deepcopy(src)
            return [overlay(proto, e, defaults, path + '[]') for e in src]
        return copy.deepcopy(src)
    return copy.deepcopy(src)


class Editor:
    """One serialized file being rewritten.

    Objects are edited as type tree dicts held by the editor: `get(path_id)` gives the dict (read on first use),
    `add(...)` stores a new one, and `commit()` writes every dict that was touched back into the file. UnityPy keeps
    reading an object's original bytes after it was rewritten, so the editor's dicts are the only current copy."""

    def __init__(self, sf):
        self.sf = sf
        self.next_id = max([abs(i) for i in sf.objects] + [0]) + 1
        self._donors = {}
        self.trees = {}

    # ---- finding things
    def objects(self, class_name=None):
        return [o for o in self.sf.objects.values() if class_name is None or o.type.name == class_name]

    def script_class(self, obj):
        """Class name of a MonoBehaviour of this file (its MonoScript may be in another file of the bundle)."""
        return script_class(self.sf, obj)

    def donor(self, class_name, script=None):
        """An existing object of this class (and script class, for a MonoBehaviour): the model for new ones."""
        key = (class_name, script)
        if key not in self._donors:
            found = None
            for o in self.sf.objects.values():
                if o.type.name != class_name:
                    continue
                if script is None or self.script_class(o) == script:
                    found = o
                    break
            if found is None:
                raise KeyError(f'no {class_name}{" " + script if script else ""} object in {self.sf.name} to model a new one on')
            # a private copy: the model survives the removal of the original object
            self._donors[key] = (attrs.evolve(found), found.read_typetree())
        return self._donors[key]

    def template(self, class_name, script=None):
        """A deep copy of the donor's type tree dict."""
        return copy.deepcopy(self.donor(class_name, script)[1])

    # ---- changing things
    def get(self, path_id):
        """The object's type tree dict; changes to it are written by commit()."""
        if path_id not in self.trees:
            self.trees[path_id] = self.sf.objects[path_id].read_typetree()
        return self.trees[path_id]

    def add(self, class_name, tree, script=None):
        """Add an object; returns its path id. `tree` is kept (not copied) and may be changed until commit()."""
        model, _ = self.donor(class_name, script)
        pid = self.next_id
        self.next_id += 1
        self.sf.objects[pid] = attrs.evolve(model, path_id=pid, data=None)
        self.trees[pid] = tree
        return pid

    def new(self, class_name, script=None, **fields):
        """Add an object that is the donor's contents with `fields` replaced; returns (path id, dict)."""
        tree = self.template(class_name, script)
        tree.update(fields)
        return self.add(class_name, tree, script), tree

    def remove(self, path_id):
        del self.sf.objects[path_id]
        self.trees.pop(path_id, None)

    def commit(self):
        for pid, tree in self.trees.items():
            self.sf.objects[pid].save_typetree(tree)
        self.sf.mark_changed()


def script_class(sf, obj):
    """Class name of the script of MonoBehaviour `obj` in serialized file `sf`, or None."""
    try:
        t = obj.read_typetree()
    except Exception:
        return None
    return script_name(sf, t.get('m_Script'))


_script_cache = {}


def script_name(sf, ref):
    if not ref or not ref.get('m_PathID'):
        return None
    key = (id(sf), ref['m_FileID'], ref['m_PathID'])
    if key in _script_cache:
        return _script_cache[key]
    name = None
    try:
        target = sf
        if ref['m_FileID']:
            ext = sf.externals[ref['m_FileID'] - 1]
            base = ext.path.replace('\\', '/').rsplit('/', 1)[-1].lower()
            target = None
            for n, f in sf.parent.files.items():
                if n.lower() == base and isinstance(f, SerializedFile):
                    target = f
            if target is None and sf.environment is not None:
                for f in sf.environment.cabs.values() if hasattr(sf.environment, 'cabs') else []:
                    if getattr(f, 'name', '').lower() == base and isinstance(f, SerializedFile):
                        target = f
        if target is not None and ref['m_PathID'] in target.objects:
            t = target.objects[ref['m_PathID']].read_typetree()
            name = t.get('m_ClassName')
    except Exception:
        name = None
    _script_cache[key] = name
    return name


def rename_cabs(env, mapping):
    """Give the files inside a bundle new internal names ({old: new}; a `.sharedAssets` / `.resS` sibling follows its
    main file) and repoint the references between them. Two loaded bundles may not hold a file of the same name."""
    files = env.file.files
    full = {}
    for old, new in mapping.items():
        for name in list(files):
            if name == old or name.startswith(old + '.'):
                full[name] = new + name[len(old):]
    for old, new in full.items():
        f = files.pop(old)
        try:
            f.name = new
        except Exception:
            pass
        files[new] = f
    for f in files.values():
        if not isinstance(f, SerializedFile):
            continue
        changed = False
        for ext in f.externals:
            for old, new in mapping.items():          # archive:/<main file>/<file>: both parts carry the name
                if old in ext.path:
                    ext.path = ext.path.replace(old, new)
                    changed = True
        if changed:
            f.mark_changed()
    return full
