"""Parser for SCS "SiiNunit" definition files (.sii / .sui).

The format is a plain-text tree of units::

    SiiNunit
    {
    accessory_addon_data : shape1.scania.s_2016.beacon
    {
        name: "@@beacon_bonfire@@"
        price: 3120
        suitable_for[]: "4x2.scania.s_2016.chassis"
    }
    }
"""
import re

_TOKEN = re.compile(r'"(?:[^"\\]|\\.)*"|[{}():,]|[^\s{}():,]+')
_ESCAPES = {'n': '\n', 't': '\t', 'r': '\r', '"': '"', '\\': '\\'}
_STRIP_AT = 12          # safety limit for recursive includes


class SiiError(Exception):
    pass


class Unit:
    __slots__ = ('type', 'name', 'attrs', 'source')

    def __init__(self, type_, name, source=''):
        self.type = type_
        self.name = name
        self.attrs = {}
        self.source = source

    def get(self, key, default=None):
        v = self.attrs.get(key)
        if v is None:
            return default
        if isinstance(v, list):
            return v[0] if v else default
        return v

    def list(self, key):
        v = self.attrs.get(key)
        if v is None:
            return []
        return v if isinstance(v, list) else [v]

    def __repr__(self):
        return f'<{self.type} {self.name!r} ({len(self.attrs)} attrs)>'


def _tokenize(text):
    out = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
            continue
        if c == '#':
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if c == '/' and text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j + 1
            continue
        if c == '@' and text.startswith('@include', i):
            m = re.compile(r'@include\s+"([^"]*)"').match(text, i)
            if m:
                out.append(('include', m.group(1)))
                i = m.end()
                continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    buf.append(_ESCAPES.get(text[j + 1], text[j + 1]))
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            out.append(('str', ''.join(buf)))
            i = j + 1
            continue
        m = _TOKEN.match(text, i)
        if not m:
            i += 1
            continue
        tok = m.group()
        i = m.end()
        if tok in '{}():,':
            out.append(('punct', tok))
        elif tok in ('true', 'false'):
            out.append(('bool', tok == 'true'))
        else:
            try:
                if re.fullmatch(r'-?\d+', tok):
                    out.append(('int', int(tok)))
                elif re.fullmatch(r'-?(\d+\.\d*|\.\d+)([eE][-+]?\d+)?', tok):
                    out.append(('float', float(tok)))
                else:
                    out.append(('word', tok))
            except ValueError:
                out.append(('word', tok))
    return out


def _parse_value(toks, i):
    """Parse a single value starting at i; returns (value, next_index)."""
    kind, val = toks[i]
    if kind == 'punct' and val == '(':
        i += 1
        items = []
        while i < len(toks):
            k, v = toks[i]
            if k == 'punct' and v == ')':
                i += 1
                break
            if k == 'punct' and v == ',':
                i += 1
                continue
            item, i = _parse_value(toks, i)
            items.append(item)
        return tuple(items), i
    return val, i + 1


