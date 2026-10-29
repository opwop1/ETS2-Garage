import * as THREE from 'three';
import { OrbitControls } from 'three/addons/OrbitControls.js';
import { TransformControls } from 'three/addons/TransformControls.js';

/* ------------------------------------------------------------------ state */
const state = {
  category: 'truck',
  vehicles: [],
  current: null,          // vehicle detail
  config: { parts: {}, accessories: {} },
  instances: [],
  materials: {},
  locatorPoints: [],
  selectedSlot: null,
  autoAccessories: {},
  edits: {},              // slot -> {pos:[x,y,z], rot:[x,y,z] deg, scale}
  groups: {},             // slot -> THREE.Group carrying the final transform
  bases: {},              // slot -> locator (base) transform
  selectedKey: null,
  hostLocators: new Set(),
  coordRows: [],
};

const el = (id) => document.getElementById(id);

// When the local service is gone the page cannot do anything useful; say so
// once instead of throwing a wall of "Failed to fetch" for every click.
let serverLost = false;
function markServerLost() {
  if (serverLost) return;
  serverLost = true;
  const hint = el('viewportHint');
  if (hint) {
    hint.textContent = '本地服务已断开，请关闭窗口后重新打开 ETS2Garage.exe';
    hint.classList.remove('hidden');
  }
  const t = el('toast');
  if (t) {
    t.textContent = '本地服务已断开，请重新启动程序';
    t.classList.remove('hidden');
  }
}

const api = async (url, opts) => {
  let r;
  try {
    r = await fetch(url, opts);
  } catch (e) {
    markServerLost();
    throw e;
  }
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).error || msg; } catch (e) { /* ignore */ }
    throw new Error(msg);
  }
  return r;
};
const apiJson = async (url, opts) => (await api(url, opts)).json();
const deg = (r) => (r * 180) / Math.PI;
const rad = (d) => (d * Math.PI) / 180;
const fmt = (v, n = 4) => (Math.abs(v) < 5e-5 ? '0' : v.toFixed(n));

const PART_LABELS = { cabin: '驾驶室', body: '车身', chassis: '底盘' };

let toastTimer = 0;
function toast(msg) {
  const t = el('toast');
  if (!t) return;
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), 2200);
}

/* ---------------------------------------------------------------- three.js */
const canvas = el('gl');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.05, 400);

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.dampingFactor = 0.08;
controls.target.set(0, 2, 0);

scene.add(new THREE.HemisphereLight(0xbcd6ff, 0x2b3140, 1.15));
const keyLight = new THREE.DirectionalLight(0xffffff, 2.1);
keyLight.position.set(6, 11, 7);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0x8fb6ff, 0.85);
fillLight.position.set(-8, 5, -6);
scene.add(fillLight);
const rimLight = new THREE.DirectionalLight(0xffd7a0, 0.6);
rimLight.position.set(0, 4, -10);
scene.add(rimLight);

const grid = new THREE.GridHelper(30, 30, 0x2c3a52, 0x1b2537);
scene.add(grid);

const truckRoot = new THREE.Group();
scene.add(truckRoot);
const locatorRoot = new THREE.Group();
scene.add(locatorRoot);

/* -------------------------------------------------------- transform gizmo */
const gizmo = new TransformControls(camera, renderer.domElement);
gizmo.setSize(0.9);
gizmo.setSpace('world');
gizmo.addEventListener('dragging-changed', (e) => { controls.enabled = !e.value; });
gizmo.addEventListener('objectChange', () => { onGizmoChange(); });
scene.add(gizmo);

let lastW = 0, lastH = 0, lastDpr = 0;

/**
 * Keep the drawing buffer and the camera aspect in lockstep with the element.
 *
 * A `window.resize` listener alone is not enough: the event can fire before the
 * new layout is committed, and layout-only changes (panels, DPI switch) never
 * fire it at all -- which shows up as a stretched model. So this is also polled
 * once per frame; the early-out makes that essentially free.
 */
function resize(force = false) {
  const w = Math.max(1, canvas.clientWidth);
  const h = Math.max(1, canvas.clientHeight);
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  if (!force && w === lastW && h === lastH && dpr === lastDpr) return false;
  lastW = w;
  lastH = h;
  lastDpr = dpr;
  renderer.setPixelRatio(dpr);
  renderer.setSize(w, h, false);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
  return true;
}
window.addEventListener('resize', () => resize());
window.addEventListener('orientationchange', () => resize());
if (window.ResizeObserver) {
  new ResizeObserver(() => resize()).observe(canvas.parentElement || canvas);
}

const textureLoader = new THREE.TextureLoader();
const texCache = new Map();
function getTexture(url) {
  if (!url) return null;
  if (texCache.has(url)) return texCache.get(url);
  const t = textureLoader.load(url);
  t.colorSpace = THREE.SRGBColorSpace;
  t.anisotropy = 4;
  texCache.set(url, t);
  return t;
}
function disposeGroup(g) {
  g.traverse((o) => {
    if (o.isMesh) {
      o.geometry.dispose();
      if (o.material && o.material.__owned) o.material.dispose();
    }
  });
  g.clear();
}

/* -------------------------------------------------------------- transform */
function identityEdit() { return { pos: [0, 0, 0], rot: [0, 0, 0], scale: 1 }; }

function getEdit(slot) {
  if (!state.edits[slot]) state.edits[slot] = identityEdit();
  return state.edits[slot];
}

function hasEdit(slot) {
  const e = state.edits[slot];
  if (!e) return false;
  return e.pos.some((v) => Math.abs(v) > 1e-5)
    || e.rot.some((v) => Math.abs(v) > 1e-4)
    || Math.abs(e.scale - 1) > 1e-4;
}

/** Compose the locator (base) transform with the user edit. */
function composeTransform(base, edit) {
  const pos = new THREE.Vector3(
    base.position[0] + edit.pos[0],
    base.position[1] + edit.pos[1],
    base.position[2] + edit.pos[2],
  );
  const baseQ = new THREE.Quaternion(
    base.rotation[1], base.rotation[2], base.rotation[3], base.rotation[0]);
  const dq = new THREE.Quaternion().setFromEuler(
    new THREE.Euler(rad(edit.rot[0]), rad(edit.rot[1]), rad(edit.rot[2]), 'XYZ'));
  return { pos, quat: dq.multiply(baseQ), scale: (base.scale || 1) * edit.scale };
}

function applyEditToGroup(g, base, edit) {
  const t = composeTransform(base, edit);
  g.position.copy(t.pos);
  g.quaternion.copy(t.quat);
  g.scale.setScalar(t.scale);
  g.updateMatrixWorld(true);
}

/** Read a manipulated group back into the stored edit values. */
function onGizmoChange() {
  const slot = state.selectedKey;
  if (!slot) return;
  const g = state.groups[slot];
  const base = state.bases[slot];
  if (!g || !base) return;
  const edit = getEdit(slot);
  edit.pos = [
    g.position.x - base.position[0],
    g.position.y - base.position[1],
    g.position.z - base.position[2],
  ];
  const baseQ = new THREE.Quaternion(
    base.rotation[1], base.rotation[2], base.rotation[3], base.rotation[0]).invert();
  const dq = g.quaternion.clone().multiply(baseQ);
  const e = new THREE.Euler().setFromQuaternion(dq, 'XYZ');
  edit.rot = [deg(e.x), deg(e.y), deg(e.z)];
  edit.scale = g.scale.x / (base.scale || 1);
  syncEditPanel();
  renderCoordTable();
  renderSlots();
}

