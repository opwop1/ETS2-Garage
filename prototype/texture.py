"""SCS 1.50+ texture extraction.

In HashFS v2 the .tobj entry holds *raw DDS bits only*; every property that used
to live in the .tobj file (size, mip count, DXGI format, alignment, sampler
state) is stored as archive entry metadata.  See ConverterPIX
src/texture/texture_object.cpp for the reference behaviour implemented here.
"""
import ctypes
import io
import math
import os
import struct
import sys

# --------------------------------------------------------------------- DXGI
# subset of prism::format_t that we know how to lay out
DXGI_BC1 = (70, 71, 72)
DXGI_BC2 = (73, 74, 75)
DXGI_BC3 = (76, 77, 78)
DXGI_BC4 = (79, 80, 81)
DXGI_BC5 = (82, 83, 84)
DXGI_BC6H = (94, 95, 96)
DXGI_BC7 = (97, 98, 99)
DXGI_B8G8R8A8 = (87, 91)
DXGI_B8G8R8X8 = (88, 93)
DXGI_B8G8R8 = (201, 203)
DXGI_R8 = (61,)
DXGI_R16G16 = (33, 34, 35, 36, 37, 38)

DDS_MAGIC = 0x20534444


def _block_layout(fmt):
    """Return (block_w, block_h, block_bytes, bytes_per_pixel)."""
    if fmt in DXGI_BC1:
        return 4, 4, 8, 0
    if fmt in DXGI_BC2 or fmt in DXGI_BC3 or fmt in DXGI_BC5 or fmt in DXGI_BC6H or fmt in DXGI_BC7:
        return 4, 4, 16, 0
    if fmt in DXGI_BC4:
        return 4, 4, 8, 0
    if fmt in DXGI_B8G8R8A8:
        return 1, 1, 0, 4
    if fmt in DXGI_B8G8R8X8 or fmt in DXGI_B8G8R8:
        return 1, 1, 0, 4
    if fmt in DXGI_R8:
        return 1, 1, 0, 1
    if fmt in DXGI_R16G16:
        return 1, 1, 0, 4
    return 1, 1, 0, 4


