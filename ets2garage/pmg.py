"""Prism3D .pmg (model geometry) parser - version 0x15 (21) and 0x14.

Layout documented by the ConverterPIX project (src/structs/pmg_0x15.h).
File structure:
    0                    pmg_header_t                (112 bytes)
    m_skeleton_offset    pmg_bone_data_t[bone_count] (200 bytes each)
    m_parts_offset       pmg_part_t[part_count]      (24 bytes each)
    m_locators_offset    pmg_locator_t[locator_count] (44 bytes each)
    m_pieces_offset      pmg_piece_t[piece_count]    (100 bytes each)
    m_string_pool_offset string pool
    m_vertex_pool_offset vertex data
    m_index_pool_offset  index data
"""
import struct

HDR = struct.Struct('<B3siiiiiQ3ff6f10i')
HDR_SIZE = 112
assert HDR.size == HDR_SIZE, HDR.size

BONE = struct.Struct('<8s64s64s16s16s12s12sfB3s')
assert BONE.size == 200, BONE.size

PART = struct.Struct('<8siiii')
assert PART.size == 24

LOCATOR = struct.Struct('<8s3ff4fi')
assert LOCATOR.size == 44

PIECE = struct.Struct('<iiIii3ff6f10i')
assert PIECE.size == 100, PIECE.size


TOKEN_LETTERS = ('\x00' + '0123456789' + 'abcdefghijklmnopqrstuvwxyz' + '_')
TOKEN_RADIX = 38


def _token(raw):
    """SCS 8-byte token: little-endian base-38 packed name (see ConverterPIX utils/token).

    Alphabet index 0 terminates; digits are 1..10, a-z are 11..36, '_' is 37.
    """
    v = int.from_bytes(raw, 'little')
    if v == 0:
        return ''
    out = []
    while v:
        v, rem = divmod(v, TOKEN_RADIX)
        out.append(TOKEN_LETTERS[rem])
    return ''.join(out)


class Locator:
    __slots__ = ('index', 'name', 'raw_name', 'position', 'scale', 'rotation', 'hookup')

    def __repr__(self):
        return (f'<Locator {self.name!r} pos=({self.position[0]:.3f},'
                f'{self.position[1]:.3f},{self.position[2]:.3f})>')


class Piece:
    __slots__ = ('index', 'material', 'verts', 'edges', 'uv_width', 'uv_mask',
                 'offsets', 'stride', 'positions', 'normals', 'uvs', 'indices',
                 'bone_index_off', 'bone_weight_off', 'color_off', 'factor_off',
                 'bb_center', 'bb', 'bb_diag')