/* -------------------------------------------------------------- selection */
function isEditable(slot) {
  const inst = state.instances.find((i) => i.slot === slot);
  return !!inst && inst.kind === 'accessory';
}

function selectSlot(slot) {
  const g = state.groups[slot];
  if (!g) { clearSelection(); return; }
  // the cabin / body / chassis shell is the reference frame -- never move it
  if (!isEditable(slot)) {
    el('editHint').classList.remove('hidden');
    return;
  }
  state.selectedKey = slot;
  gizmo.attach(g);
  el('editPanel').classList.remove('hidden');
  el('editHint').classList.add('hidden');
  const inst = state.instances.find((i) => i.slot === slot);
  const opt = (state.autoAccessories[slot] || []).find((o) => o.path === inst?.def)
    || (state.current?.slots.find((s) => s.slot === slot)?.options || [])
      .find((o) => o.path === inst?.def);
  const name = (opt && opt.name) || (inst && (inst.source || inst.model)) || slot;
  el('editTitle').textContent = `${PART_LABELS[inst?.kind] || slot} · ${name}`;
  syncEditPanel();
  renderCoordTable();
  renderSlots();
  updateLocatorHighlight();
}

function clearSelection() {
  state.selectedKey = null;
  gizmo.detach();
  el('editPanel').classList.add('hidden');
  if (truckRoot.children.length) el('editHint').classList.remove('hidden');
  renderCoordTable();
  renderSlots();
  updateLocatorHighlight();
}

/* ------------------------------------------------------------- edit panel */
const EP_FIELDS = [
  ['epPX', 'pos', 0], ['epPY', 'pos', 1], ['epPZ', 'pos', 2],
  ['epRX', 'rot', 0], ['epRY', 'rot', 1], ['epRZ', 'rot', 2],
];
const EP_AXIS = {
  px: ['pos', 0], py: ['pos', 1], pz: ['pos', 2],
  rx: ['rot', 0], ry: ['rot', 1], rz: ['rot', 2],
  s: ['scale', -1],
};

function syncEditPanel() {
  const slot = state.selectedKey;
  if (!slot) return;
  const e = getEdit(slot);
  el('epPX').value = fmt(e.pos[0], 3);
  el('epPY').value = fmt(e.pos[1], 3);
  el('epPZ').value = fmt(e.pos[2], 3);
  el('epRX').value = fmt(e.rot[0], 1);
  el('epRY').value = fmt(e.rot[1], 1);
  el('epRZ').value = fmt(e.rot[2], 1);
  el('epS').value = fmt(e.scale, 3);
  updateReadout();
}

function commitEdit(slot) {
  const g = state.groups[slot];
  const base = state.bases[slot];
  if (!g || !base) return;
  applyEditToGroup(g, base, getEdit(slot));
  updateReadout();
  renderCoordTable();
  renderSlots();
  updateLocatorHighlight();
}

function updateReadout() {
  const box = el('epReadout');
  const slot = state.selectedKey;
  if (!slot) { box.innerHTML = ''; return; }
  const g = state.groups[slot];
  const base = state.bases[slot];
  if (!g || !base) { box.innerHTML = ''; return; }
  const e = getEdit(slot);
  const p = g.position;
  box.innerHTML =
    `<span class="k">挂点</span> ${base.locatorName || '—'} `
    + `<span class="k">基座</span> (${fmt(base.position[0], 3)}, ${fmt(base.position[1], 3)}, ${fmt(base.position[2], 3)})<br>`
    + `<span class="k">偏移</span> (${fmt(e.pos[0], 4)}, ${fmt(e.pos[1], 4)}, ${fmt(e.pos[2], 4)})<br>`
    + `<span class="k">旋转</span> (${fmt(e.rot[0], 1)}°, ${fmt(e.rot[1], 1)}°, ${fmt(e.rot[2], 1)}°) `
    + `<span class="k">缩放</span> ${fmt(e.scale, 3)}<br>`
    + `<span class="hi">最终坐标</span> <span class="hi">X ${fmt(p.x, 4)}  Y ${fmt(p.y, 4)}  Z ${fmt(p.z, 4)}</span>`;
}

function bump(axis, dir) {
  const slot = state.selectedKey;
  if (!slot) return;
  const e = getEdit(slot);
  const step = parseFloat(el('epStep').value) || 0.01;
  const [kind, idx] = EP_AXIS[axis];
  if (kind === 'scale') e.scale = Math.max(0.05, e.scale + dir * 0.01);
  else if (kind === 'rot') e.rot[idx] += dir * (step < 0.01 ? 1 : Math.round(step * 100));
  else e.pos[idx] += dir * step;
  commitEdit(slot);
  syncEditPanel();
}

function setEditValue(kind, idx, value) {
  const slot = state.selectedKey;
  if (!slot || !isFinite(value)) return;
  const e = getEdit(slot);
  if (kind === 'scale') e.scale = Math.max(0.05, value);
  else e[kind][idx] = value;
  commitEdit(slot);
  updateReadout();
}

function setGizmoMode(mode) {
  gizmo.setMode(mode);
  gizmo.setSpace(mode === 'translate' ? 'world' : 'local');
  document.querySelectorAll('.ep-mode').forEach((x) => {
    x.classList.toggle('active', x.dataset.mode === mode);
  });
}

document.querySelectorAll('.ep-mode').forEach((b) => {
  b.onclick = () => setGizmoMode(b.dataset.mode);
});
EP_FIELDS.forEach(([id, kind, idx]) => {
  el(id).addEventListener('change', (ev) => setEditValue(kind, idx, parseFloat(ev.target.value)));
});
el('epS').addEventListener('change', (ev) => setEditValue('scale', -1, parseFloat(ev.target.value)));
document.querySelectorAll('.ep-ctl button[data-axis]').forEach((b) => {
  b.onclick = () => bump(b.dataset.axis, parseInt(b.dataset.d, 10));
});
el('editClose').onclick = clearSelection;
el('editReset').onclick = () => {
  if (!state.selectedKey) return;
  state.edits[state.selectedKey] = identityEdit();
  commitEdit(state.selectedKey);
  syncEditPanel();
};
el('editResetAll').onclick = () => {
  state.edits = {};
  for (const [slot, g] of Object.entries(state.groups)) {
    const base = state.bases[slot];
    if (base) applyEditToGroup(g, base, getEdit(slot));
  }
  syncEditPanel();
  renderCoordTable();
  renderSlots();
};

/** Drop the selected part so its bounding box rests on the surface below it. */
el('epDrop').onclick = () => {
  const slot = state.selectedKey;
  const g = state.groups[slot];
  if (!g) return;
  const hosts = Object.entries(state.groups)
    .filter(([k]) => k !== slot).map(([, grp]) => grp);
  const box = new THREE.Box3().setFromObject(g);
  if (box.isEmpty()) return;
  ray.set(new THREE.Vector3(g.position.x, g.position.y + 6, g.position.z),
          new THREE.Vector3(0, -1, 0));
  const hits = ray.intersectObjects(hosts, true);
  if (!hits.length) return;
  const hitY = hits[0].point.y;
  const localMin = box.min.y - g.position.y;
  const targetY = hitY + 0.002 - localMin;
  const e = getEdit(slot);
  e.pos[1] += targetY - g.position.y;
  commitEdit(slot);
  syncEditPanel();
};