def mip_row_pitch(fmt, width):
    bw, bh, bbytes, bpp = _block_layout(fmt)
    if bbytes:
        return max(1, (width + bw - 1) // bw) * bbytes
    return width * bpp


def mip_row_count(fmt, height):
    bw, bh, bbytes, bpp = _block_layout(fmt)
    if bbytes:
        return max(1, (height + bh - 1) // bh)
    return height


# ------------------------------------------------ gdeflate native decompressor
_lib = None


def _load_lib():
    global _lib
    if _lib is not None:
        return _lib
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in ('gdeflate.dll', os.path.join(here, 'gdeflate.dll'),
                 os.path.join(here, 'native', 'out', 'gdeflate.dll'),
                 os.path.join(os.path.dirname(here), 'native', 'out', 'gdeflate.dll')):
        if os.path.exists(cand):
            lib = ctypes.CDLL(os.path.abspath(cand))
            lib.scs_gdeflate_decompress.restype = ctypes.c_int
            lib.scs_gdeflate_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t,
                                                    ctypes.c_void_p, ctypes.c_size_t]
            _lib = lib
            return lib
    raise RuntimeError('gdeflate.dll not found - cannot decode 1.50+ textures')


def gdeflate_decompress(data, out_size):
    lib = _load_lib()
    out = ctypes.create_string_buffer(out_size)
    src = ctypes.create_string_buffer(data, len(data))
    ok = lib.scs_gdeflate_decompress(out, out_size, src, len(data))
    if not ok:
        raise ValueError('gdeflate decompression failed')
    return out.raw[:out_size]


COMPRESSION_NONE, COMPRESSION_ZLIB, COMPRESSION_ZLIB_HDRLESS, COMPRESSION_GDEFLATE, COMPRESSION_ZSTD = range(5)


def _decompress(data, compression, out_size):
    if compression == COMPRESSION_NONE:
        return data[:out_size] if len(data) >= out_size else data
    if compression == COMPRESSION_ZLIB:
        import zlib
        return zlib.decompress(data)
    if compression in (COMPRESSION_ZLIB_HDRLESS,):
        import zlib
        return zlib.decompressobj(-15).decompress(data)
    if compression == COMPRESSION_GDEFLATE:
        return gdeflate_decompress(data, out_size)
    raise ValueError(f'unsupported compression {compression}')


# ----------------------------------------------------------------- DDS build
def _align(value, alignment):
    if alignment <= 1:
        return value
    return (value + alignment - 1) // alignment * alignment


def build_dds_bits(info, payload):
    """De-pad the aligned source layout into tightly packed mip data."""
    fmt = info['format']
    width, height = info['width'], info['height']
    mips = info['mipmaps']
    faces = max(1, info['count'])
    pitch_align = info['pitch_alignment']
    image_align = info['image_alignment']

    out = bytearray()
    off = 0
    w, h = width, height
    for _face in range(faces):
        for _mip in range(mips):
            row_pitch = mip_row_pitch(fmt, w)
            rows = mip_row_count(fmt, h)
            off = _align(off, image_align)
            for _row in range(rows):
                off = _align(off, pitch_align)
                out += payload[off:off + row_pitch]
                off += row_pitch
            w = max(1, w // 2)
            h = max(1, h // 2)
    return bytes(out)


def _legacy_fourcc(fmt):
    if fmt in DXGI_BC1:
        return b'DXT1'
    if fmt in DXGI_BC2:
        return b'DXT3'
    if fmt in DXGI_BC3:
        return b'DXT5'
    if fmt in DXGI_BC4:
        return b'ATI1'
    if fmt in DXGI_BC5:
        return b'ATI2'
    return None


DDSD_CAPS = 0x1
DDSD_HEIGHT = 0x2
DDSD_WIDTH = 0x4
DDSD_PITCH = 0x8
DDSD_PIXELFORMAT = 0x1000
DDSD_MIPMAPCOUNT = 0x20000
DDSD_LINEARSIZE = 0x80000
DDPF_ALPHAPIXELS = 0x1
DDPF_FOURCC = 0x4
DDPF_RGB = 0x40
DDPF_LUMINANCE = 0x20000
DDSCAPS_TEXTURE = 0x1000
DDSCAPS_MIPMAP = 0x400000
DDSCAPS_COMPLEX = 0x8


def make_dds(info, bits):
    """Build a legacy (DX9-style) DDS blob so that ordinary decoders can read it."""
    fmt = info['format']
    width, height = info['width'], info['height']
    mips = info['mipmaps']
    fourcc = _legacy_fourcc(fmt)
    flags = DDSD_CAPS | DDSD_HEIGHT | DDSD_WIDTH | DDSD_PIXELFORMAT
    if mips > 1:
        flags |= DDSD_MIPMAPCOUNT
    caps = DDSCAPS_TEXTURE
    if mips > 1:
        caps |= DDSCAPS_MIPMAP | DDSCAPS_COMPLEX
    if fourcc:
        flags |= DDSD_LINEARSIZE
        pf = struct.pack('<II4sIIIII', 32, DDPF_FOURCC, fourcc,
                         0, 0, 0, 0, 0)
    else:
        flags |= DDSD_PITCH
        if fmt in DXGI_B8G8R8A8:
            pf = struct.pack('<II4sIIIII', 32, DDPF_RGB | DDPF_ALPHAPIXELS, b'\0' * 4,
                             32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
        elif fmt in DXGI_B8G8R8X8 or fmt in DXGI_B8G8R8:
            pf = struct.pack('<II4sIIIII', 32, DDPF_RGB, b'\0' * 4,
                             32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0)
        elif fmt in DXGI_R8:
            pf = struct.pack('<II4sIIIII', 32, DDPF_LUMINANCE, b'\0' * 4,
                             8, 0xFF, 0, 0, 0)
        else:
            import warnings
            warnings.warn(f'unsupported dxgi format {fmt} for DDS output')
            pf = struct.pack('<II4sIIIII', 32, DDPF_RGB | DDPF_ALPHAPIXELS, b'\0' * 4,
                             32, 0x00FF0000, 0x0000FF00, 0x000000FF, 0xFF000000)
    header = struct.pack('<4sIIIIIII44s', b'DDS ', 124, flags, height, width,
                         mip_row_pitch(fmt, width) if not fourcc else len(bits),
                         0, mips, b'\0' * 44)
    caps_block = struct.pack('<IIIII', caps, 0, 0, 0, 0)
    return header + pf + caps_block + bits


def extract_texture(archive, path):
    """Return (dds_bytes, info) for a 1.50+ .tobj entry."""
    info = archive.texture_info(path)
    if 'parts' not in info:
        raise ValueError(f'{path}: no payload metadata')
    parts = info['parts']
    chunks = []
    for p in parts:
        raw = archive.raw_payload(path, p)
        chunks.append(_decompress(raw, p['compression'], p['size']))
    payload = b''.join(chunks)
    bits = build_dds_bits(info, payload)
    return make_dds(info, bits), info


if __name__ == '__main__':
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from hashfs2 import ScsArchive
    from PIL import Image
    BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
    av = ScsArchive(os.path.join(BASE, 'base_vehicle.scs'))
    tests = ['material/custom/flake_noise.tobj', 'material/custom/trucklight_mask.tobj']
    for t in tests:
        dds, info = extract_texture(av, t)
        print(f'== {t}: {info["width"]}x{info["height"]} fmt={info["format"]} '
              f'mips={info["mipmaps"]} -> dds {len(dds)} bytes')
        open(os.path.basename(t).replace('.tobj', '.dds'), 'wb').write(dds)
        try:
            im = Image.open(io.BytesIO(dds))
            print('   Pillow:', im.format, im.size, im.mode)
            im.convert('RGB').save(os.path.basename(t).replace('.tobj', '.png'))
            print('   png written')
        except Exception as exc:
            print('   Pillow failed:', exc)