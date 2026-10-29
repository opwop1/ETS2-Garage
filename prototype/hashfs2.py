"""SCS HashFS v2 archive reader (ETS2 / ATS 1.50+).

Format summary
--------------
Header (0x34 bytes, little endian):
    char[4]  magic         "SCS#"
    uint16   version       2
    uint16   salt          must be 0 for the supported variant
    char[4]  hash_method   "CITY" (CityHash64)
    uint32   entry_count
    uint32   size1         compressed size of index 1
    uint32   word_count2   number of uint32 words in index 2 (uncompressed)
    uint32   size2         compressed size of index 2
    uint64   start1        file offset of index 1 (zlib)
    uint64   start2        file offset of index 2 (zlib)
    uint64   cert_start

Index 1 (entry_count x 0x10):
    uint64 hash (little endian), uint32 index2_word_offset, uint16 part_count, uint16 flags1
        flags1 & 0x01 -> entry is a directory listing
        flags1 & 0x04 -> preload

Index 2 (word_count2 x uint32) -- part descriptors:
    uint16 offset_low, uint8 offset_high, uint8 kind
        kind & 0x80 -> data part header (16 bytes at offset*4)
        offset = offset_low | (offset_high << 16)

Data part header (16 bytes):
    uint16 zsize_low, uint8 zsize_high, uint8 flags2,
    uint16 usize_low, uint8 usize_high, uint8 flags3,
    uint32 unknown7, uint32 data_offset
        zsize = zsize_low | zsize_high << 16
        usize = usize_low | usize_high << 16
        (flags2 & 0xf0) == 0x10 -> zlib deflate
        absolute file offset = data_offset * 0x10

Directory listing entries (uncompressed payload of a directory entry):
    uint32 count, uint8 size[count], then payload[count]
    payload starting with '/' is a subdirectory (leading slash stripped),
    otherwise it is a file name.
"""

import os
import struct
import zlib

from cityhash64 import cityhash64

MAGIC = b'SCS#'
HASH_METHOD = b'CITY'

COMPRESSION_NONE = 0x00
COMPRESSION_ZLIB = 0x10


class ScsError(Exception):
    pass


class ScsEntry:
    __slots__ = ('hash', 'offset', 'zsize', 'size', 'compression', 'is_dir',
                 'is_tobj', 'parts', 'flags1', 'flags2', 'flags3', 'index_offset')

    def __init__(self, **kw):
        for k in self.__slots__:
            setattr(self, k, kw.get(k))

    def __repr__(self):
        kind = 'dir' if self.is_dir else ('tobj' if self.is_tobj else 'file')
        return f'<ScsEntry {kind} off=0x{self.offset:x} z={self.zsize} u={self.size}>'


