import struct, zlib, os, re

BASE = r"D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2"

def grundy(name):
    p = os.path.join(BASE, name)
    data = open(p, 'rb').read()
    size = len(data)
    cnt, f10, f14, f18, f1c, f20, f24, f28 = struct.unpack_from('<8I', data, 12)
    print(f"\n===== {name} size=0x{size:x} entries={cnt} f10={f10} f14={f14} f18={f18} f1c=0x{f1c:x} f24=0x{f24:x} =====")
    for label, off, ln in (("f1c-block", f1c, 0), ("f24-block", f24, f18)):
        seg = data[off:] if ln == 0 else data[off:off+ln]
        out = None
        if seg[:1] == b'\x78':
            try:
                out = zlib.decompress(seg)
            except Exception as e:
                out = None
                print(f"  {label} @0x{off:x} zlib fail {e} rawlen={len(seg)}")
        if out is not None:
            print(f"  {label} @0x{off:x} comp={len(seg)} -> raw={len(out)}")
            print("   ", out[:600].hex(' '))
            try:
                print("   txt:", out[:400].decode('utf-8', 'replace').replace('\n', '\\n'))
            except Exception:
                pass
        else:
            print(f"  {label} @0x{off:x} not zlib: {seg[:64].hex(' ')}")

for n in ('version.scs', 'core.scs'):
    grundy(n)