/* --------------------------------------------------------------- locators */
const LOC_COLOR = 0x4da3ff;
const LOC_ACTIVE = 0xffab3d;
const ray = new THREE.Raycaster();

function updateLocatorHighlight() {
  const activeName = state.selectedKey ? state.bases[state.selectedKey]?.locatorName : null;
  for (const p of state.locatorPoints) {
    const l = p.userData.locator;
    const active = activeName && p.userData.instSlot === state.selectedKey && l.name === activeName;
    p.material.color.setHex(active ? LOC_ACTIVE : LOC_COLOR);
    p.scale.setScalar(active ? 2.4 : 1);
  }
}

/* ------------------------------------------------------------------- mesh */
async function buildInstance(inst) {
  const blob = await api('/api/mesh?path=' + encodeURIComponent(inst.path)).then((r) => r.arrayBuffer());
  const group = new THREE.Group();
  for (const p of inst.pieces) {
    if (p.skip) continue;
    const s = p.sections;
    if (!s.position || !s.index) continue;
    const g = new THREE.BufferGeometry();
    const n = p.count;
    g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(blob, s.position[0], n * 3), 3));
    if (s.normal) g.setAttribute('normal', new THREE.BufferAttribute(new Float32Array(blob, s.normal[0], n * 3), 3));
    if (s.uv0) g.setAttribute('uv', new THREE.BufferAttribute(new Float32Array(blob, s.uv0[0], n * 2), 2));
    if (s.uv1) g.setAttribute('uv1', new THREE.BufferAttribute(new Float32Array(blob, s.uv1[0], n * 2), 2));
    if (s.color) {
      const src = new Uint8Array(blob, s.color[0], n * 4);
      const col = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        col[i * 3] = Math.min(1, (src[i * 4] / 255) * 2);
        col[i * 3 + 1] = Math.min(1, (src[i * 4 + 1] / 255) * 2);
        col[i * 3 + 2] = Math.min(1, (src[i * 4 + 2] / 255) * 2);
      }
      g.setAttribute('color', new THREE.BufferAttribute(col, 3));
    }
    g.setIndex(new THREE.BufferAttribute(new Uint16Array(blob, s.index[0], p.triangles * 3), 1));
    if (!s.normal) g.computeVertexNormals();

    const mdef = state.materials[p.material_path] || {};
    const pdef = mdef.paint || null;
    const livery = pdef && pdef.mask ? makeLivery(pdef) : null;
    let mat;
    if (livery) {
      mat = new THREE.MeshStandardMaterial({
        color: 0xffffff,
        map: whiteTexture(),
        vertexColors: !!s.color,
        roughness: 0.3,
        metalness: 0.3,
        side: THREE.DoubleSide,
        wireframe: el('showWire').checked,
      });
      applyLivery(mat, livery);
    } else {
      const base = pdef ? pdef.base : null;
      mat = new THREE.MeshStandardMaterial({
        color: base
          ? new THREE.Color(base[0], base[1], base[2])
          : (mdef.diffuse ? new THREE.Color(mdef.diffuse[0], mdef.diffuse[1], mdef.diffuse[2]) : 0xffffff),
        map: (!mdef.is_paint && mdef.base_url) ? getTexture(mdef.base_url) : null,
        vertexColors: !!s.color,
        roughness: mdef.is_paint ? 0.35 : 0.6,
        metalness: mdef.is_paint ? 0.28 : 0.15,
        side: THREE.DoubleSide,
        wireframe: el('showWire').checked,
      });
    }
    mat.__owned = true;
    group.add(new THREE.Mesh(g, mat));
  }
  return group;
}

/* ------------------------------------------------------- paint / livery */
const paintMaskCache = new Map();
let _whiteTex = null;
function whiteTexture() {
  if (!_whiteTex) {
    const d = new Uint8Array([255, 255, 255, 255]);
    _whiteTex = new THREE.DataTexture(d, 1, 1, THREE.RGBAFormat);
    _whiteTex.colorSpace = THREE.SRGBColorSpace;
    _whiteTex.needsUpdate = true;
  }
  return _whiteTex;
}

function makeLivery(pdef) {
  const variants = pdef.variants || [];
  if (!variants.length) return null;
  const v = Math.min(state.paintVariant || 0, Math.floor(variants.length / 4) - 1);
  const base = Math.max(0, v) * 4;
  const cols = [];
  for (let i = 0; i < 4; i++) {
    const c = variants[base + i] || variants[i] || [1, 1, 1];
    cols.push(new THREE.Color(c[0], c[1], c[2]));
  }
  let tex = paintMaskCache.get(pdef.mask_url);
  if (!tex) {
    tex = textureLoader.load(pdef.mask_url);
    tex.colorSpace = THREE.NoColorSpace;   // mask holds channel indices, not colour
    tex.wrapS = THREE.RepeatWrapping;
    tex.wrapT = THREE.RepeatWrapping;
    paintMaskCache.set(pdef.mask_url, tex);
  }
  return { mask: tex, cols, id: `${pdef.mask_url}#${base}` };
}

function applyLivery(mat, livery) {
  mat.userData.liveryId = livery.id;
  // force three.js to declare/populate the generic vUv varying
  mat.defines = Object.assign({}, mat.defines, { USE_UV: '' });
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.paintMask = { value: livery.mask };
    shader.uniforms.paintC0 = { value: livery.cols[0] };
    shader.uniforms.paintC1 = { value: livery.cols[1] };
    shader.uniforms.paintC2 = { value: livery.cols[2] };
    shader.uniforms.paintC3 = { value: livery.cols[3] };
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>',
        `#include <common>
         uniform sampler2D paintMask;
         uniform vec3 paintC0; uniform vec3 paintC1;
         uniform vec3 paintC2; uniform vec3 paintC3;`)
      .replace('#include <map_fragment>',
        `#include <map_fragment>
         {
           vec3 mk = texture2D( paintMask, vUv ).rgb;
           float w0 = max( 0.0, 1.0 - ( mk.r + mk.g + mk.b ) );
           float wsum = max( w0 + mk.r + mk.g + mk.b, 0.001 );
           vec3 livery = ( paintC0 * w0 + paintC1 * mk.r
                         + paintC2 * mk.g + paintC3 * mk.b ) / wsum;
           diffuseColor.rgb *= livery;
         }`);
  };
  mat.needsUpdate = true;
}

function fitCamera(box) {
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const radius = Math.max(size.length(), 2);
  const dist = (radius / Math.tan((camera.fov * Math.PI) / 360)) * 0.62;
  controls.target.copy(center);
  camera.position.set(center.x - dist * 0.8, center.y + dist * 0.42, center.z - dist * 0.85);
  camera.near = Math.max(0.05, radius / 200);
  camera.far = radius * 40;
  camera.updateProjectionMatrix();
  controls.update();
}

