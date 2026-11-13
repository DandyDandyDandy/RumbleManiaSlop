"""make_hand_poser.py - writes hand_poser.html (next to this file), a one-file tool for posing the classic monkeys' hands.

The page shows each classic character's left hand and forearm in 3D with sliders for the wrist and for every
finger joint (curl, spread, twist). "Save" downloads classic_hands.json; put that file into this folder and
run the import again (setup.cmd --only mania): classic_chara.py reads the pose
from it (the right hand mirrors the left). The pose arithmetic in the page (poseMatrices) is the same as
classic_chara.finger_pose.
"""
import os, sys, json
import numpy as np
import UnityPy
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import classic_chara as cc

if cc.AA is None:
    cc.configure_from_env()

def export(name):
    cfg = cc.config(name)
    classic, root = cc.load_classic(cfg, posed=False)
    cm = classic['body']
    wrist, chains = cc.finger_chains(root, 'l')
    bone_names = ['te_l'] + [n.name for f in cc.FINGERS_ORDER if f in chains for n in chains[f]]   # the doctor has no finger bones
    index = {n: i + 1 for i, n in enumerate(bone_names)}       # 0 = everything else (does not move)
    hand_nodes = {d.name for d in wrist.walk()}
    near = {'ude_l'} | hand_nodes
    nv = len(cm['pos'])
    used = np.zeros(nv, dtype=bool)
    vb = np.zeros((nv, 4), dtype=int); vw = np.zeros((nv, 4))
    for k in range(4):
        for i in range(nv):
            b = cm['bones'][cm['bi'][i, k]].name
            w = cm['w'][i, k]
            if w <= 0: continue
            if b in near: used[i] = True
            # a bone below a finger joint that is not itself posed follows the nearest posed ancestor
            node = cm['bones'][cm['bi'][i, k]]
            while node is not None and node.name not in index: node = node.parent if node.name in hand_nodes else None
            vb[i, k] = index[node.name] if node is not None else 0
            vw[i, k] = w
    remap = -np.ones(nv, dtype=int); remap[used] = np.arange(used.sum())
    tris, cols = [], np.zeros((nv, 3))
    for t, mat in zip(cm['tris'], cm['mats']):
        img = np.asarray(cc.classic_image(cfg, mat)[0])
        t3 = t.reshape(-1, 3)
        keep = used[t3].all(1)
        tris += remap[t3[keep]].reshape(-1).tolist()
        vs = np.unique(t3[keep])
        uv = cm['uv'][vs]
        px = img[np.clip(((1 - uv[:, 1] % 1.0) * img.shape[0]).astype(int), 0, img.shape[0] - 1), np.clip(((uv[:, 0] % 1.0) * img.shape[1]).astype(int), 0, img.shape[1] - 1), :3]
        cols[vs] = px / 255.0
    r = lambda a: [round(float(x), 5) for x in np.asarray(a).reshape(-1)]
    return dict(pos=r(cm['pos'][used]), col=r(cols[used]), tris=tris, vb=vb[used].reshape(-1).tolist(), vw=r(vw[used]),
                wrist=r(wrist.W[:3, 3]), chains={f: [r(n.W[:3, 3]) for n in chains[f]] for f in cc.FINGERS_ORDER if f in chains},
                default=cc.default_hand_spec(name), start=cc.hand_spec(name))