class ScsArchive:
    """Random-access reader for a single .scs HashFS v2 archive."""

    def __init__(self, path, keep_open=True):
        self.path = path
        self.name = os.path.basename(path)
        self._fh = None
        self._keep_open = keep_open
        self.entries = {}
        self.entry_count = 0
        self.dirs = []
        self.files = []
        self.header = None
        self._mount()

    # ---------------------------------------------------------------- mount
    def _mount(self):
        self._fh = open(self.path, 'rb')
        fh = self._fh
        raw = fh.read(0x34)
        if len(raw) < 0x34:
            raise ScsError(f'{self.name}: too short to be an SCS archive')
        (magic, version, salt, hash_method, entry_count, size1,
         word_count2, size2, start1, start2, cert_start) = struct.unpack('<4sHH4sIIIIQQQ', raw)
        if magic != MAGIC:
            raise ScsError(f'{self.name}: bad magic {magic!r}')
        if version != 2:
            raise ScsError(f'{self.name}: unsupported HashFS version {version}')
        if salt != 0:
            raise ScsError(f'{self.name}: unsupported salt {salt}')
        if hash_method != HASH_METHOD:
            raise ScsError(f'{self.name}: unsupported hash method {hash_method!r}')
        self.header = dict(version=version, salt=salt, entry_count=entry_count,
                           start1=start1, start2=start2, cert_start=cert_start)
        self.entry_count = entry_count

        index1 = self._read_index(start1, size1, entry_count * 0x10)
        index2 = self._read_index(start2, size2, word_count2 * 4)
        self._index1 = index1
        self._index2 = index2

        for j in range(entry_count):
            (h, index_offset, parts,
             flags1) = struct.unpack_from('<QIHH', index1, j * 0x10)
            is_dir = bool(flags1 & 0x01)
            descs = []
            data_header = None
            for k in range(parts):
                off_low, off_high, kind = struct.unpack_from('<HBB', index2, (index_offset + k) * 4)
                off = off_low | (off_high << 16)
                if kind & 0x80:
                    hsize = 16
                elif kind == 1:
                    hsize = 8
                elif kind == 2:
                    hsize = 4
                elif kind == 5:
                    hsize = 32
                elif kind == 6:
                    hsize = 8
                else:
                    hsize = 0
                blob = index2[off * 4: off * 4 + hsize]
                descs.append((off, kind, blob))
                if kind & 0x80:
                    data_header = blob
            if data_header is None or len(data_header) < 16:
                continue
            (zsize_l, zsize_h, flags2, usize_l, usize_h, flags3,
             unknown7, data_offset) = struct.unpack('<HBBHBBII', data_header)
            self.entries[h] = ScsEntry(
                hash=h, offset=data_offset * 0x10, zsize=zsize_l | (zsize_h << 16),
                size=usize_l | (usize_h << 16), compression=flags2 & 0xF0,
                is_dir=is_dir, is_tobj=bool(descs and descs[0][1] == 1),
                parts=descs, flags1=flags1, flags2=flags2, flags3=flags3,
                index_offset=index_offset,
            )
        if not self._keep_open:
            self._fh.close()
            self._fh = None

    def _read_index(self, start, size, expected):
        self._fh.seek(start)
        raw = self._fh.read(size)
        if len(raw) != size:
            raise ScsError(f'{self.name}: short read at index 0x{start:x}')
        try:
            out = zlib.decompress(raw)
        except zlib.error:
            try:
                out = zlib.decompressobj().decompress(raw)
            except zlib.error as exc:
                raise ScsError(f'{self.name}: index at 0x{start:x} not zlib ({exc})')
        return out

    # ---------------------------------------------------------------- access
    def has(self, path):
        return cityhash64(path) in self.entries

    def stat(self, path):
        return self.entries.get(cityhash64(path))

    def read(self, path_or_hash, raw=False):
        h = path_or_hash if isinstance(path_or_hash, int) else cityhash64(path_or_hash)
        entry = self.entries.get(h)
        if entry is None:
            return None
        if self._fh is None:
            with open(self.path, 'rb') as fh:
                fh.seek(entry.offset)
                data = fh.read(entry.zsize)
        else:
            self._fh.seek(entry.offset)
            data = self._fh.read(entry.zsize)
        if len(data) != entry.zsize:
            raise ScsError(f'{self.name}: short read for {path_or_hash!r}')
        if entry.compression == COMPRESSION_ZLIB and not raw:
            try:
                data = zlib.decompress(data)
            except zlib.error:
                data = zlib.decompressobj().decompress(data)
        return data

    read_entry = read

    # ------------------------------------------------------------- metadata
    META_NAMES = {0x01: 'img', 0x02: 'sample', 0x03: 'mipproxy', 0x04: 'inline_directory'}
    META_WORDS = {0x01: 2, 0x02: 1, 0x03: 8, 0x04: 1, 0x06: 2}
    for _m in (0x80, 0x81, 0x82, 0x83, 0x84):
        META_WORDS[_m] = 4

    def meta_items(self, path_or_hash):
        """Yield (kind, [u32,...]) metadata records for an entry."""
        h = path_or_hash if isinstance(path_or_hash, int) else cityhash64(path_or_hash)
        entry = self.entries.get(h)
        if entry is None:
            return []
        out = []
        for off, kind, blob in entry.parts:
            nwords = self.META_WORDS.get(kind, len(blob) // 4)
            base = off * 4
            words = list(struct.unpack_from(f'<{nwords}I', self._index2, base))
            name = self.META_NAMES.get(kind)
            if name is None:
                if kind & 0x80:
                    name = 'plain' if kind == 0x80 else f'plain+{kind - 0x80}'
                else:
                    name = f'kind{kind:#x}'
            out.append((kind, name, words))
        return out

    def texture_info(self, path_or_hash):
        """Decode the metadata of a 1.50+ .tobj entry (raw DDS bits + metadata)."""
        items = self.meta_items(path_or_hash)
        info = {'meta': items}
        for kind, name, w in items:
            if kind == 0x01 and len(w) >= 2:               # img
                v0, v1 = w[0], w[1]
                info['width'] = 1 + (v0 & 0xFFFF)
                info['height'] = 1 + (v0 >> 16)
                info['mipmaps'] = (v1 & 0xF) + 1
                info['format'] = (v1 >> 4) & 0xFF
                info['cube'] = (v1 >> 12) & 0x3
                info['count'] = ((v1 >> 14) & 0x3F) + 1
                info['pitch_alignment'] = 1 << ((v1 >> 20) & 0xF)
                info['image_alignment'] = 1 << ((v1 >> 24) & 0xF)
            elif kind == 0x02 and len(w) >= 1:             # sample
                info['sample'] = w[0]
            elif kind & 0x80:                              # plain / mip0 / mip1 / miptail
                if len(w) >= 4:
                    w0, w1, w2, w3 = w[0], w[1], w[2], w[3]
                    comp = (((w0 >> 28) & 0xF) | (((w1 >> 28) & 0xF) << 4)) & 0xF
                    part = {
                        'key': name,
                        # prism::fs_compression_t: 0 none, 1 zlib, 2 zlib-headerless,
                        # 3 gdeflate, 4 zstd
                        'compression': comp,
                        'compressed_size': w0 & 0xFFFFFFF,
                        'size': w1 & 0xFFFFFFF,
                        'offset': 16 * w3,
                    }
                    info.setdefault('parts', []).append(part)
        return info

    def raw_payload(self, path_or_hash, part):
        """Read the raw (still compressed) bytes of a plain/mip metadata part."""
        if self._fh is None:
            with open(self.path, 'rb') as fh:
                fh.seek(part['offset'])
                return fh.read(part['compressed_size'])
        self._fh.seek(part['offset'])
        return self._fh.read(part['compressed_size'])

    def read_dir(self, path_or_hash):
        data = self.read(path_or_hash)
        if data is None:
            return None
        if len(data) < 4:
            return [], []
        count = struct.unpack_from('<I', data, 0)[0]
        sizes = data[4:4 + count]
        off = 4 + count
        dirs, files = [], []
        for i in range(count):
            n = sizes[i]
            item = data[off:off + n]
            off += n
            s = item.decode('utf-8', 'replace')
            if s.startswith('/'):
                dirs.append(s[1:])
            else:
                files.append(s)
        return dirs, files

    # ---------------------------------------------------------------- listing
    def list_files(self, roots=('',), progress=None):
        """Walk the stored directory tree and return every file path."""
        root = None
        for cand in roots:
            if cityhash64(cand) in self.entries:
                root = cand
                break
        if root is None:
            return []
        seen = set()
        stack = [root]
        files = []
        dirs = []
        while stack:
            d = stack.pop()
            if d in seen:
                continue
            seen.add(d)
            dirs.append(d)
            res = self.read_dir(d)
            if res is None:
                continue
            subdirs, fs = res
            prefix = d + '/' if d else ''
            for sd in subdirs:
                stack.append(prefix + sd)
            for f in fs:
                files.append(prefix + f)
            if progress and len(dirs) % 200 == 0:
                progress(len(dirs), len(files))
        self.dirs = sorted(dirs)
        self.files = sorted(files)
        return self.files

    def close(self):
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def sanity_check(directory, only=None, limit=None):
    import time
    names = only or sorted(f for f in os.listdir(directory) if f.lower().endswith('.scs'))
    for n in names:
        p = os.path.join(directory, n)
        t0 = time.time()
        try:
            a = ScsArchive(p)
            files = a.list_files()
            print(f'{n:34s} entries={a.entry_count:7d} dirs={len(a.dirs):6d} '
                  f'files={len(files):7d}  {time.time()-t0:6.2f}s')
            for f in files[:limit or 0]:
                print('     ', f)
            a.close()
        except ScsError as exc:
            print(f'{n:34s} SKIP: {exc}')


if __name__ == '__main__':
    import sys
    base = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
    args = sys.argv[1:]
    if args:
        a = ScsArchive(os.path.join(base, args[0]))
        files = a.list_files()
        print(f'{args[0]}: {a.entry_count} entries, {len(a.dirs)} dirs, {len(files)} files')
        n = int(args[1]) if len(args) > 1 else 40
        for f in files[:n]:
            print('  ', f)
        a.close()
    else:
        sanity_check(base, only=['version.scs', 'core.scs', 'def.scs'], limit=25)