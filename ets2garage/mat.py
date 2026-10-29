"""Parser for SCS .mat material files.

    effect : "eut2.dif.spec..." {
        diffuse : { 1.0 , 1.0 , 1.0 }
        texture : "texture_base" {
            source : "/material/road/asphalt.tobj"
        }
    }
"""
import re

from sii import _tokenize, _parse_value

_TEXTURE_RE = re.compile(r'texture\s*:\s*"([^"]*)"\s*\{', re.S)


class Material:
    __slots__ = ('path', 'effect', 'attributes', 'textures', 'diffuse', 'specular', 'shininess')

    def __init__(self, path, effect='', attributes=None, textures=None):
        self.path = path
        self.effect = effect
        self.attributes = attributes or {}
        self.textures = textures or {}
        self.diffuse = self.attributes.get('diffuse')
        self.specular = self.attributes.get('specular')
        self.shininess = self.attributes.get('shininess')

    def base_texture(self):
        for key in ('texture_base', 'texture_diffuse', 'texture_over'):
            if key in self.textures:
                return self.textures[key]
        if self.textures:
            return next(iter(self.textures.values()))
        return None

    def normal_texture(self):
        return self.textures.get('texture_nm') or self.textures.get('texture_normal')

    def __repr__(self):
        return f'<Material {self.path} effect={self.effect}>'


def _parse_block(text, start):
    """Parse a brace block starting at the '{' in text[start:]; returns (dict, end)."""
    i = text.index('{', start) + 1
    attrs = {}
    textures = {}
    n = len(text)
    while i < n:
        while i < n and text[i] in ' \t\r\n':
            i += 1
        if i < n and text[i] == '}':
            return attrs, textures, i + 1
        m = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\s*:').match(text, i)
        if not m:
            i += 1
            continue
        key = m.group(1)
        i = m.end()
        while i < n and text[i] in ' \t\r\n':
            i += 1
        if i < n and text[i] == '"' and _TEXTURE_RE.match(text, m.start()):
            # named texture block
            name = text[i + 1:text.index('"', i + 1)]
            inner_start = text.index('{', i)
            sub, _sub_tex, end = _parse_block(text, inner_start)
            src = None
            for k, v in sub.items():
                if k == 'source':
                    src = v
            if src:
                textures[name] = src
            i = end
            continue
        if i < n and text[i] == '{':
            sub, _sub_tex, end = _parse_block(text, i)
            attrs[key] = sub
            i = end
            continue
        # scalar / tuple value
        j = i
        depth = 0
        while j < n:
            c = text[j]
            if c == '{':
                depth += 1
            elif c == '}':
                if depth == 0:
                    break
                depth -= 1
            elif c == '\n' and depth == 0:
                break
            j += 1
        raw = text[i:j].strip()
        i = j
        if raw.startswith('"'):
            attrs[key] = raw.strip('"')
        elif raw.startswith('{') or raw.startswith('('):
            nums = re.findall(r'-?\d+(?:\.\d+)?', raw)
            try:
                attrs[key] = tuple(float(x) for x in nums)
            except ValueError:
                attrs[key] = raw
        else:
            try:
                attrs[key] = float(raw)
            except ValueError:
                attrs[key] = raw
    return attrs, textures, i


def parse_material(data, path=''):
    if isinstance(data, bytes):
        text = data.decode('utf-8', 'replace')
    else:
        text = data
    m = re.search(r'effect\s*:\s*"([^"]*)"\s*\{', text)
    effect = m.group(1) if m else ''
    if m:
        attrs, textures, _ = _parse_block(text, m.end() - 1)
    else:
        attrs, textures, _ = {}, {}, 0
    return Material(path, effect, attrs, textures)


_CACHE = {}


def load_material(vfs, path):
    path = path.lstrip('/')
    if path in _CACHE:
        return _CACHE[path]
    data = vfs.read(path)
    mat = parse_material(data, path) if data is not None else Material(path)
    _CACHE[path] = mat
    return mat