/* --------------------------------------------------------------- assembly */
async function refreshModel(autoFill = true) {
  if (!state.current) return;
  el('loading').classList.remove('hidden');
  el('loading').querySelector('span').textContent = '正在构建模型…';
  try {
    const data = await apiJson('/api/assemble', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        parts: state.config.parts,
        accessories: state.config.accessories,
        paint_job: state.config.paint_job || '',
        paint_color: state.paintColor || null,
      }),
    });
    state.instances = data.instances;
    state.materials = data.materials || {};
    gizmo.detach();
    disposeGroup(truckRoot);
    disposeGroup(locatorRoot);
    state.groups = {};
    state.bases = {};
    state.locatorPoints = [];
    state.hostLocators = new Set();

    let tris = 0;
    const box = new THREE.Box3();
    for (const inst of data.instances) {
      const hidden = !!inst.hidden;
      // hidden = geometry already included in another part (old trucks put the
      // whole vehicle into the cabin model); still used for locators
      const meshes = hidden ? new THREE.Group() : await buildInstance(inst);
      const outer = new THREE.Group();
      const base = {
        position: inst.transform.position.slice(),
        rotation: inst.transform.rotation.slice(),
        scale: inst.transform.scale,
        locatorName: inst.locator,
      };
      // wheels: one mesh set per locator, positioned relative to the first one
      if (inst.placements && inst.placements.length > 1) {
        const p0 = inst.placements[0];
        const m0 = new THREE.Matrix4().compose(
          new THREE.Vector3(p0.position[0], p0.position[1], p0.position[2]),
          new THREE.Quaternion(p0.rotation[1], p0.rotation[2], p0.rotation[3], p0.rotation[0]),
          new THREE.Vector3(p0.scale, p0.scale, p0.scale));
        const inv0 = new THREE.Matrix4().copy(m0).invert();
        for (let i = 1; i < inst.placements.length; i++) {
          const pi = inst.placements[i];
          const mi = new THREE.Matrix4().compose(
            new THREE.Vector3(pi.position[0], pi.position[1], pi.position[2]),
            new THREE.Quaternion(pi.rotation[1], pi.rotation[2], pi.rotation[3], pi.rotation[0]),
            new THREE.Vector3(pi.scale, pi.scale, pi.scale));
          const rel = new THREE.Matrix4().multiplyMatrices(inv0, mi);
          const clone = meshes.clone(true);
          rel.decompose(clone.position, clone.quaternion, clone.scale);
          outer.add(clone);
        }
      }
      outer.add(meshes);
      outer.userData.inst = inst;
      outer.userData.slot = inst.slot;
      state.groups[inst.slot] = outer;
      state.bases[inst.slot] = base;
      applyEditToGroup(outer, base, getEdit(inst.slot));
      truckRoot.add(outer);
      box.expandByObject(outer);
      const copies = (inst.placements && inst.placements.length) || 1;
      if (!hidden) tris += copies * inst.pieces.reduce((a, p) => a + (p.skip ? 0 : p.triangles), 0);

      const info = await apiJson('/api/locators?path=' + encodeURIComponent(inst.path)
        + '&variant=' + encodeURIComponent((inst.variants || []).join(',')));
      inst.locators = info;
      if (['cabin', 'chassis', 'body'].includes(inst.kind)) {
        for (const l of info) state.hostLocators.add(l.name);
      }
    }
    truckRoot.updateMatrixWorld(true);

    const geo = new THREE.SphereGeometry(0.045, 10, 8);
    const locMat = new THREE.MeshBasicMaterial({ color: LOC_COLOR, transparent: true, opacity: 0.85 });
    for (const outer of truckRoot.children) {
      const inst = outer.userData.inst;
      for (const l of (inst.locators || [])) {
        const m = new THREE.Mesh(geo, locMat);
        m.position.set(l.position[0], l.position[1], l.position[2]);
        m.applyMatrix4(outer.matrixWorld);
        m.userData.locator = l;
        m.userData.instSlot = inst.slot;
        locatorRoot.add(m);
        state.locatorPoints.push(m);
      }
    }
    locatorRoot.visible = el('showLocators').checked;

    // Slots this truck's model has attachment points for get the *factory* part
    // (never tuning parts), so every vehicle -- including future SCS ones --
    // comes out complete without any hard-coded slot list.
    if (autoFill && state.hostLocators.size && state.current) {
      let added = 0;
      for (const s of state.current.slots) {
        if (state.config.accessories[s.slot] || state.config.parts[s.slot]) continue;
        if (!slotHasLocator(s.slot)) continue;
        const o = factoryOption(s.slot);
        if (!o) continue;
        state.config.accessories[s.slot] = o.path;
        state.autoAccessories[s.slot] = s.options;
        added++;
      }
      if (added) {
        state.factoryCount = (state.factoryCount || 0) + added;
        await refreshModel(false);
        return;
      }
    }

    el('renderStats').textContent =
      `${data.instances.length} 个部件 · ${tris.toLocaleString()} 三角面 · ${Object.keys(state.materials).length} 材质`;
    if (!truckRoot.children.length) {
      el('viewportHint').classList.remove('hidden');
      el('viewportHint').textContent = '未能构建模型';
    } else {
      el('viewportHint').classList.add('hidden');
      if (!state.__fitted) { fitCamera(box); state.__fitted = true; }
    }
    if (data.warnings && data.warnings.length) console.warn(data.warnings);

    if (state.selectedKey && state.groups[state.selectedKey]) selectSlot(state.selectedKey);
    else if (!state.selectedKey) el('editHint').classList.remove('hidden');

    renderCoordTable(data.warnings || []);
    renderSlots();
  } catch (err) {
    console.error(err);
    el('viewportHint').classList.remove('hidden');
    el('viewportHint').textContent = '构建失败：' + err.message;
  } finally {
    el('loading').classList.add('hidden');
  }
}

/* ------------------------------------------------------------------ slots */
function renderSlots() {
  const host = el('slotList');
  host.innerHTML = '';
  const filter = el('slotSearch').value.trim().toLowerCase();
  const d = state.current;
  if (!d) return;
  const required = new Set(d.required_slots || []);
  const grouped = { wheel: [], required: [], optional: [] };
  for (const s of d.slots) {
    if (filter && !(`${s.slot} ${s.label || ''}`.toLowerCase().includes(filter))) continue;
    (s.wheel ? grouped.wheel : required.has(s.slot) ? grouped.required : grouped.optional).push(s);
  }
  const mk = (title, items) => {
    if (!items.length) return;
    const h = document.createElement('div');
    h.className = 'summary sub';
    h.style.padding = '8px 6px 4px';
    h.style.borderBottom = 'none';
    h.textContent = title + ` (${items.length})`;
    host.appendChild(h);
    for (const s of items) host.appendChild(slotCard(s));
  };
  mk('车轮', grouped.wheel);
  mk('必须装配', grouped.required);
  mk('可选配件', grouped.optional);
}

