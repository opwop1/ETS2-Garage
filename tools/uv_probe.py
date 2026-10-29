"""Decide which UV channel the paint-job mask is sampled with."""
import io
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'ets2garage'))
from scs import ScsVfs, open_archives          # noqa: E402
from pmg import Pmg                            # noqa: E402
from texture import extract_texture            # noqa: E402

BASE = r'D:\SteamLibrary\steamapps\common\Euro Truck Simulator 2'
vfs = ScsVfs(open_archives(BASE)).index()

MASK = 'vehicle/truck/upgrade/paintjob/scania_s_2016/academy/pjm_at_0x6144_size_2048x2048.tobj'
dds, info = extract_texture(vfs, MASK)
im = Image.open(io.BytesIO(dds))
im.load()
mask = np.asarray(im.convert('RGBA')).astype(np.float32) / 255.0
print('mask', mask.shape, 'unique-ish levels:',
      len(np.unique((mask[..., :3] * 8).astype(np.int32).reshape(-1, 3), axis=0)))

pmg = Pmg(vfs.read('vehicle/truck/scania_2016/cabin/cab_s_low.pmg'))
for p in pmg.pieces:
    if p.material != 3 or not p.uvs:      # piece 3 is the 8701-vertex cabin shell
        continue
    arr = np.asarray(p.uvs, dtype=np.float32)      # (n, 2*w)
    w = max(1, p.uv_width)
    print(f'piece {p.index} verts={p.verts} uv_width={w}')
    h, wid = mask.shape[:2]
    for c in range(w):
        uv = arr[:, 2 * c:2 * c + 2]
        xs = np.clip((uv[:, 0] % 1.0) * (wid - 1), 0, wid - 1).astype(np.int32)
        ys = np.clip((uv[:, 1] % 1.0) * (h - 1), 0, h - 1).astype(np.int32)
        px = mask[ys, xs, :3]
        onehot = np.min(np.abs(px - np.array([1, 0, 0])), axis=1)
        onehot = np.minimum(onehot, np.min(np.abs(px - np.array([0, 1, 0])), axis=1))
        onehot = np.minimum(onehot, np.min(np.abs(px - np.array([0, 0, 1])), axis=1))
        onehot = np.minimum(onehot, np.min(np.abs(px - np.array([0, 0, 0])), axis=1))
        frac = float((onehot < 0.15).mean())
        print(f'   uv{c}: distinct={len(np.unique((px*8).astype(np.int32).reshape(-1,3),axis=0))} '
              f'onehot-fraction={frac:.3f} mean={px.mean(axis=0).round(3)}')
    break