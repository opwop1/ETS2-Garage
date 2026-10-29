"""Prism3D .pmd (model descriptor) parser - version 4.

Holds the material list per "look", plus variants/parts/attribute values.
Geometry lives in the sibling .pmg file.

Reference layout: ConverterPIX src/structs/pmd.h
"""
import struct

from tokens import decode_token

PMD_VERSION = 4
HEADER = struct.Struct('<16I')
HEADER_SIZE = 64
assert HEADER.size == HEADER_SIZE
ATTRIB_DEF = struct.Struct('<8sii')
ATTRIB_LINK = struct.Struct('<ii')


class Pmd:
    def __init__(self, data):
        self.data = data
        (self.version, self.material_count, self.look_count, self.piece_count,
         self.variant_count, self.part_count, self.attribs_count,
         self.attribs_values_size, self.material_block_size,
         self.look_offset, self.variant_offset, self.part_attribs_offset,
         self.attribs_value_offset, self.attribs_offset, self.material_offset,
         self.material_data_offset) = HEADER.unpack_from(data, 0)
        if self.version != PMD_VERSION:
            raise ValueError(f'unsupported PMD version {self.version}')
        self.looks = []
        self.variants = []
        self.parts = []
        self._parse_looks()
        self._parse_variants()

    def _cstr(self, offset):
        end = self.data.find(b'\x00', offset)
        if end < 0:
            end = len(self.data)
        return self.data[offset:end].decode('utf-8', 'replace')

    def _parse_looks(self):
        for i in range(self.look_count):
            raw = self.data[self.look_offset + i * 8:self.look_offset + i * 8 + 8]
            name = decode_token(raw)
            materials = []
            for j in range(self.material_count):
                slot = (i * self.material_count + j) * 4
                off = struct.unpack_from('<I', self.data, self.material_offset + slot)[0]
                materials.append(self._cstr(off))
            self.looks.append({'name': name, 'materials': materials})

    def _parse_variants(self):
        for i in range(self.variant_count):
            raw = self.data[self.variant_offset + i * 8:self.variant_offset + i * 8 + 8]
            name = decode_token(raw)
            parts = []
            for j in range(self.part_count):
                link_off = self.part_attribs_offset + j * ATTRIB_LINK.size
                frm, to = ATTRIB_LINK.unpack_from(self.data, link_off)
                attrs = {}
                for k in range(frm, to):
                    doff = self.attribs_offset + k * ATTRIB_DEF.size
                    nraw, atype, aoff = ATTRIB_DEF.unpack_from(self.data, doff)
                    voff = (self.attribs_value_offset + aoff
                            + i * self.attribs_values_size)
                    if voff + 4 > len(self.data):
                        continue
                    val = struct.unpack_from('<i', self.data, voff)[0]
                    attrs[decode_token(nraw)] = val
                parts.append(attrs)
            self.variants.append({'name': name, 'parts': parts})

    def material_list(self, look=None):
        if not self.looks:
            return []
        if look is None:
            return self.looks[0]['materials']
        for l in self.looks:
            if l['name'] == look:
                return l['materials']
        return self.looks[0]['materials']