def parse(text, source='', include_resolver=None, _depth=0):
    """Parse SiiNunit text into {unit_name: Unit}."""
    units = {}
    toks = _tokenize(text)
    i = 0
    n = len(toks)

    def want_punct(idx, ch):
        if idx < n and toks[idx][0] == 'punct' and toks[idx][1] == ch:
            return idx + 1
        return idx

    # skip a leading SiiNunit marker
    if i < n and toks[i][0] in ('word', 'str') and toks[i][1] == 'SiiNunit':
        i += 1
    i = want_punct(i, '{')

    while i < n:
        if toks[i][0] == 'include':
            if include_resolver and _depth < _STRIP_AT:
                sub = include_resolver(source, toks[i][1])
                if sub is not None:
                    for k, v in parse(sub, toks[i][1], include_resolver, _depth + 1).items():
                        units.setdefault(k, v)
            i += 1
            continue
        if toks[i][0] == 'punct' and toks[i][1] == '}':
            i += 1
            continue
        if toks[i][0] != 'word':
            i += 1
            continue
        utype = toks[i][1]
        i += 1
        i = want_punct(i, ':')
        if i >= n:
            break
        uname = toks[i][1] if toks[i][0] in ('word', 'str') else ''
        i += 1
        i = want_punct(i, '{')
        unit = Unit(utype, uname, source)
        while i < n and not (toks[i][0] == 'punct' and toks[i][1] == '}'):
            if toks[i][0] == 'include':
                if include_resolver and _depth < _STRIP_AT:
                    sub = include_resolver(source, toks[i][1])
                    if sub is not None:
                        for k, v in parse(sub, toks[i][1], include_resolver, _depth + 1).items():
                            units.setdefault(k, v)
                i += 1
                continue
            if toks[i][0] != 'word':
                i += 1
                continue
            key = toks[i][1]
            is_array = False
            if key.endswith(']') and '[' in key:
                # "attr[]" or "attr[3]" both denote array elements
                key = key[:key.index('[')]
                is_array = True
            elif i + 1 < n and toks[i + 1][0] == 'punct' and toks[i + 1][1] == '(':
                is_array = True
            i += 1
            i = want_punct(i, ':')
            if i >= n:
                break
            value, i = _parse_value(toks, i)
            if is_array:
                unit.attrs.setdefault(key, [])
                if not isinstance(unit.attrs[key], list):
                    unit.attrs[key] = [unit.attrs[key]]
                unit.attrs[key].append(value)
            else:
                unit.attrs[key] = value
        i = want_punct(i, '}')
        if uname:
            units[uname] = unit
    return units


_INCLUDE_RE = re.compile(r'@include\s+"([^"]*)"')
_INCLUDE_MAX_DEPTH = 8


def expand_includes(text, source='', resolver=None, depth=0):
    """Inline ``@include "x.sui"`` directives.

    SCS uses includes both at top level and *inside* unit bodies (a
    ``*_settings.sui`` fragment is often just a list of attributes), so textual
    expansion is the only approach that handles both cases.
    """
    if resolver is None or depth >= _INCLUDE_MAX_DEPTH:
        return text

    def repl(match):
        name = match.group(1).strip()
        res = resolver(source, name)
        if not res:
            return ''
        path, sub = res
        return expand_includes(sub, path, resolver, depth + 1)

    return _INCLUDE_RE.sub(repl, text)


def make_vfs_resolver(vfs):
    """Resolver bound to an ScsVfs; returns (resolved_path, text)."""
    def resolve(source, name):
        if name.startswith('/'):
            path = name.lstrip('/')
        else:
            d = source.rsplit('/', 1)[0] if '/' in source else ''
            path = f'{d}/{name}' if d else name
        data = vfs.read(path)
        if data is None:
            return None
        return path, data.decode('utf-8', 'replace').lstrip('\ufeff')
    return resolve


def parse_bytes(data, source='', include_resolver=None):
    if data is None:
        return {}
    if data[:4] == b'\x00\x00\x00\x00' or data[:4] == b'BSII':
        raise SiiError('binary SII files are not supported')
    text = data.decode('utf-8', 'replace').lstrip('\ufeff')
    return parse(text, source, include_resolver)


def decode_localized(value, locale_map=None, default=None):
    """Resolve "@@token@@" strings through a locale map."""
    if not isinstance(value, str):
        return value
    if value.startswith('@@') and value.endswith('@@') and len(value) > 4:
        key = value[2:-2]
        if locale_map:
            return locale_map.get(key, default or key)
        return default or key
    return value


if __name__ == '__main__':
    import sys
    u = parse(open(sys.argv[1], encoding='utf-8').read())
    for name, unit in list(u.items())[:5]:
        print(unit)
        for k, v in list(unit.attrs.items())[:8]:
            print('   ', k, '=', v)