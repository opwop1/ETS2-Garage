import struct, zlib, sys, os

BASE = r"D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2"

def probe(name, max_zlib_scan=None):
    p = os.path.join(BASE, name)
    with open(p, 'rb') as f:
        head = f.read(0x40)
        size = os.path.getsize(p)
    magic = head[:4]
    ver = struct.unpack_from('<I', head, 4)[0]
    sig = head[8:12]
    fields = struct.unpack_from('<8I', head, 12)
    print(f"\n===== {name}  size={size} (0x{size:x}) =====")
    print("magic", magic, "version", ver, "signature", sig)
    names = ['f0x0C', 'f0x10', 'f0x14', 'f0x18', 'f0x1C', 'f0x20', 'f0x24', 'f0x28']
    for n, v in zip(names, fields):
        print(f"  {n} = {v} (0x{v:x})")
    print(f"  f0x2C(first 4 bytes after) = {struct.unpack_from('<I', head, 0x2C)[0]}")

    # scan for zlib streams in the tail region
    with open(p, 'rb') as f:
        f.seek(max(0, size - 200000))
        start = max(0, size - 200000)
        blob = f.read()
    found = []
    i = 0
    n = len(blob)
    while i < n - 2:
        if blob[i] == 0x78 and blob[i+1] in (0x01, 0x9c, 0xda, 0x5e):
            try:
                d = zlib.decompressobj()
                out = d.decompress(blob[i:])
                if len(out) > 0:
                    found.append((start + i, len(out), out))
                    i += max(2, len(blob) - i - len(d.unused_data))
                    continue
            except Exception:
                pass
        i += 1
    print(f"  zlib streams found in tail: {len(found)}")
    for off, ln, out in found[:12]:
        print(f"   @0x{off:x} -> {ln} bytes: {out[:300]!r}")

if __name__ == '__main__':
    probe('version.scs')
    probe('core.scs')