function slotCard(s) {
  const cur = state.config.accessories[s.slot];
  const hostTruck = state.current.id;
  const card = document.createElement('div');
  card.className = 'slot' + (cur ? '' : ' empty') + (state.selectedSlot === s.slot ? ' selected' : '');
  const info = (state.autoAccessories[s.slot] || s.options || []).find((o) => o.path === cur) || null;
  const inst = state.instances.find((i) => i.slot === s.slot);
  let value = '未装配';
  let extra = '';
  if (cur) {
    value = (info && info.name) || cur.split('/').pop();
    if (inst) {
      const g = state.groups[s.slot];
      const moved = hasEdit(s.slot) ? ' · <b style="color:#ffab3d">已调整</b>' : '';
      extra = (inst.locator ? 'locator ' + inst.locator : '无挂点（需手动放置）')
        + (g ? ` · (${fmt(g.position.x, 3)}, ${fmt(g.position.y, 3)}, ${fmt(g.position.z, 3)})` : '') + moved;
    }
  } else if (s.options.length) {
    value = `${s.options.length} 个原厂可选`;
  }
  const foreign = info && info.from_truck && info.from_truck !== hostTruck;
  card.innerHTML = `
    <div class="slot-head">
      <span class="slot-name">${s.label || s.slot}</span>
      ${s.wheel ? `<span class="slot-tag wheel">${s.slot}</span>` : ''}
      ${s.required ? '<span class="slot-tag">必需</span>' : ''}
      ${foreign ? `<span class="slot-tag mix">来自 ${info.from_truck}</span>` : ''}
      ${cur ? '<span class="slot-tag adj" title="调整位置">调整</span>' : ''}
    </div>
    <div class="slot-value">${value}</div>
    ${extra ? `<div class="slot-xyz">${extra}</div>` : ''}`;
  card.onclick = () => openPicker(s.slot);
  const adj = card.querySelector('.slot-tag.adj');
  if (adj) adj.onclick = (ev) => { ev.stopPropagation(); selectSlot(s.slot); };
  return card;
}

/* ----------------------------------------------------------------- picker */
async function openPicker(slot) {
  state.selectedSlot = slot;
  renderSlots();
  const modal = el('picker');
  modal.classList.remove('hidden');
  el('pickerTitle').textContent = `选择配件 · ${slot}`;
  el('pickerList').innerHTML = '<div class="muted" style="padding:14px">正在加载全部车辆的配件…</div>';
  el('pickerNote').textContent = '';
  const data = await apiJson('/api/slot?slot=' + encodeURIComponent(slot));
  state.autoAccessories[slot] = data.options;
  const names = state.hostLocators || new Set();
  const hostHasLocator = names.has(slot) || [...names].some((n) => n.startsWith(slot + '_'));
  el('pickerNote').textContent = hostHasLocator
    ? `共 ${data.count} 个来自全部车辆的「${slot}」配件可选；当前车辆模型存在挂点，装配后可用「调整」微调位置。`
    : `共 ${data.count} 个可选配件。注意：当前车辆模型没有「${slot}」挂点，配件会落在原点——选中后用箭头拖到正确位置即可。`;
  drawPicker(data.options, slot);
}

function drawPicker(options, slot) {
  const list = el('pickerList');
  const q = el('pickerSearch').value.trim().toLowerCase();
  list.innerHTML = '';
  const none = document.createElement('div');
  none.className = 'opt';
  none.innerHTML = `<div class="thumb">∅</div><div class="meta"><div class="oname">不装配 / 移除</div>
                    <div class="ofrom">清空该槽位</div></div>`;
  none.onclick = () => setAccessory(slot, '');
  list.appendChild(none);
  let shown = 0;
  for (const o of options) {
    if (q && !(o.name.toLowerCase().includes(q) || o.path.toLowerCase().includes(q)
               || (o.from_truck || '').toLowerCase().includes(q))) continue;
    if (shown++ > 400) break;
    const d = document.createElement('div');
    d.className = 'opt' + (state.config.accessories[slot] === o.path ? ' current' : '');
    const iconUrl = o.icon ? '/api/icon?icon=' + encodeURIComponent(o.icon) + '&size=128' : '';
    d.innerHTML = `
      <div class="thumb">${iconUrl ? `<img loading="lazy" src="${iconUrl}" onerror="this.remove()">` : '—'}</div>
      <div class="meta">
        <div class="oname">${o.name}</div>
        <div class="ofrom">来自 ${o.from_truck || '?'}</div>
        <div class="oprice">${o.part_type === 'factory' ? '原厂' : o.part_type === 'aftermarket' ? '改装' : ''} ${o.price ? o.price.toLocaleString() + ' €' : ''}</div>
      </div>`;
    d.onclick = () => setAccessory(slot, o.path);
    list.appendChild(d);
  }
}

function setAccessory(slot, path) {
  const previous = state.config.accessories[slot];
  if (path) state.config.accessories[slot] = path;
  else delete state.config.accessories[slot];
  if (previous !== path) delete state.edits[slot];
  el('picker').classList.add('hidden');
  renderSlots();
  refreshModel().then(() => { if (path) selectSlot(slot); });
}

/* ------------------------------------------------------------ coord table */
function worldTransform(outer) {
  truckRoot.updateMatrixWorld(true);
  const pos = new THREE.Vector3().setFromMatrixPosition(outer.matrixWorld);
  const quat = new THREE.Quaternion().setFromRotationMatrix(outer.matrixWorld);
  const scl = new THREE.Vector3().setFromMatrixScale(outer.matrixWorld);
  const e = new THREE.Euler().setFromQuaternion(quat, 'XYZ');
  return { pos, euler: [deg(e.x), deg(e.y), deg(e.z)], scale: scl.x };
}

function renderCoordTable() {
  const tbody = el('coordTable').querySelector('tbody');
  tbody.innerHTML = '';
  const rows = [];
  for (const inst of state.instances) {
    const slot = inst.slot;
    const opt = (state.autoAccessories[slot] || []).find((o) => o.path === inst.def);
    const g = state.groups[slot];
    const base = state.bases[slot];
    const e = state.edits[slot] || identityEdit();
    const w = g ? worldTransform(g) : null;
    rows.push({
      key: slot,
      editable: inst.kind === 'accessory',
      slot: PART_LABELS[inst.kind] || slot,
      name: (opt && opt.name) || (inst.source || inst.model),
      from: (opt && opt.from_truck) || state.current?.id || '',
      locator: inst.locator || '—',
      base: base ? base.position : [0, 0, 0],
      offset: e.pos.slice(),
      final: w ? [w.pos.x, w.pos.y, w.pos.z] : [0, 0, 0],
      rot: w ? w.euler : [0, 0, 0],
      scale: w ? w.scale : 1,
      moved: hasEdit(slot),
      missing: !inst.locator && inst.kind === 'accessory',
    });
  }
  state.coordRows = rows;
  for (const r of rows) {
    const tr = document.createElement('tr');
    if (r.missing) tr.className = 'missing';
    if (r.key === state.selectedKey) tr.className += ' sel';
    if (!r.editable) tr.className += ' locked';
    const hl = r.moved ? 'hl' : '';
    tr.innerHTML = `
      <td>${r.moved ? '● ' : ''}${r.slot}</td><td>${r.name}</td><td>${r.from}</td><td>${r.locator}</td>
      <td class="num">${fmt(r.base[0])}</td><td class="num">${fmt(r.base[1])}</td><td class="num">${fmt(r.base[2])}</td>
      <td class="num ${hl}">${fmt(r.offset[0])}</td><td class="num ${hl}">${fmt(r.offset[1])}</td><td class="num ${hl}">${fmt(r.offset[2])}</td>
      <td class="num ${hl}">${fmt(r.final[0])}</td><td class="num ${hl}">${fmt(r.final[1])}</td><td class="num ${hl}">${fmt(r.final[2])}</td>
      <td class="num">${r.rot.map((v) => fmt(v, 1)).join(', ')}</td>
      <td class="num">${fmt(r.scale, 3)}</td>`;
    tr.onclick = () => { if (r.editable) selectSlot(r.key); };
    tbody.appendChild(tr);
  }
  if (!rows.length) {
    tbody.innerHTML = '<tr><td colspan="15" class="muted">尚未装配任何部件</td></tr>';
  }
}

