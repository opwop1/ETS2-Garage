"""CityHash64 (Google CityHash v1.1, 64-bit) pure-Python implementation.

Used by SCS HashFS v2 archives (ETS2/ATS 1.50+) to map paths to 64-bit keys.
"""

MASK64 = (1 << 64) - 1

k0 = 0xC3A5C85C97CB3127
k1 = 0xB492B66FBE98F273
k2 = 0x9AE16A3B2F90404F
k3 = 0xC949D7C7509E6557
kMul = 0x9DDFEA08EB382D69


def fetch64(s, i):
    return int.from_bytes(s[i:i + 8], 'little')


def fetch32(s, i):
    return int.from_bytes(s[i:i + 4], 'little')


def rotate(val, shift):
    if shift == 0:
        return val
    return ((val >> shift) | (val << (64 - shift))) & MASK64


def rotate_by_at_least_1(val, shift):
    return ((val >> shift) | (val << (64 - shift))) & MASK64


def shift_mix(val):
    return val ^ (val >> 47)


def hash128to64(low, high):
    a = ((low ^ high) * kMul) & MASK64
    a ^= (a >> 47)
    b = ((high ^ a) * kMul) & MASK64
    b ^= (b >> 47)
    return (b * kMul) & MASK64


def hash_len_16(u, v):
    return hash128to64(u, v)


def hash_len_0_to_16(s, off, n):
    if n > 8:
        a = fetch64(s, off)
        b = fetch64(s, off + n - 8)
        return hash_len_16(a, rotate_by_at_least_1((b + n) & MASK64, n)) ^ b
    if n >= 4:
        a = fetch32(s, off)
        return hash_len_16((n + (a << 3)) & MASK64, fetch32(s, off + n - 4))
    if n > 0:
        a = s[off]
        b = s[off + (n >> 1)]
        c = s[off + n - 1]
        y = (a + (b << 8)) & MASK64
        z = (n + (c << 2)) & MASK64
        # products must be truncated to 64 bits *before* ShiftMix, exactly as
        # the C++ implementation does (uint64 arithmetic).
        return (shift_mix(((y * k2) & MASK64) ^ ((z * k3) & MASK64)) * k2) & MASK64
    return k2


def hash_len_17_to_32(s, off, n):
    a = (fetch64(s, off) * k1) & MASK64
    b = fetch64(s, off + 8)
    c = (fetch64(s, off + n - 8) * k2) & MASK64
    d = (fetch64(s, off + n - 16) * k0) & MASK64
    return hash_len_16(
        (rotate((a - b) & MASK64, 43) + rotate(c, 30) + d) & MASK64,
        (a + rotate(b ^ k3, 20) - c + n) & MASK64,
    )


def _w32(s, off, a, b):
    return _weak32(fetch64(s, off), fetch64(s, off + 8),
                   fetch64(s, off + 16), fetch64(s, off + 24), a, b)


def _weak32(w, x, y, z, a, b):
    a = (a + w) & MASK64
    b = rotate((b + a + z) & MASK64, 21)
    c = a
    a = (a + x) & MASK64
    a = (a + y) & MASK64
    b = (b + rotate(a, 44)) & MASK64
    return ((a + z) & MASK64, (b + c) & MASK64)


def hash_len_33_to_64(s, off, n):
    z = fetch64(s, off + 24)
    a = (fetch64(s, off) + (n + fetch64(s, off + n - 16)) * k0) & MASK64
    b = rotate((a + z) & MASK64, 52)
    c = rotate(a, 37)
    a = (a + fetch64(s, off + 8)) & MASK64
    c = (c + rotate(a, 7)) & MASK64
    a = (a + fetch64(s, off + 16)) & MASK64
    vf = (a + z) & MASK64
    vs = (b + rotate(a, 31) + c) & MASK64
    a = (fetch64(s, off + 16) + fetch64(s, off + n - 32)) & MASK64
    z = fetch64(s, off + n - 8)
    b = rotate((a + z) & MASK64, 52)
    c = rotate(a, 37)
    a = (a + fetch64(s, off + n - 24)) & MASK64
    c = (c + rotate(a, 7)) & MASK64
    a = (a + fetch64(s, off + n - 16)) & MASK64
    wf = (a + z) & MASK64
    ws = (b + rotate(a, 31) + c) & MASK64
    r = shift_mix(((vf + ws) * k2 + (wf + vs) * k0) & MASK64)
    return (shift_mix((r * k0 + vs) & MASK64) * k2) & MASK64


def cityhash64(data, off=0, length=None):
    """CityHash64 of data[off:off+length]. Accepts bytes or str."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    if length is None:
        length = len(data) - off
    n = length
    if n <= 32:
        if n <= 16:
            return hash_len_0_to_16(data, off, n)
        return hash_len_17_to_32(data, off, n)
    if n <= 64:
        return hash_len_33_to_64(data, off, n)

    x = fetch64(data, off + n - 40)
    y = (fetch64(data, off + n - 16) + fetch64(data, off + n - 56)) & MASK64
    z = hash_len_16((fetch64(data, off + n - 48) + n) & MASK64,
                    fetch64(data, off + n - 24))
    v = _w32(data, off + n - 64, n, z)
    w = _w32(data, off + n - 32, (y + k1) & MASK64, x)
    x = (x * k1 + fetch64(data, off)) & MASK64

    i = off
    rem = (n - 1) & ~63
    while True:
        x = (rotate((x + y + v[0] + fetch64(data, i + 8)) & MASK64, 37) * k1) & MASK64
        y = (rotate((y + v[1] + fetch64(data, i + 48)) & MASK64, 42) * k1) & MASK64
        x ^= w[1]
        y = (y + v[0] + fetch64(data, i + 40)) & MASK64
        z = (rotate((z + w[0]) & MASK64, 33) * k1) & MASK64
        v = _w32(data, i, (v[1] * k1) & MASK64, (x + w[0]) & MASK64)
        w = _w32(data, i + 32, (z + w[1]) & MASK64, (y + fetch64(data, i + 16)) & MASK64)
        z, x = x, z
        i += 64
        rem -= 64
        if rem == 0:
            break
    return hash_len_16(
        (hash_len_16(v[0], w[0]) + (shift_mix(y) * k1) + z) & MASK64,
        (hash_len_16(v[1], w[1]) + x) & MASK64,
    )


def cityhash64_path(path):
    """SCS stores paths with '/' separators and lowercase."""
    return cityhash64(path)


if __name__ == '__main__':
    print('empty          =', hex(cityhash64('')))
    print('expect k2      =', hex(k2))
    for s in ('version.sii', 'def/city.sii', 'a', 'ab', 'abc', 'abcd',
              'def/vehicle/truck/scania_2016/accessory/mirror/shape1.sii',
              'x' * 100):
        print(f'{s[:40]:42s} = {cityhash64(s):#018x}')