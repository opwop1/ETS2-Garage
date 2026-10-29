"""SCS 8-byte token decoding (base-38 packed names)."""
TOKEN_LETTERS = ('\x00' + '0123456789' + 'abcdefghijklmnopqrstuvwxyz' + '_')
TOKEN_RADIX = 38


def decode_token(raw):
    if isinstance(raw, int):
        v = raw
    else:
        v = int.from_bytes(raw, 'little')
    if v == 0:
        return ''
    out = []
    while v:
        v, rem = divmod(v, TOKEN_RADIX)
        out.append(TOKEN_LETTERS[rem])
    return ''.join(out)


def encode_token(name):
    v = 0
    mult = 1
    for ch in name:
        try:
            idx = TOKEN_LETTERS.index(ch)
        except ValueError:
            idx = 0
        v += idx * mult
        mult *= TOKEN_RADIX
    return v