function exportRows() {
  const rows = state.coordRows || [];
  const header = ['vehicle', 'category', 'slot', 'accessory', 'from_truck', 'locator',
                  'locator_x', 'locator_y', 'locator_z',
                  'offset_x', 'offset_y', 'offset_z',
                  'final_x', 'final_y', 'final_z',
                  'rot_x_deg', 'rot_y_deg', 'rot_z_deg', 'scale'];
  const out = [header.join(',')];
  for (const r of rows) {
    out.push([state.current?.id || '', state.current?.category || '', r.slot,
      JSON.stringify(r.name), r.from, r.locator,
      ...r.base.map((v) => v.toFixed(5)),
      ...r.offset.map((v) => v.toFixed(5)),
      ...r.final.map((v) => v.toFixed(5)),
      ...r.rot.map((v) => v.toFixed(3)), r.scale.toFixed(4)].join(','));
  }
  return out.join('\n');
}

function download(name, text) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }));
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 2000);
}

/* ---------------------------------------------------------------- vehicle */
async function selectVehicle(cat, id) {
  state.category = cat;
  const d = await apiJson(`/api/vehicle?category=${cat}&id=${encodeURIComponent(id)}`);
  state.current = d;
  state.autoAccessories = {};
  state.edits = {};
  state.selectedKey = null;
  state.__fitted = false;
  gizmo.detach();
  applyFactoryConfig();
  renderSummary();
  renderSlots();
  await refreshModel();
}

/** Pick the part the factory would fit in a slot (legal for the chosen cabin). */
function unitOfPrimary(key) {
  const d = state.current;
  if (!d) return '';
  const pr = (d.primaries || []).find((p) => p.key === key);
  if (!pr) return '';
  const o = pr.options.find((x) => x.path === state.config.parts[key]);
  return o ? o.unit : '';
}

function optionFits(o) {
  const sf = o.suitable_for || [];
  if (!sf.length) return true;
  const cab = unitOfPrimary('cabin') || unitOfPrimary('body');
  const chs = unitOfPrimary('chassis');
  if (!cab && !chs) return true;
  return sf.some((u) => u === cab || u === chs);
}

function stockRank(o) {
  let r = 0;
  if (o.part_type !== 'factory') r += 2;
  if (o.unlock) r += 1;
  if (/(^|\/)(stock|standard|default|empty|covered|nrm_)/i.test(o.path)) r -= 1;
  return r;
}

function stockOption(slot) {
  const d = state.current;
  const s = (d?.slots || []).find((x) => x.slot === slot);
  if (!s || !s.options.length) return null;
  let cands = s.options.filter((o) => o.model && optionFits(o));
  if (!cands.length) cands = s.options.filter((o) => o.model);
  if (!cands.length) return null;
  return cands.slice().sort((a, b) =>
    stockRank(a) - stockRank(b) || (a.price || 0) - (b.price || 0)
    || (a.name || '').localeCompare(b.name || ''))[0];
}

/**
 * The part the factory actually fits in a slot.
 *
 * `part_type: "factory"` cleanly separates structural parts (mirrors, visors,
 * trailer bodies -- stock on every truck) from optional tuning
 * (beacons, toys, flags, Thor grilles -- all `aftermarket`/`licensed`), which a
 * brand-new vehicle does not have.
 */
function factoryOption(slot) {
  const s = (state.current?.slots || []).find((x) => x.slot === slot);
  if (!s) return null;
  let cands = s.options.filter((o) => o.model && o.part_type === 'factory' && optionFits(o));
  if (!cands.length) cands = s.options.filter((o) => o.model && o.part_type === 'factory');
  if (!cands.length) return null;
  return cands.slice().sort((a, b) =>
    (a.unlock || 0) - (b.unlock || 0) || (a.price || 0) - (b.price || 0)
    || (a.name || '').localeCompare(b.name || ''))[0];
}

const SLOT_ALIASES = {
  steering_w: 'swheel',
  f_rim: 'wheel_f', r_rim: 'wheel_r',
  f_tire: 'wheel_f', f_disc: 'wheel_f', f_hub: 'wheel_f', f_nuts: 'wheel_f',
  r_tire: 'wheel_r', r_disc: 'wheel_r', r_hub: 'wheel_r', r_nuts: 'wheel_r',
};

function slotHasLocator(slot) {
  const names = state.hostLocators;
  if (!names || !names.size) return false;
  const s = (state.current?.slots || []).find((x) => x.slot === slot);
  const probes = [slot];
  if (s && s.wheel_axis) probes.push(s.wheel_axis);
  if (SLOT_ALIASES[slot]) probes.push(SLOT_ALIASES[slot]);
  for (const p of probes) {
    if (names.has(p)) return true;
    for (const n of names) if (n.startsWith(p + '_')) return true;
  }
  return false;
}

/** Load the vehicle exactly as the manufacturer ships it (def defaults[]/fallback[]). */
function applyFactoryConfig() {
  const d = state.current;
  if (!d) return 0;
  state.config = { parts: {}, accessories: {}, paint_job: '' };
  state.edits = {};
  state.paintVariant = 0;
  state.paintColor = null;
  const explicit = d.factory || {};
  const pd = d.part_defaults || {};

  // 1. pick the primary parts (cabin/chassis or body/chassis)
  for (const pr of (d.primaries || [])) {
    if (!pr.options || !pr.options.length) continue;
    const pref = explicit[pr.key] && pr.options.some((o) => o.path === explicit[pr.key]);
    state.config.parts[pr.key] = pref ? explicit[pr.key] : pr.options[0].path;
  }
  if (!Object.keys(state.config.parts).length) {
    if (d.cabins.length) state.config.parts.cabin = d.cabins[0].path;
    if (d.chassis.length) state.config.parts.chassis = d.chassis[0].path;
  }

  // 2. merge defaults: the chosen cabin/chassis defaults[] win over the
  //    data.sii list, which wins over the "cheapest stock part" fallback
  const merged = Object.assign({}, d.factory_filled || {}, explicit);
  for (const key of ['cabin', 'body', 'chassis', 'interior']) {
    const p = state.config.parts[key];
    if (p && pd[p]) Object.assign(merged, pd[p]);
  }

  const bySlot = new Map(d.slots.map((s) => [s.slot, s]));
  let count = 0;

  // 2. the vehicle's own defaults[] / fallback[] first
  for (const [slot, path] of Object.entries(merged)) {
    if (state.config.parts[slot]) continue;
    if (slot === 'paint_job') { state.config.paint_job = path; continue; }
    const s = bySlot.get(slot);
    if (!s) continue;
    const opt = s.options.find((o) => o.path === path);
    if (!opt || !opt.model) continue;
    state.config.accessories[slot] = path;
    state.autoAccessories[slot] = s.options;
    count++;
  }
  // 3. slots this truck's model actually has attachment points for are filled
  //    after the first build (see refreshModel) so that every vehicle -- present
  //    or future -- comes out complete without hard-coded lists.
  if (!state.config.paint_job && (d.paint_jobs || []).length) {
    state.config.paint_job = (d.factory || {}).paint_job || d.paint_jobs[0].path;
  }
  if (state.config.paint_job && !(d.paint_jobs || []).some((o) => o.path === state.config.paint_job)) {
    d.paint_jobs = d.paint_jobs || [];
    d.paint_jobs.unshift({ path: state.config.paint_job, name: state.config.paint_job });
  }
  state.factoryCount = count;
  return count;
}