PAGE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Classic hand poser</title>
<style>
  :root { color-scheme: dark; }
  body { margin: 0; font: 13px/1.35 system-ui, sans-serif; background: #1d2026; color: #e6e6e6; display: flex; height: 100vh; }
  #side { width: 400px; overflow-y: auto; padding: 12px 14px; box-sizing: border-box; border-right: 1px solid #333842; }
  #view { flex: 1; position: relative; }
  canvas { display: block; }
  h1 { font-size: 16px; margin: 0 0 8px; }
  h2 { font-size: 13px; margin: 14px 0 4px; color: #ffcf6b; }
  .row { display: grid; grid-template-columns: 62px 1fr 38px; gap: 6px; align-items: center; }
  .row input[type=range] { width: 100%; }
  .row span:last-child { text-align: right; font-variant-numeric: tabular-nums; color: #b9c0cc; }
  .joint { margin: 2px 0 6px; padding-left: 8px; border-left: 2px solid #333842; }
  .joint b { font-weight: 600; color: #9fb4d4; font-size: 12px; }
  button, select { font: inherit; background: #2c313b; color: #e6e6e6; border: 1px solid #454c59; border-radius: 4px; padding: 5px 9px; cursor: pointer; }
  button:hover { background: #394050; }
  .bar { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
  #hint { position: absolute; left: 12px; bottom: 10px; color: #8d95a3; pointer-events: none; }
  p { margin: 6px 0; color: #b9c0cc; }
  code { background: #2c313b; padding: 1px 4px; border-radius: 3px; }
</style></head><body>
<div id="side">
  <h1>Classic hand poser</h1>
  <p>Pose the left hand; the right hand mirrors it. When you like it, press <b>Save</b>, move the downloaded
  <code>classic_hands.json</code> into <code>mania\classic\</code> of the repository, and ask for a rebuild.</p>
  <div class="bar">
    <select id="who"></select>
    <button id="relaxed">Relaxed</button><button id="fist">Fist</button><button id="flat">Flat</button><button id="reset">Reset</button>
  </div>
  <div class="bar"><button id="copyall">Copy this pose to all five</button><button id="save">Save classic_hands.json</button></div>
  <div id="controls"></div>
</div>
<div id="view"><div id="hint">drag: rotate &nbsp;·&nbsp; right-drag: pan &nbsp;·&nbsp; wheel: zoom</div></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
<script>
const DATA = __DATA__;
const FINGERS = [['oya', 'Thumb'], ['hit', 'Index'], ['nak', 'Middle'], ['kus', 'Ring'], ['koy', 'Little']];
const PRESET = {
  relaxed: {hit: [30, 45, 35], nak: [35, 50, 35], kus: [40, 50, 35], koy: [45, 50, 35], oya: [30, 25, 20]},
  fist: {hit: [85, 95, 75], nak: [85, 95, 75], kus: [85, 95, 75], koy: [85, 95, 75], oya: [45, 60, 45]},
  flat: {hit: [0, 0, 0], nak: [0, 0, 0], kus: [0, 0, 0], koy: [0, 0, 0], oya: [0, 0, 0]}};
const clone = o => JSON.parse(JSON.stringify(o));
const poses = {};
for (const k in DATA) poses[k] = clone(DATA[k].start);
let who = Object.keys(DATA)[0];

// ---- 4x4 matrices, row-major, column vectors (the same arithmetic as classic_chara.finger_pose)
const I4 = () => [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1];
function mul(a, b) { const r = new Array(16).fill(0);
  for (let i = 0; i < 4; i++) for (let j = 0; j < 4; j++) { let s = 0; for (let k = 0; k < 4; k++) s += a[4*i+k] * b[4*k+j]; r[4*i+j] = s; } return r; }
function rot(axis, deg, p) {
  const a = deg * Math.PI / 180, c = Math.cos(a), s = Math.sin(a), [x, y, z] = axis, t = 1 - c;
  const R = [t*x*x + c, t*x*y - s*z, t*x*z + s*y, 0,  t*x*y + s*z, t*y*y + c, t*y*z - s*x, 0,  t*x*z - s*y, t*y*z + s*x, t*z*z + c, 0,  0,0,0,1];
  const T = I4(); T[3] = p[0]; T[7] = p[1]; T[11] = p[2];
  const Ti = I4(); Ti[3] = -p[0]; Ti[7] = -p[1]; Ti[11] = -p[2];
  return mul(mul(T, R), Ti); }
const norm = v => { const l = Math.hypot(...v) || 1; return v.map(x => x / l); };
const cross = (a, b) => [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]];
function poseMatrices(d, spec) {          // -> matrices for bone 0 (static), the wrist and each finger joint
  const M = [I4()], wp = d.wrist, [wx, wy, wz] = spec.wrist;
  const H = mul(mul(rot([0,0,1], wz, wp), rot([0,1,0], wy, wp)), rot([1,0,0], wx, wp));
  M.push(H);
  for (const [f] of FINGERS) {
    const ch = d.chains[f];
    if (!ch) continue;
    let dir = ch.length > 1 ? [ch[1][0] - ch[0][0], 0, ch[1][2] - ch[0][2]] : [1, 0, 0];
    dir = norm(dir);
    const curlAxis = norm(cross(dir, [0, -1, 0]));
    let C = H;
    for (let k = 0; k < ch.length; k++) {
      const [curl, spread, twist] = spec.fingers[f][k];
      C = mul(mul(mul(C, rot([0,1,0], -spread, ch[k])), rot(curlAxis, curl, ch[k])), rot(dir, twist, ch[k]));
      M.push(C);
    }
  }
  return M; }

// ---- scene
const view = document.getElementById('view');
const renderer = new THREE.WebGLRenderer({antialias: true});
view.appendChild(renderer.domElement);
const scene = new THREE.Scene(); scene.background = new THREE.Color(0x2a2f38);
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 10);
const controls = new THREE.OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x556070, 0.95));
const sun = new THREE.DirectionalLight(0xffffff, 0.55); sun.position.set(0.4, 1, -0.8); scene.add(sun);
let mesh = null;
function build() {
  const d = DATA[who];
  if (mesh) { scene.remove(mesh); mesh.geometry.dispose(); }
  const g = new THREE.BufferGeometry();
  g.setAttribute('position', new THREE.BufferAttribute(new Float32Array(d.pos.length), 3));
  g.setAttribute('color', new THREE.BufferAttribute(new Float32Array(d.col), 3));
  g.setIndex(d.tris);
  mesh = new THREE.Mesh(g, new THREE.MeshLambertMaterial({vertexColors: true, side: THREE.DoubleSide}));
  scene.add(mesh);
  const c = d.chains.nak ? d.chains.nak[0] : [d.wrist[0] + 0.06, d.wrist[1], d.wrist[2]];
  controls.target.set((d.wrist[0] + c[0]) / 2 + 0.02, d.wrist[1] - 0.01, d.wrist[2]);
  const span = Math.max(0.12, Math.abs(c[0] - d.wrist[0]) * 3.2);
  camera.position.set(controls.target.x + span * 0.5, controls.target.y + span * 0.9, controls.target.z - span * 1.7);
  controls.update();
  update(); }
function update() {
  const d = DATA[who], M = poseMatrices(d, poses[who]), out = mesh.geometry.attributes.position.array, n = d.pos.length / 3;
  for (let i = 0; i < n; i++) {
    const x = d.pos[3*i], y = d.pos[3*i+1], z = d.pos[3*i+2]; let ox = 0, oy = 0, oz = 0, wsum = 0;
    for (let k = 0; k < 4; k++) { const w = d.vw[4*i+k]; if (w <= 0) continue; const m = M[d.vb[4*i+k]];
      ox += w * (m[0]*x + m[1]*y + m[2]*z + m[3]); oy += w * (m[4]*x + m[5]*y + m[6]*z + m[7]); oz += w * (m[8]*x + m[9]*y + m[10]*z + m[11]); wsum += w; }
    out[3*i] = ox / wsum; out[3*i+1] = oy / wsum; out[3*i+2] = oz / wsum; }
  mesh.geometry.attributes.position.needsUpdate = true;
  mesh.geometry.computeVertexNormals(); }

// ---- controls
const box = document.getElementById('controls');
function slider(label, min, max, get, set) {
  const row = document.createElement('div'); row.className = 'row';
  const name = document.createElement('span'); name.textContent = label;
  const inp = document.createElement('input'); inp.type = 'range'; inp.min = min; inp.max = max; inp.step = 1; inp.value = get();
  const val = document.createElement('span'); val.textContent = get();
  inp.addEventListener('input', () => { set(+inp.value); val.textContent = inp.value; update(); });
  row.append(name, inp, val); return row; }
function panel() {
  box.innerHTML = '';
  const p = poses[who];
  const h = document.createElement('h2'); h.textContent = 'Wrist'; box.append(h);
  ['roll (x)', 'swing (y)', 'bend (z)'].forEach((l, i) => box.append(slider(l, -90, 90, () => p.wrist[i], v => p.wrist[i] = v)));
  for (const [f, title] of FINGERS) {
    if (!DATA[who].chains[f]) continue;
    const h2 = document.createElement('h2'); h2.textContent = title; box.append(h2);
    for (let k = 0; k < 3; k++) {
      const j = document.createElement('div'); j.className = 'joint';
      const b = document.createElement('b'); b.textContent = ['base joint', 'middle joint', 'tip joint'][k]; j.append(b);
      j.append(slider('curl', -40, 140, () => p.fingers[f][k][0], v => p.fingers[f][k][0] = v));
      j.append(slider('spread', -60, 60, () => p.fingers[f][k][1], v => p.fingers[f][k][1] = v));
      j.append(slider('twist', -90, 90, () => p.fingers[f][k][2], v => p.fingers[f][k][2] = v));
      box.append(j); } } }
const sel = document.getElementById('who');
for (const k in DATA) { const o = document.createElement('option'); o.value = k; o.textContent = k[0].toUpperCase() + k.slice(1); sel.append(o); }
sel.addEventListener('change', () => { who = sel.value; panel(); build(); });
function preset(name) { const p = poses[who]; p.wrist = [0, 0, 0];
  for (const [f] of FINGERS) p.fingers[f] = PRESET[name][f].map(c => [c, 0, 0]); panel(); update(); }
document.getElementById('relaxed').onclick = () => preset('relaxed');
document.getElementById('fist').onclick = () => preset('fist');
document.getElementById('flat').onclick = () => preset('flat');
document.getElementById('reset').onclick = () => { poses[who] = clone(DATA[who].start); panel(); update(); };
document.getElementById('copyall').onclick = () => { for (const k in DATA) if (k !== who) poses[k] = clone(poses[who]); };
document.getElementById('save').onclick = () => {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(new Blob([JSON.stringify(poses, null, 1)], {type: 'application/json'}));
  a.download = 'classic_hands.json'; a.click(); URL.revokeObjectURL(a.href); };
function resize() { const w = view.clientWidth, h = view.clientHeight; renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }
window.addEventListener('resize', resize);
resize(); panel(); build();
(function loop() { requestAnimationFrame(loop); controls.update(); renderer.render(scene, camera); })();
</script></body></html>
'''

if __name__ == '__main__':
    data = {name: export(name) for name in cc.CHARS if name != 'doctor'}   # the doctor's hands are fine as they are (and have no finger bones)
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'hand_poser.html')
    open(out, 'w', encoding='utf-8').write(PAGE.replace('__DATA__', json.dumps(data, separators=(',', ':'))))
    print('wrote', out, os.path.getsize(out) // 1024, 'KB;', {k: len(v['pos']) // 3 for k, v in data.items()}, 'vertices')
