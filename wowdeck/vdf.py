"""Minimal Valve Data Format codec: text VDF (config.vdf, localconfig.vdf) and the
binary VDF used by shortcuts.vdf. Standard library only. Preserves key order.

Text values are always strings. Binary values are str (type 0x01), int (type 0x02,
little-endian int32, returned unsigned) or dict (type 0x00). Nothing else is emitted by
Steam for shortcuts.vdf; other types raise.
"""
from __future__ import annotations
import struct

# --------------------------------------------------------------------------- text VDF

_ESC = {'n': '\n', 't': '\t', '\\': '\\', '"': '"'}
_UNESC = {v: '\\' + k for k, v in _ESC.items()}


def _tokens(text: str):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in ' \t\r\n':
            i += 1
        elif c == '/' and text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
        elif c in '{}':
            yield c, i
            i += 1
        elif c == '"':
            j, out = i + 1, []
            while j < n and text[j] != '"':
                if text[j] == '\\' and j + 1 < n:
                    out.append(_ESC.get(text[j + 1], text[j + 1]))
                    j += 2
                else:
                    out.append(text[j])
                    j += 1
            yield ''.join(out), i
            i = j + 1
        elif c == '[':                      # conditional like [$WIN32]; ignore
            j = text.find(']', i)
            i = n if j < 0 else j + 1
        else:                               # bare token
            j = i
            while j < n and text[j] not in ' \t\r\n{}"':
                j += 1
            yield text[i:j], i
            i = j


def loads(text: str) -> dict:
    root: dict = {}
    stack = [root]
    key = None
    for tok, pos in _tokens(text):
        cur = stack[-1]
        if tok == '{':
            if key is None:
                raise ValueError(f'VDF: "{{" without key at {pos}')
            child: dict = {}
            cur[key] = child
            stack.append(child)
            key = None
        elif tok == '}':
            if len(stack) == 1:
                raise ValueError(f'VDF: unbalanced "}}" at {pos}')
            stack.pop()
            key = None
        elif key is None:
            key = tok
        else:
            cur[key] = tok
            key = None
    if len(stack) != 1:
        raise ValueError('VDF: unterminated block')
    return root


def _q(s: str) -> str:
    return '"' + ''.join(_UNESC.get(c, c) for c in str(s)) + '"'


def dumps(data: dict, indent: int = 0) -> str:
    out = []
    pad = '\t' * indent
    for k, v in data.items():
        if isinstance(v, dict):
            out.append(f'{pad}{_q(k)}\n{pad}{{\n{dumps(v, indent + 1)}{pad}}}\n')
        else:
            out.append(f'{pad}{_q(k)}\t\t{_q(v)}\n')
    return ''.join(out)


def load(path):
    with open(path, encoding='utf-8', errors='surrogateescape') as f:
        return loads(f.read())


def dump(data: dict, path):
    with open(path, 'w', encoding='utf-8', errors='surrogateescape', newline='\n') as f:
        f.write(dumps(data))


def get_path(data: dict, *keys, default=None):
    cur = data
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def set_path(data: dict, *keys_and_value):
    *keys, value = keys_and_value
    cur = data
    for k in keys[:-1]:
        nxt = cur.get(k)
        if not isinstance(nxt, dict):
            nxt = cur[k] = {}
        cur = nxt
    cur[keys[-1]] = value


# --------------------------------------------------------------------------- binary VDF

_T_MAP, _T_STR, _T_INT, _T_END = 0x00, 0x01, 0x02, 0x08


def _cstr(buf: bytes, i: int):
    j = buf.index(b'\x00', i)
    return buf[i:j].decode('utf-8', errors='surrogateescape'), j + 1


def _bin_load_map(buf: bytes, i: int):
    out: dict = {}
    while True:
        t = buf[i]
        i += 1
        if t == _T_END:
            return out, i
        key, i = _cstr(buf, i)
        if t == _T_MAP:
            out[key], i = _bin_load_map(buf, i)
        elif t == _T_STR:
            out[key], i = _cstr(buf, i)
        elif t == _T_INT:
            out[key] = struct.unpack_from('<I', buf, i)[0]
            i += 4
        else:
            raise ValueError(f'binary VDF: unsupported type {t:#x} at {i - 1}')


def binary_loads(buf: bytes) -> dict:
    data, i = _bin_load_map(buf, 0)
    if i != len(buf):
        raise ValueError(f'binary VDF: {len(buf) - i} trailing bytes')
    return data


def _bin_dump_map(data: dict) -> bytes:
    out = bytearray()
    for k, v in data.items():
        kb = str(k).encode('utf-8', errors='surrogateescape') + b'\x00'
        if isinstance(v, dict):
            out += bytes([_T_MAP]) + kb + _bin_dump_map(v)
        elif isinstance(v, bool) or isinstance(v, int):
            out += bytes([_T_INT]) + kb + struct.pack('<I', int(v) & 0xFFFFFFFF)
        elif isinstance(v, str):
            out += bytes([_T_STR]) + kb + v.encode('utf-8', errors='surrogateescape') + b'\x00'
        else:
            raise TypeError(f'binary VDF: cannot encode {type(v).__name__} for key {k!r}')
    out += bytes([_T_END])
    return bytes(out)


def binary_dumps(data: dict) -> bytes:
    return _bin_dump_map(data)


def binary_load(path) -> dict:
    with open(path, 'rb') as f:
        return binary_loads(f.read())


def binary_dump(data: dict, path):
    with open(path, 'wb') as f:
        f.write(binary_dumps(data))