function renderSummary() {
  const d = state.current;
  const rows = (d.primaries || []).map((pr) => {
    if (!pr.options.length) return '';
    const cur = state.config.parts[pr.key] || '';
    const opts = pr.options.map((o) =>
      `<option value="${o.path}" ${o.path === cur ? 'selected' : ''}>${o.name}</option>`).join('');
    return `<div class="prow"><label>${pr.label}</label><select data-part="${pr.key}">${opts}</select></div>`;
  }).join('');

  // paint jobs are filtered by the selected cabin, like the in-game shop does
  const cabPr = (d.primaries || []).find((p) => p.key === 'cabin');
  const cabOpt = cabPr && cabPr.options.find((o) => o.path === state.config.parts.cabin);
  const cabUnit = cabOpt ? cabOpt.unit : '';
  let pjs = (d.paint_jobs || []).filter((o) =>
    !o.suitable_for || !o.suitable_for.length || !cabUnit || o.suitable_for.includes(cabUnit));
  if (!pjs.length) pjs = (d.paint_jobs || []).slice();
  const curPj = state.config.paint_job || '';
  // the factory paint job first, then plain colours, then patterned liveries
  pjs = pjs.slice().sort((a, b) => {
    const rank = (p) => (p.path === curPj ? 0 : (!p.mask ? 1 : 2));
    return rank(a) - rank(b)
      || (a.price || 0) - (b.price || 0)
      || (a.name || '').localeCompare(b.name || '');
  });
  const pjOpts = pjs.map((o) =>
    `<option value="${o.path}" ${o.path === curPj ? 'selected' : ''}>${o.mask ? '◆ ' : '● '}${o.name}</option>`).join('');
  const nLivery = pjs.filter((o) => o.mask).length;
  const pjRow = pjs.length
    ? `<div class="prow"><label>涂装</label><select data-paint="1" id="paintSelect">${pjOpts}</select></div>
       <div class="sub" style="margin-top:4px">共 ${pjs.length} 种涂装（● 实色 ${pjs.length - nLivery} / ◆ 花纹 ${nLivery}）
       ${state.config.paint_job ? '' : '· 未选中'}</div>`
    : '';

  const pj = pjs.find((o) => o.path === curPj);
  const nvar = pj ? Math.floor((pj.variants || []).length / 4) : 0;
  const varRow = nvar > 1
    ? `<div class="prow"><label>配色</label><select id="variantSelect">${
        Array.from({ length: nvar }, (_, i) =>
          `<option value="${i}" ${i === (state.paintVariant || 0) ? 'selected' : ''}>配色 ${i + 1}</option>`).join('')
      }</select></div>`
    : '';
  const livery = pj && pj.mask ? `<span class="tag-livery">花纹涂装</span>` : '';
  const customColour = pj && pj.base_color_locked === false && !pj.mask;
  const hex = state.paintColor
    ? '#' + state.paintColor.map((v) => Math.round(v * 255).toString(16).padStart(2, '0')).join('')
    : (pj && pj.base_color ? '#' + pj.base_color.slice(0, 3)
        .map((v) => Math.round(v * 255).toString(16).padStart(2, '0')).join('') : '#ffffff');
  const colorRow = customColour
    ? `<div class="prow"><label>车漆</label><input type="color" id="paintColor" value="${hex}">
         <button id="paintColorReset" class="ghost small">默认</button></div>`
    : '';

  el('truckSummary').innerHTML =
    `<div class="title">${d.name}</div>
     <div class="sub">${d.id} · ${d.slots.length} 个槽位 · 已载入原厂配件 ${state.factoryCount || 0} 项 ${livery}</div>
     <div class="prow-main"><button id="loadFactory" class="ghost small">重新载入原厂配置</button>
       <button id="clearAll" class="ghost small">清空全部配件</button></div>${rows}${pjRow}${colorRow}${varRow}`;

  const lf = el('loadFactory');
  if (lf) lf.onclick = () => {
    applyFactoryConfig();
    renderSummary();
    renderSlots();
    refreshModel().then(() => toast(`已载入原厂配置：${state.factoryCount} 项配件`));
  };
  const ca = el('clearAll');
  if (ca) ca.onclick = () => {
    state.config.accessories = {};
    state.edits = {};
    renderSummary();
    renderSlots();
    refreshModel().then(() => toast('已清空全部配件'));
  };
  const ps = el('paintSelect');
  if (ps) ps.onchange = () => {
    state.config.paint_job = ps.value;
    state.paintVariant = 0;
    state.paintColor = null;
    const p = pjs.find((o) => o.path === ps.value);
    renderSummary();
    refreshModel().then(() => toast(
      `涂装：${p ? p.name : '?'}${p && p.mask ? '（花纹涂装）' : '（实色）'}`));
  };
  const vs = el('variantSelect');
  if (vs) vs.onchange = () => {
    state.paintVariant = parseInt(vs.value, 10) || 0;
    refreshModel();
  };
  const pc = el('paintColor');
  if (pc) {
    pc.oninput = () => {
      const h = pc.value.replace('#', '');
      state.paintColor = [0, 2, 4].map((i) => parseInt(h.substr(i, 2), 16) / 255);
      clearTimeout(state.__paintTimer);
      state.__paintTimer = setTimeout(() => refreshModel(), 220);
    };
  }
  const pcr = el('paintColorReset');
  if (pcr) pcr.onclick = () => {
    state.paintColor = null;
    renderSummary();
    refreshModel();
  };
  el('truckSummary').querySelectorAll('select[data-part]').forEach((sel) => {
    sel.onchange = () => {
      state.config.parts[sel.dataset.part] = sel.value;
      state.edits = {};
      state.__fitted = false;
      // switching cabin/chassis brings its own factory defaults
      applyFactoryConfig();
      renderSummary();
      renderSlots();
      refreshModel();
    };
  });
}

function renderVehicles() {
  const host = el('vehList');
  host.innerHTML = '';
  const q = el('vehSearch').value.trim().toLowerCase();
  for (const v of state.vehicles) {
    if (v.category !== state.category) continue;
    if (q && !(v.name.toLowerCase().includes(q) || v.id.toLowerCase().includes(q))) continue;
    const d = document.createElement('div');
    d.className = 'veh-item ' + v.category
      + (state.current && state.current.id === v.id ? ' active' : '');
    d.innerHTML = `<span class="dot"></span>
      <span class="vname">${v.name}</span>
      <span class="vid">${v.id}</span>`;
    d.onclick = () => { selectVehicle(v.category, v.id).catch((e) => console.warn(e)); };
    host.appendChild(d);
  }
}

/* -------------------------------------------------------------- animation */
function animate() {
  requestAnimationFrame(animate);
  resize();                       // keeps the aspect correct after any relayout
  controls.update();
  renderer.render(scene, camera);
}
animate();

/* ----------------------------------------------------------- interaction */
const pointer = new THREE.Vector2();
let downPos = null;

canvas.addEventListener('pointerdown', (e) => {
  downPos = { x: e.clientX, y: e.clientY };
});