class Pmg:
    def __init__(self, data):
        self.data = data
        (self.version, sig, self.piece_count, self.part_count, self.bone_count,
         self.weight_width, self.locator_count, self.skeleton_hash,
         self.bb_center_x, self.bb_center_y, self.bb_center_z, self.bb_diagonal,
         *rest) = HDR.unpack_from(data, 0)
        (self.bb_min_x, self.bb_min_y, self.bb_min_z,
         self.bb_max_x, self.bb_max_y, self.bb_max_z,
         self.skeleton_offset, self.parts_offset, self.locators_offset,
         self.pieces_offset, self.string_pool_offset, self.string_pool_size,
         self.vertex_pool_offset, self.vertex_pool_size,
         self.index_pool_offset, self.index_pool_size) = rest
        self.signature = sig
        self.parts = []
        self.locators = []
        self.pieces = []
        self.piece_part = [0] * max(0, self.piece_count)
        self.locator_part = [0] * max(0, self.locator_count)
        self._parse_parts()
        self._parse_locators()
        self._parse_pieces()
        self._map_parts()

    def _map_parts(self):
        """Attribute every piece/locator to the part that owns it.

        Truck models bundle several configuration variants side by side (all
        chassis types, all cabins); the PMD variant table then decides which
        parts are drawn. Without that mapping every wheel of every axle
        configuration would be drawn at once.
        """
        for pi, part in enumerate(self.parts):
            for k in range(part['piece_count']):
                idx = part['piece_idx'] + k
                if 0 <= idx < len(self.piece_part):
                    self.piece_part[idx] = pi
            for k in range(part['locator_count']):
                idx = part['locator_idx'] + k
                if 0 <= idx < len(self.locator_part):
                    self.locator_part[idx] = pi

    # ------------------------------------------------------------------ parts
    def _parse_parts(self):
        for i in range(self.part_count):
            off = self.parts_offset + i * PART.size
            raw, pc, pid, lc, lid = PART.unpack_from(self.data, off)
            self.parts.append(dict(name=_token(raw) or raw.hex(), piece_count=pc,
                                   piece_idx=pid, locator_count=lc, locator_idx=lid))

    # --------------------------------------------------------------- locators
    def _hookup(self, offset):
        if offset == -1 or self.string_pool_size <= 0:
            return None
        start = self.string_pool_offset + offset
        end = min(start + (self.string_pool_size - offset), len(self.data))
        raw = self.data[start:end]
        return raw.split(b'\x00')[0].decode('utf-8', 'replace')

    def _parse_locators(self):
        for i in range(self.locator_count):
            off = self.locators_offset + i * LOCATOR.size
            (raw, px, py, pz, scale, rw, rx, ry, rz, hook) = LOCATOR.unpack_from(self.data, off)
            loc = Locator()
            loc.index = i
            loc.raw_name = raw
            loc.name = _token(raw)
            loc.position = (px, py, pz)
            loc.scale = scale
            loc.rotation = (rw, rx, ry, rz)
            loc.hookup = self._hookup(hook)
            self.locators.append(loc)

    # ----------------------------------------------------------------- pieces
    def _parse_pieces(self):
        for i in range(self.piece_count):
            off = self.pieces_offset + i * PIECE.size
            (edges, verts, uv_mask, uv_width, material,
             bcx, bcy, bcz, bbdiag,
             bminx, bminy, bminz, bmaxx, bmaxy, bmaxz,
             skel_off, pos_off, nrm_off, uv_off, col_off, fac_off, tan_off,
             bone_off, bonew_off, idx_off) = PIECE.unpack_from(self.data, off)
            p = Piece()
            p.index = i
            p.material = material
            p.verts = verts
            p.edges = edges
            p.uv_width = uv_width
            p.uv_mask = uv_mask
            p.bb_center = (bcx, bcy, bcz)
            p.bb = (bminx, bminy, bminz, bmaxx, bmaxy, bmaxz)
            p.bb_diag = bbdiag
            p.offsets = dict(skeleton=skel_off, position=pos_off, normal=nrm_off,
                             uv=uv_off, color=col_off, factor=fac_off,
                             tangent=tan_off, index=idx_off, bone=bone_off,
                             bone_weight=bonew_off)
            stride = 0
            if pos_off != -1:
                stride += 12
            if nrm_off != -1:
                stride += 12
            if tan_off != -1:
                stride += 16
            if uv_off != -1:
                stride += 8 * max(1, uv_width)
            if col_off != -1:
                stride += 4
            if fac_off != -1:
                stride += 4
            if bone_off != -1:
                stride += 8
            p.stride = stride
            self.pieces.append(p)
            if stride == 0 and verts:
                continue
            self._read_vertices(p)

    def _read_vertices(self, p):
        d = self.data
        st = p.stride
        if p.offsets['position'] != -1:
            base = p.offsets['position']
            p.positions = [struct.unpack_from('<3f', d, base + st * j) for j in range(p.verts)]
        else:
            p.positions = None
        if p.offsets['normal'] != -1:
            base = p.offsets['normal']
            p.normals = [struct.unpack_from('<3f', d, base + st * j) for j in range(p.verts)]
        else:
            p.normals = None
        if p.offsets['uv'] != -1:
            base = p.offsets['uv']
            w = max(1, p.uv_width)
            # SCS stores up to 3 UV sets per vertex; carriers such as the paint
            # job mask are sampled with UV1/UV2.
            p.uvs = [struct.unpack_from(f'<{2 * w}f', d, base + st * j)
                     for j in range(p.verts)]
        else:
            p.uvs = None
        if p.offsets['index'] != -1:
            base = p.offsets['index']
            n = p.edges // 3
            p.indices = [struct.unpack_from('<3H', d, base + 6 * j) for j in range(n)]
        else:
            p.indices = None

    # ------------------------------------------------------------------ stats
    def total_vertices(self):
        return sum(p.verts for p in self.pieces)

    def total_triangles(self):
        return sum(p.edges // 3 for p in self.pieces)


if __name__ == '__main__':
    import sys
    data = open(sys.argv[1] if len(sys.argv) > 1 else 'cab_s_low.pmg', 'rb').read()
    m = Pmg(data)
    print(f'version=0x{m.version:02x} sig={m.signature!r} pieces={m.piece_count} '
          f'parts={m.part_count} bones={m.bone_count} locators={m.locator_count}')
    print(f'vertices={m.total_vertices()} triangles={m.total_triangles()}')
    print(f'bb_center={m.bb_center_x:.3f},{m.bb_center_y:.3f},{m.bb_center_z:.3f}')
    print('\nparts:')
    for p in m.parts:
        print('  ', p)
    print('\nlocators:')
    for l in m.locators[:80]:
        n = l.name if l.name else l.raw_name.hex()
        print(f'   {l.index:3d} {n:24s} pos=({l.position[0]:9.4f},{l.position[1]:9.4f},'
              f'{l.position[2]:9.4f}) scale={l.scale:.3f} hookup={l.hookup!r}')
    print('\npieces:')
    for p in m.pieces:
        print(f'   #{p.index} mat={p.material} verts={p.verts} tris={p.edges//3} stride={p.stride}')
        if p.positions:
            print('      v0', p.positions[0], 'v1', p.positions[1] if p.verts > 1 else '')