canvas.addEventListener('pointerup', (e) => {
  if (!downPos) return;
  const moved = Math.hypot(e.clientX - downPos.x, e.clientY - downPos.y);
  downPos = null;
  if (moved > 5 || gizmo.dragging) return;
  const r = canvas.getBoundingClientRect();
  pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
  pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
  ray.setFromCamera(pointer, camera);
  const hits = ray.intersectObjects(truckRoot.children, true);
  if (!hits.length) { clearSelection(); return; }
  let o = hits[0].object;
  while (o && !o.userData.slot) o = o.parent;
  if (!o || !o.userData.slot) return;
  if (!isEditable(o.userData.slot)) return;      // cabin/chassis shell is fixed
  selectSlot(o.userData.slot);
});

let hoverTimer = 0;
canvas.addEventListener('pointermove', (e) => {
  const r = canvas.getBoundingClientRect();
  pointer.x = ((e.clientX - r.left) / r.width) * 2 - 1;
  pointer.y = -((e.clientY - r.top) / r.height) * 2 + 1;
  const now = performance.now();
  if (now - hoverTimer < 90) return;
  hoverTimer = now;
  ray.setFromCamera(pointer, camera);
  const hud = el('locatorHud');
  const hits = ray.intersectObjects(locatorRoot.children, false);
  if (hits.length) {
    const l = hits[0].object.userData.locator;
    hud.innerHTML = `<b>${l.name}</b><br>X ${fmt(l.position[0])}<br>`
      + `Y ${fmt(l.position[1])}<br>Z ${fmt(l.position[2])}`
      + (l.hookup ? `<br>hookup ${l.hookup}` : '');
    hud.classList.remove('hidden');
  } else {
    hud.classList.add('hidden');
  }
});

window.addEventListener('keydown', (e) => {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;
  const k = e.key.toLowerCase();
  if (k === 'w') { setGizmoMode('translate'); e.preventDefault(); }
  else if (k === 'e') { setGizmoMode('rotate'); e.preventDefault(); }
  else if (k === 'r') { setGizmoMode('scale'); e.preventDefault(); }
  else if (k === 'escape') { clearSelection(); el('picker').classList.add('hidden'); }
});

/* ------------------------------------------------------------------- boot */
// Tell the desktop launcher this page is still open; when the beats stop it
// shuts the local server down (an `--app` window may belong to a browser
// process we did not start ourselves).
setInterval(() => {
  fetch('/api/ping').then(() => { serverLost = false; }).catch(() => markServerLost());
}, 5000);
document.addEventListener('visibilitychange', () => {
  fetch('/api/ping').catch(() => {});
});

async function pollStatus() {
  const s = await apiJson('/api/status');
  if (s.status === 'scanning') {
    el('bootProgress').classList.remove('hidden');
    el('bootProgress').querySelector('span').textContent = s.progress;
    setTimeout(pollStatus, 350);
  } else if (s.status === 'ready') {
    el('bootProgress').classList.add('hidden');
    startApp(s);
  } else if (s.status === 'error') {
    el('bootProgress').classList.add('hidden');
    el('bootError').classList.remove('hidden');
    el('bootError').textContent = s.error;
  } else {
    const c = s.candidates || [];
    const host = el('candidates');
    host.innerHTML = '';
    for (const p of c) {
      const b = document.createElement('button');
      b.textContent = '✓ ' + p;
      b.onclick = () => { el('gamePath').value = p; };
      host.appendChild(b);
    }
    if (c.length && !el('gamePath').value) el('gamePath').value = c[0];
  }
}

async function startApp(s) {
  el('boot').classList.add('hidden');
  el('app').classList.remove('hidden');
  el('statFiles').textContent = `归档 ${s.stats.archives} · 文件 ${(s.stats.files / 1000).toFixed(0)}k`;
  el('statVehicles').textContent = `卡车 ${s.stats.trucks} · 挂车 ${s.stats.trailers}`;
  el('statMods').textContent = s.stats.mods ? `mod ${s.stats.mods}` : '无 mod';
  requestAnimationFrame(() => { resize(); });
  state.vehicles = (await apiJson('/api/vehicles')).vehicles;
  renderVehicles();
  const first = state.vehicles.find((v) => v.category === 'truck');
  if (first) selectVehicle(first.category, first.id);
}

el('scanBtn').onclick = async () => {
  const path = el('gamePath').value.trim();
  if (!path) return;
  el('scanBtn').disabled = true;
  await apiJson('/api/scan', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ path, mod_dir: el('modPath').value.trim() }),
  });
  pollStatus();
};
el('browseBtn').onclick = async () => {
  if (window.pywebview && window.pywebview.api) {
    const p = await window.pywebview.api.pick_directory();
    if (p) el('gamePath').value = p;
  } else {
    const p = window.prompt('请粘贴游戏安装目录（含 base.scs 的文件夹）：', el('gamePath').value || '');
    if (p) el('gamePath').value = p.trim();
  }
};
el('reScan').onclick = () => {
  el('app').classList.add('hidden');
  el('boot').classList.remove('hidden');
  el('scanBtn').disabled = false;
  pollStatus();
};
el('vehSearch').oninput = renderVehicles;
el('slotSearch').oninput = renderSlots;
document.querySelectorAll('.tab').forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
    b.classList.add('active');
    state.category = b.dataset.cat;
    renderVehicles();
  };
});
el('pickerClose').onclick = () => el('picker').classList.add('hidden');
el('pickerSearch').oninput = () => {
  const slot = state.selectedSlot;
  drawPicker(state.autoAccessories[slot] || [], slot);
};
el('showLocators').onchange = () => { locatorRoot.visible = el('showLocators').checked; };
el('showGrid').onchange = () => { grid.visible = el('showGrid').checked; };
el('showWire').onchange = () => {
  truckRoot.traverse((o) => { if (o.isMesh && o.material) o.material.wireframe = el('showWire').checked; });
};
el('resetView').onclick = () => {
  const box = new THREE.Box3().setFromObject(truckRoot);
  if (!box.isEmpty()) fitCamera(box);
};
el('exportCsv').onclick = () => download(`ets2_${state.current?.id || 'vehicle'}_coords.csv`, exportRows());
el('exportJson').onclick = () => download(`ets2_${state.current?.id || 'vehicle'}_config.json`,
  JSON.stringify({
    vehicle: state.current?.id, category: state.current?.category,
    parts: state.config.parts,
    accessories: state.config.accessories,
    coordinates: state.coordRows,
  }, null, 2));
el('copyAll').onclick = async () => {
  try { await navigator.clipboard.writeText(exportRows()); el('copyAll').textContent = '已复制'; }
  catch (e) { el('copyAll').textContent = '复制失败'; }
  setTimeout(() => { el('copyAll').textContent = '复制全部'; }, 1600);
};

pollStatus();

// diagnostics hook (used by the automated UI check)
window.__ets2 = {
  state, truckRoot, locatorRoot, scene, camera, controls, gizmo, THREE, renderer,
  snapshot: () => { renderer.render(scene, camera); return renderer.domElement.toDataURL('image/png'); },
  selectSlot, clearSelection, setGizmoMode, bump, getEdit, applyEditToGroup,
  renderCoordTable, worldTransform, refreshModel, applyFactoryConfig, renderSummary,
  slotHasLocator, stockOption,
};