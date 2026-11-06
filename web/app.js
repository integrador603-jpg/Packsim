/* Packsim · interfaz web. Todo el cálculo lo hace la API; acá solo se dibuja. */
'use strict';
const $ = id => document.getElementById(id);
const fmt = (v, d = 0) => (+v).toLocaleString('es-AR', { minimumFractionDigits: d, maximumFractionDigits: d });
const kgTxt = kg => kg < 1 ? fmt(kg * 1000, 1) + ' g' : fmt(kg, kg < 10 ? 2 : 1) + ' kg';
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const dormir = ms => new Promise(r => setTimeout(r, ms));

// ═══════════════ API ═══════════════
class ErrorSesion extends Error {}
async function api(ruta, opts = {}) {
  const r = await fetch(ruta, { credentials: 'same-origin', ...opts });
  if (r.status === 401 && !ruta.startsWith('/v1/sesion')) { mostrarLogin(); throw new ErrorSesion('Tu sesión venció. Volvé a ingresar.'); }
  const json = (r.headers.get('content-type') || '').includes('json');
  const datos = json ? await r.json() : await r.arrayBuffer();
  if (!r.ok) throw new Error((json && datos.detalle) || `Error ${r.status}`);
  return datos;
}
async function trabajo(ruta, params, archivo, alAvanzar) {
  const fd = new FormData();
  fd.append('parametros', JSON.stringify(params));
  if (archivo) fd.append('archivo', archivo);
  const { id } = await api(ruta, { method: 'POST', body: fd });
  const fin = Date.now() + 8 * 60 * 1000;
  let espera = 250;
  while (Date.now() < fin) {
    await dormir(espera); espera = Math.min(1000, espera * 1.4);
    const t = await api('/v1/trabajos/' + id);
    if (t.texto && alAvanzar) alAvanzar(t.progreso, t.texto);
    if (t.estado === 'listo') return t;
    if (t.estado === 'error') throw new Error(t.error);
  }
  throw new Error('La simulación tardó demasiado. Probá de nuevo.');
}

// ═══════════════ ESTADO ═══════════════
const FIN = [['zinc', 'Zincado', 0xa9b3bd], ['amar', 'Bicromatado', 0xd4b24c], ['pav', 'Pavonado', 0x34383c], ['galv', 'Galvanizado', 0x9aa3a9],
  ['inox', 'Inoxidable', 0xc4cacf], ['bronce', 'Bronce', 0xb4813f], ['verde', 'Pintado verde', 0x2f7d4f]];
const ICON = {
  tornillo_hexagonal: '<path d="M6 3h10l-1.5 4h-7z" stroke-linejoin="round"/><path d="M9 7v13h4V7M9 10h4M9 13h4M9 16h4"/>',
  tornillo_allen: '<rect x="6" y="3" width="10" height="5" rx="1"/><path d="M9 8v12h4V8M9.5 11h3M9.5 14h3M9.5 17h3"/><path d="M10 5.5h2"/>',
  tuerca_hexagonal: '<polygon points="11,3 18,7 18,15 11,19 4,15 4,7"/><circle cx="11" cy="11" r="3.3"/>',
  tuerca_autofrenante: '<polygon points="11,5 17,8.5 17,14.5 11,18 5,14.5 5,8.5"/><path d="M7 5.5Q11 2 15 5.5"/><circle cx="11" cy="11.5" r="2.6"/>',
  arandela_plana: '<ellipse cx="11" cy="11" rx="8" ry="4.5"/><ellipse cx="11" cy="11" rx="3.4" ry="1.8"/>',
  arandela_grower: '<path d="M4.5 12a7 4 0 1 0 2.5-4.5"/><path d="M7 7.5l1.5 2.5"/><ellipse cx="11" cy="11.5" rx="3" ry="1.6"/>',
  varilla_roscada: '<path d="M5 17L17 5M7 19L19 7"/><path d="M8 14l2 2M10 12l2 2M12 10l2 2M14 8l2 2"/>',
  buje: '<ellipse cx="11" cy="6" rx="6.5" ry="2.4"/><ellipse cx="11" cy="6" rx="3" ry="1.1"/><path d="M4.5 6v10a6.5 2.4 0 0 0 13 0V6"/>',
  rodamiento: '<circle cx="11" cy="11" r="8"/><circle cx="11" cy="11" r="3.2"/><circle cx="11" cy="5.6" r="1.2"/><circle cx="16.4" cy="11" r="1.2"/><circle cx="11" cy="16.4" r="1.2"/><circle cx="5.6" cy="11" r="1.2"/>',
};
const BOX_ICON = {
  carton: '<path d="M3 8l10-4 10 4v11l-10 4-10-4z"/><path d="M3 8l10 4 10-4M13 12v11"/><path d="M3 8l-1.5-3.5L11 1M23 8l1.5-3.5L15 1"/>',
  madera: '<path d="M3 8l10-4 10 4v11l-10 4-10-4z"/><path d="M3 8l10 4 10-4M13 12v11M3 13.5l10 4 10-4"/><path d="M5 22.5v1.5M13 25.5V24M21 22.5v1.5"/>',
  plastico: '<path d="M3 8l10-4 10 4v11l-10 4-10-4z"/><path d="M3 8l10 4 10-4M13 12v11"/><path d="M6 13l4 1.6M16 14.6l4-1.6"/>',
};
const S = {
  cat: null, paso: 0, fuente: 'cat', famId: 'tornillo_hexagonal', famVals: {}, terminacion: 'zinc', colorLibre: '#3d6fb0',
  archivo: null, pieza: null, geo: null, avisos: [], boxIdx: 1, tipo: 'carton', taraOrigen: 'cat', manip: 'manual', prio: 'cantidad',
  res: null, vista: 'part', hechos: [false, false, false, false], pedido: 0, desactualizado: true, modo: 'ordenado', anim: null,
};

// ═══════════════ THREE ═══════════════
let renderer, scene, camera, grid, gPart, gPack, gFis;
const orbit = { th: 0.8, ph: 0.5, r: 300, t: null };
function iniciar3D() {
  const c3d = $('c3d');
  renderer = new THREE.WebGLRenderer({ canvas: c3d, antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  scene = new THREE.Scene(); scene.background = new THREE.Color(0xe4e8ec);
  camera = new THREE.PerspectiveCamera(38, 1, 1, 100000);
  scene.add(new THREE.HemisphereLight(0xf4f7fa, 0x5d6670, 0.5));
  const dl = new THREE.DirectionalLight(0xffffff, 0.85); dl.position.set(4, 7, 5); scene.add(dl);
  const dl2 = new THREE.DirectionalLight(0xc9d8e8, 0.3); dl2.position.set(-5, 3, -4); scene.add(dl2);
  grid = new THREE.GridHelper(2000, 40, 0xbac2ca, 0xd3d9df); scene.add(grid);
  gPart = new THREE.Group(); gPack = new THREE.Group(); gFis = new THREE.Group(); scene.add(gPart, gPack, gFis);
  orbit.t = new THREE.Vector3();
  let drag = 0, lx = 0, ly = 0;
  c3d.addEventListener('contextmenu', e => e.preventDefault());
  c3d.addEventListener('mousedown', e => { drag = e.button === 2 || e.shiftKey ? 2 : 1; lx = e.clientX; ly = e.clientY; });
  addEventListener('mouseup', () => drag = 0);
  addEventListener('mousemove', e => {
    if (!drag) return; const dx = e.clientX - lx, dy = e.clientY - ly; lx = e.clientX; ly = e.clientY;
    if (drag === 1) { orbit.th -= dx * 0.006; orbit.ph = Math.max(-0.15, Math.min(1.5, orbit.ph + dy * 0.006)); }
    else { const k = orbit.r * 0.0016, rt = new THREE.Vector3(Math.cos(orbit.th), 0, -Math.sin(orbit.th)); orbit.t.addScaledVector(rt, -dx * k); orbit.t.y += dy * k; }
  });
  c3d.addEventListener('wheel', e => { e.preventDefault(); orbit.r = Math.max(5, Math.min(60000, orbit.r * (e.deltaY > 0 ? 1.1 : 0.9))); }, { passive: false });
  addEventListener('resize', ajustar);
  ajustar();
  (function bucle() {
    requestAnimationFrame(bucle);
    const t = orbit.t;
    camera.position.set(t.x + orbit.r * Math.sin(orbit.th) * Math.cos(orbit.ph), t.y + orbit.r * Math.sin(orbit.ph), t.z + orbit.r * Math.cos(orbit.th) * Math.cos(orbit.ph));
    camera.lookAt(t); avanzarAnimacion(); renderer.render(scene, camera);
  })();
}
function ajustar() { const w = $('vp').clientWidth, h = $('vp').clientHeight; if (!w || !h) return; renderer.setSize(w, h, false); camera.aspect = w / h; camera.updateProjectionMatrix(); }
function encuadrar(size, centro) { orbit.r = (size.length() / 2 || 50) / Math.sin(camera.fov * Math.PI / 360) * 1.05; orbit.t.copy(centro); }
function limpiar(g) { while (g.children.length) { const c = g.children.pop(); c.traverse(o => { if (o.userData.own && o.geometry) o.geometry.dispose(); if (o.userData.own && o.material && o.material.map) o.material.map.dispose(); }); } }
// marco de la pieza y del embalaje (z arriba) → visor (y arriba): (x, y, z) → (x, z, −y)
const CP = new THREE.Matrix4().set(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1);
const matCache = new Map();
function metal(hex) {
  if (!matCache.has(hex)) {
    const c = new THREE.Color(hex), lum = c.r * 0.3 + c.g * 0.59 + c.b * 0.11;
    matCache.set(hex, new THREE.MeshPhongMaterial({ color: hex, shininess: lum > 0.5 ? 70 : 35, specular: new THREE.Color(lum > 0.5 ? 0x777777 : 0x333333) }));
  }
  return matCache.get(hex);
}
function colorPieza() { return S.terminacion === 'libre' ? parseInt(S.colorLibre.slice(1), 16) : FIN.find(f => f[0] === S.terminacion)[2]; }

function dibujarPieza() {
  limpiar(gPart);
  if (!S.geo || !S.pieza) { $('dimTag').innerHTML = ''; $('empty3d').hidden = false; return; }
  $('empty3d').hidden = true;
  const c = S.pieza.centro_envolvente_mm, e = S.pieza.envolvente_mm;
  const m = new THREE.Mesh(S.geo, metal(colorPieza()));
  m.matrixAutoUpdate = false;
  m.matrix.copy(new THREE.Matrix4().makeTranslation(0, e[2] / 2, 0).multiply(CP).multiply(new THREE.Matrix4().makeTranslation(-c[0], -c[1], -c[2])));
  gPart.add(m);
  const he = new THREE.Vector3(e[0] / 2, e[2] / 2, e[1] / 2);
  const bh = new THREE.Box3Helper(new THREE.Box3(new THREE.Vector3(-he.x, 0, -he.z), new THREE.Vector3(he.x, e[2], he.z)), 0x1f5f9e);
  bh.material.transparent = true; bh.material.opacity = 0.35; gPart.add(bh);
  grid.scale.setScalar(Math.max(0.05, Math.max(...e) / 400));
  $('dimTag').innerHTML = `Envolvente <b>${fmt(e[0], 1)} × ${fmt(e[1], 1)} × ${fmt(e[2], 1)}</b> mm`;
  if (S.vista === 'part') encuadrar(new THREE.Vector3(e[0], e[2], e[1]).multiplyScalar(1.7), new THREE.Vector3(0, e[2] / 2, 0));
}

// ── embalaje con texturas procedurales ──
const TEXC = {}, TILE = { carton: 250, madera: 400, plastico: 200 }, BORDE = { carton: 0x7d5a35, madera: 0x5e3f1e, plastico: 0x2c4a69 };
function textura(tipo) {
  if (TEXC[tipo]) return TEXC[tipo];
  const c = document.createElement('canvas'); c.width = c.height = 256; const g = c.getContext('2d');
  if (tipo === 'carton') {
    g.fillStyle = '#b8895a'; g.fillRect(0, 0, 256, 256);
    for (let x = 0; x < 256; x += 6) { g.fillStyle = x % 12 ? 'rgba(255,238,210,0.06)' : 'rgba(70,40,15,0.08)'; g.fillRect(x, 0, 3, 256); }
    for (let i = 0; i < 2600; i++) { const a = Math.random() * 0.11; g.fillStyle = Math.random() < 0.5 ? `rgba(80,48,18,${a})` : `rgba(255,236,205,${a})`; g.fillRect(Math.random() * 256, Math.random() * 256, 1 + Math.random() * 5, 1); }
  } else if (tipo === 'madera') {
    const cols = ['#c99d66', '#b98b56', '#d1a874', '#c29462'];
    for (let r = 0; r < 4; r++) {
      const y0 = r * 64; g.fillStyle = cols[r]; g.fillRect(0, y0, 256, 64);
      for (let k = 0; k < 10; k++) {
        g.strokeStyle = `rgba(95,58,22,${0.10 + Math.random() * 0.14})`; g.lineWidth = 0.8 + Math.random() * 1.4; g.beginPath();
        const yy = y0 + 4 + Math.random() * 56, ph = Math.random() * 6, am = 1 + Math.random() * 2.5;
        for (let x = 0; x <= 256; x += 8) { const y = yy + Math.sin(x / 38 + ph) * am; x ? g.lineTo(x, y) : g.moveTo(x, y); }
        g.stroke();
      }
      if (Math.random() < 0.6) { g.fillStyle = 'rgba(92,55,20,0.38)'; g.beginPath(); g.ellipse(Math.random() * 240 + 8, y0 + 18 + Math.random() * 28, 7, 4, 0, 0, Math.PI * 2); g.fill(); }
      g.fillStyle = 'rgba(55,32,10,0.6)'; g.fillRect(0, y0 + 61, 256, 3);
    }
  } else {
    g.fillStyle = '#4f78a3'; g.fillRect(0, 0, 256, 256);
    for (let y = 0; y < 256; y += 32) { g.fillStyle = 'rgba(255,255,255,0.09)'; g.fillRect(0, y, 256, 3); g.fillStyle = 'rgba(0,0,0,0.12)'; g.fillRect(0, y + 3, 256, 2); }
  }
  const t = new THREE.CanvasTexture(c); t.wrapS = t.wrapT = THREE.RepeatWrapping; t.anisotropy = 4; TEXC[tipo] = t; return t;
}
function matCaja(tipo, w, h, opaco) {
  const t = textura(tipo).clone(); t.needsUpdate = true; t.repeat.set(Math.max(w, 1) / TILE[tipo], Math.max(h, 1) / TILE[tipo]);
  const tr = opaco ? 0 : (+$('trans').value || 0) / 100;
  return new THREE.MeshLambertMaterial({ map: t, transparent: !opaco, opacity: 1 - tr, depthWrite: opaco || tr < 0.02 });
}
function cajaVisual(L, W, H) {
  const tipo = S.tipo, th = S.cat.tipos_embalaje[tipo].espesor_mm, g = new THREE.Group();
  const put = (padre, geo, mat, x, y, z, pared) => {
    const m = new THREE.Mesh(geo, mat); m.position.set(x, y, z); m.userData.own = true; m.userData.pared = pared; padre.add(m);
    const e = new THREE.LineSegments(new THREE.EdgesGeometry(geo), new THREE.LineBasicMaterial({ color: BORDE[tipo], transparent: true, opacity: 0.55 }));
    e.position.set(x, y, z); e.userData.own = true; e.userData.borde = pared; padre.add(e);
  };
  put(g, new THREE.BoxGeometry(L + 2 * th, th, W + 2 * th), matCaja(tipo, L, W, true), 0, -th / 2, 0, false);
  put(g, new THREE.BoxGeometry(th, H, W + 2 * th), matCaja(tipo, W, H), L / 2 + th / 2, H / 2, 0, true);
  put(g, new THREE.BoxGeometry(th, H, W + 2 * th), matCaja(tipo, W, H), -L / 2 - th / 2, H / 2, 0, true);
  put(g, new THREE.BoxGeometry(L, H, th), matCaja(tipo, L, H), 0, H / 2, W / 2 + th / 2, true);
  put(g, new THREE.BoxGeometry(L, H, th), matCaja(tipo, L, H), 0, H / 2, -W / 2 - th / 2, true);
  if (tipo === 'carton') {
    const d = W / 2, ang = 0.42;
    [[1, 'z', L], [-1, 'z', L], [1, 'x', W], [-1, 'x', W]].forEach(([sg, ax, len]) => {
      const piv = new THREE.Group(), alto = ax === 'z' ? d : d * 0.96;
      put(piv, ax === 'z' ? new THREE.BoxGeometry(len, alto, th) : new THREE.BoxGeometry(th, alto, len), matCaja(tipo, len, d), 0, alto / 2, 0, true);
      if (ax === 'z') { piv.position.set(0, H, sg * (W / 2 + th / 2)); piv.rotation.x = sg * ang; } else { piv.position.set(sg * (L / 2 + th / 2), H, 0); piv.rotation.z = -sg * ang; }
      g.add(piv);
    });
  } else if (tipo === 'madera') {
    const bt = Math.min(60, Math.max(30, Math.min(L, W) * 0.06)), osc = matCaja(tipo, bt, H); osc.color = new THREE.Color(0xa07a4c);
    [[1, 1], [1, -1], [-1, 1], [-1, -1]].forEach(([sx, sz]) => put(g, new THREE.BoxGeometry(bt, H, th * 0.9), osc, sx * (L / 2 + th - bt / 2), H / 2, sz * (W / 2 + th * 1.45), true));
    const borde = matCaja(tipo, L, bt); borde.color = new THREE.Color(0xa07a4c);
    [1, -1].forEach(sz => put(g, new THREE.BoxGeometry(L + 2 * th, bt, th * 0.9), borde, 0, H - bt / 2, sz * (W / 2 + th * 1.45), true));
    const sk = Math.min(100, Math.max(40, H * 0.12)), skm = matCaja(tipo, L, sk, true); skm.color = new THREE.Color(0x8c6a40);
    const n = W > 600 ? 3 : 2;
    for (let i = 0; i < n; i++) put(g, new THREE.BoxGeometry(L + 2 * th, sk, sk), skm, 0, -th - sk / 2, -W / 2 + sk / 2 + i * (W - sk) / (n - 1), false);
  } else {
    const lab = matCaja(tipo, L, 12);
    [1, -1].forEach(sz => put(g, new THREE.BoxGeometry(L + 2 * th + 10, 12, 10), lab, 0, H - 6, sz * (W / 2 + th + 5), true));
    [1, -1].forEach(sx => put(g, new THREE.BoxGeometry(10, 12, W + 2 * th + 30), lab, sx * (L / 2 + th + 5), H - 6, 0, true));
  }
  return g;
}
function aplicarTransparencia() {
  const tr = (+$('trans').value || 0) / 100;
  [gPack, gFis].forEach(G => G && G.traverse(o => {
    if (o.userData.pared && o.material) { o.material.opacity = 1 - tr; o.material.depthWrite = tr < 0.02; o.material.needsUpdate = true; }
    if (o.userData.borde && o.material) o.material.opacity = Math.max(0.25, 0.55 - tr * 0.2);
  }));
}

const PAL = [0x1f5f9e, 0xd08a2c, 0x2f8f6a, 0x8e5bb5, 0xc4483e, 0x4aa3c9, 0x7b8a2e, 0xb05c8a];
let instancias = [], disp = [];
function dibujarAcomodo() {
  limpiar(gPack); instancias = []; disp = [];
  const b = medidasCaja(); if (!S.cat || !b) return;
  gPack.add(cajaVisual(b.L, b.W, b.H));
  const R = S.res && S.res.resultado.resultado;
  $('cutBox').hidden = !(R && R.piezas && S.vista === 'pack');
  if (!R || !S.geo || !R.piezas) { aplicarTransparencia(); return; }
  disp = R.disposicion.slice(0, R.piezas);
  const n = disp.length, c = S.res.resultado.pieza.centro_envolvente_mm, e = S.res.resultado.pieza.envolvente_mm;
  const caras = S.geo.index ? S.geo.index.count / 3 : S.geo.attributes.position.count / 3;
  const geo = caras * n > 6e6 ? new THREE.BoxGeometry(e[0], e[1], e[2]).translate(c[0], c[1], c[2]) : S.geo;   // vista simplificada si es muy pesado
  const porOri = $('colOri').checked, claves = [...new Set(disp.map(d => JSON.stringify(d.rotacion)))], col = new THREE.Color();
  const im = new THREE.InstancedMesh(geo, new THREE.MeshPhongMaterial({ color: 0xffffff, shininess: 50, specular: 0x555555 }), Math.max(1, n));
  const T0 = new THREE.Matrix4().makeTranslation(-b.L / 2, 0, b.W / 2).multiply(CP), Tc = new THREE.Matrix4().makeTranslation(-c[0], -c[1], -c[2]), A = new THREE.Matrix4(), M = new THREE.Matrix4();
  disp.forEach((d, i) => {
    const r = d.rotacion, p = d.centro_mm;
    A.set(r[0][0], r[0][1], r[0][2], p[0], r[1][0], r[1][1], r[1][2], p[1], r[2][0], r[2][1], r[2][2], p[2], 0, 0, 0, 1);
    M.copy(T0).multiply(A).multiply(Tc); im.setMatrixAt(i, M);
    im.setColorAt(i, col.setHex(porOri ? PAL[claves.indexOf(JSON.stringify(r)) % PAL.length] : colorPieza()));
  });
  im.count = n; im.instanceMatrix.needsUpdate = true; if (im.instanceColor) im.instanceColor.needsUpdate = true;
  if (geo !== S.geo) im.userData.own = true;
  gPack.add(im); instancias = [im];
  $('cut').value = 100; aplicarCorte(); aplicarTransparencia();
}
function aplicarCorte() {
  const b = medidasCaja(); if (!b) return;
  const v = +$('cut').value / 100, n = v >= 1 ? disp.length : disp.filter(d => d.centro_mm[2] <= b.H * v + 1e-6).length;
  instancias.forEach(im => im.count = n);
  $('cutLbl').textContent = v >= 1 ? 'todas' : `${fmt(b.H * v)} mm · ${fmt(n)} u.`;
}
function encuadrarVista() {
  const b = medidasCaja();
  if (S.vista === 'part' && S.pieza) { const e = S.pieza.envolvente_mm; encuadrar(new THREE.Vector3(e[0], e[2], e[1]).multiplyScalar(1.7), new THREE.Vector3(0, e[2] / 2, 0)); }
  else if (S.vista === 'phys' && S.anim) { const d = S.anim.caja; encuadrar(new THREE.Vector3(d[0], d[2] * 1.4, d[1]), new THREE.Vector3(0, d[2] * 0.5, 0)); }
  else if (S.vista === 'pack' && b) { const sol = S.tipo === 'carton' ? b.W * 0.45 : 0; encuadrar(new THREE.Vector3(b.L + sol * 0.4, b.H + sol, b.W + sol * 0.8), new THREE.Vector3(0, (b.H + sol) / 2, 0)); }
}
function ponerVista(v) {
  if (v === 'phys' && !S.anim) v = 'pack';
  S.vista = v; ['part', 'pack', 'phys'].forEach(k => $('v-' + k).className = k === v ? 'on' : '');
  gPart.visible = v === 'part'; gPack.visible = v === 'pack'; gFis.visible = v === 'phys'; grid.visible = v === 'part';
  $('dimTag').hidden = v !== 'part'; $('repro').hidden = v !== 'phys'; $('fisTag').hidden = v !== 'phys';
  if (v === 'pack') dibujarAcomodo();
  if (v === 'phys') { if (S.anim) { S.anim.reproduciendo = true; $('btnPlay').textContent = '❚❚'; } }
  $('cutBox').hidden = !(v === 'pack' && S.res && S.res.resultado.resultado.piezas);
  encuadrarVista();
}

// ═══════════════ PASO 1: PIEZA ═══════════════
function familia() { return S.cat.familias.find(f => f.id === S.famId); }
function renderFamilias() {
  const q = $('q').value.trim().toLowerCase();
  const lista = S.cat.familias.filter(f => !q || [f.nombre, f.norma, f.id, ...(f.campos.flatMap(c => c.opciones || []))].join(' ').toLowerCase().includes(q));
  $('fams').innerHTML = lista.length ? lista.map(f => `<button class="fam${f.id === S.famId ? ' on' : ''}" data-fam="${f.id}"><svg width="24" height="24" viewBox="0 0 22 22" fill="none" stroke="currentColor" stroke-width="1.4">${ICON[f.id] || ''}</svg><span>${esc(f.nombre)}</span></button>`).join('')
    : '<div class="why" style="grid-column:1/-1">Sin resultados. Si la pieza no está en el catálogo, subí el archivo 3D.</div>';
}
function renderCampos() {
  const f = familia();
  if (!S.famVals[f.id]) { S.famVals[f.id] = {}; f.campos.forEach(c => S.famVals[f.id][c.id] = c.defecto); }
  const v = S.famVals[f.id];
  $('famNorma').textContent = f.norma;
  $('famFields').innerHTML = f.campos.map(c => c.opciones
    ? `<div class="row"><label for="ff_${c.id}">${esc(c.nombre)}</label><select id="ff_${c.id}" data-campo="${c.id}">${c.opciones.map(o => `<option${String(o) === String(v[c.id]) ? ' selected' : ''}>${o}</option>`).join('')}</select><span class="u">${c.unidad || ''}</span></div>`
    : `<div class="row"><label for="ff_${c.id}">${esc(c.nombre)}</label><input type="number" id="ff_${c.id}" data-campo="${c.id}" value="${v[c.id]}" min="0" step="0.5"><span class="u">${c.unidad || ''}</span></div>`).join('');
}
function renderTerminaciones() {
  $('sws').innerHTML = FIN.map(([id, n, c]) => `<button class="sw${S.terminacion === id ? ' on' : ''}" data-fin="${id}"><i style="background:#${c.toString(16).padStart(6, '0')}"></i>${n}</button>`).join('') +
    `<label class="sw${S.terminacion === 'libre' ? ' on' : ''}" title="Color personalizado"><input type="color" id="colorLibre" value="${S.colorLibre}" aria-label="Color personalizado">Otro</label>`;
}
function paramsPieza() {
  const material = $('mat').value;
  if (S.fuente === 'cat') {
    const v = {}; Object.entries(S.famVals[S.famId]).forEach(([k, x]) => v[k] = isNaN(+x) ? x : +x);
    return { origen: 'catalogo', familia: S.famId, valores: v, material };
  }
  const kg = +$('impKg').value;
  return { origen: 'archivo', unidades: $('impUnit').value, material, peso_kg: kg > 0 ? kg : null, nombre: $('impName').value.trim() || null };
}
let tAnalisis = null;
function pedirAnalisis(demora = 250) { clearTimeout(tAnalisis); tAnalisis = setTimeout(analizar, demora); }
async function analizar() {
  if (S.fuente === 'file' && !S.archivo) { S.pieza = null; S.geo = null; renderPieza(); dibujarPieza(); return; }
  const id = ++S.pedido;
  ocupado(S.fuente === 'file' ? 'Leyendo la pieza…' : 'Preparando la pieza…');
  try {
    const t = await trabajo('/v1/piezas', { pieza: paramsPieza() }, S.fuente === 'file' ? S.archivo : null);
    const glb = await api(t.malla_visor);
    if (id !== S.pedido) return;                               // llegó una respuesta vieja
    S.pieza = t.resultado.pieza; S.avisos = t.advertencias || [];
    S.res = null; limpiarResultado();
    S.geo = await geometriaDeGLB(glb);
    marcarDesactualizado();
    if (S.fuente === 'file') impMsg(`Pieza leída: <b>${S.pieza.envolvente_mm.map(x => fmt(x, 1)).join(' × ')} mm</b>. Si las medidas no son las reales, cambiá las unidades.`, 'ok');
    renderPieza(); dibujarPieza();
  } catch (e) {
    if (id !== S.pedido || e instanceof ErrorSesion) return;
    if (S.fuente === 'file') impMsg(esc(e.message), 'bad'); else aviso(e.message, true);
  } finally { if (id === S.pedido) ocupado(null); }
}
function geometriaDeGLB(buf) {
  return new Promise((ok, mal) => new THREE.GLTFLoader().parse(buf, '', g => {
    let geo = null;
    g.scene.updateMatrixWorld(true);
    g.scene.traverse(o => { if (!geo && o.isMesh) { geo = o.geometry.clone(); geo.applyMatrix4(o.matrixWorld); } });
    if (!geo) return mal(new Error('La pieza no tiene superficies para dibujar.'));
    if (!geo.attributes.normal) geo.computeVertexNormals();
    ok(geo);
  }, mal));
}
function impMsg(html, cls = 'info') { $('impMsg').innerHTML = html; $('impMsg').className = 'msg ' + cls; }
function renderPieza() {
  const p = S.pieza;
  $('avisos').innerHTML = S.avisos.map(a => `<div class="msg warn">${esc(a)}</div>`).join('');
  if (!p) { $('pName').textContent = '—'; $('pDesc').textContent = ''; $('pKv').innerHTML = ''; return; }
  const e = p.envolvente_mm, bv = e[0] * e[1] * e[2] / 1000, colHex = '#' + colorPieza().toString(16).padStart(6, '0');
  const fin = S.terminacion === 'libre' ? 'Personalizado' : FIN.find(f => f[0] === S.terminacion)[1];
  const mat = S.cat.materiales.find(m => m.id === p.material);
  $('pName').textContent = p.nombre; $('pDesc').textContent = p.origen === 'catalogo' ? p.norma_o_archivo : 'Archivo 3D (no se guarda)';
  $('pKv').innerHTML = `<dt>Envolvente</dt><dd>${e.map(x => fmt(x, 1)).join(' × ')} mm</dd>
    <dt>Volumen real</dt><dd>${fmt(p.volumen_cm3, p.volumen_cm3 < 10 ? 2 : 1)} cm³</dd>
    <dt>Volumen envolvente</dt><dd>${fmt(bv, bv < 10 ? 2 : 1)} cm³</dd>
    <dt>Peso unitario</dt><dd>${kgTxt(p.peso_kg)}</dd>
    <dt style="font-size:11px;color:var(--ink3)">origen del peso</dt><dd style="font-size:11px;color:var(--ink3);font-family:var(--f-ui)">${esc(p.origen_peso)}</dd>
    <dt>Material</dt><dd style="font-family:var(--f-ui)">${esc(mat ? mat.nombre : p.material)}</dd>
    <dt>Terminación</dt><dd style="font-family:var(--f-ui)"><span class="swatch" style="background:${colHex}"></span>${fin}</dd>`;
}
function ponerFuente(f) {
  S.fuente = f; $('src-cat').className = f === 'cat' ? 'on' : ''; $('src-file').className = f === 'file' ? 'on' : '';
  $('srcCat').hidden = f !== 'cat'; $('srcFile').hidden = f !== 'file';
  pedirAnalisis(0);
}
function elegirArchivo(file) {
  if (!file) return;
  const ext = (file.name.split('.').pop() || '').toLowerCase();
  if (!S.cat.formatos.includes(ext)) { impMsg(`Formato no soportado (.${esc(ext)}). Usá STEP, IGES, STL, OBJ, GLB, DXF o DWG.`, 'bad'); return; }
  if (file.size > S.cat.tamano_max_mb * 1024 * 1024) { impMsg(`El archivo supera el máximo de ${S.cat.tamano_max_mb} MB.`, 'bad'); return; }
  S.archivo = file;
  if (!$('impName').value) $('impName').value = file.name.replace(/\.[^.]+$/, '').slice(0, 120);
  if (S.paso !== 0) irPaso(0);
  if (S.fuente !== 'file') ponerFuente('file'); else pedirAnalisis(0);
}

// ═══════════════ PASO 2: EMBALAJE ═══════════════
function renderCajas() {
  $('boxList').innerHTML = S.cat.embalajes.map((c, i) => `<button class="boxopt${i === S.boxIdx ? ' on' : ''}" data-caja="${i}">
    <svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" stroke-width="1.4">${BOX_ICON[c.tipo]}</svg>
    <div><div class="t">${esc(c.nombre)}</div><div class="d">${c.interior_mm.join(' × ')} mm · máx. ${c.carga_max_kg} kg · tara ${fmt(c.tara_kg, c.tara_kg < 1 ? 2 : 0)} kg</div></div></button>`).join('') +
    `<button class="boxopt${S.boxIdx === -1 ? ' on' : ''}" data-caja="-1"><svg width="26" height="26" viewBox="0 0 26 26" fill="none" stroke="currentColor" stroke-width="1.4" stroke-dasharray="3 2"><path d="M3 8l10-4 10 4v11l-10 4-10-4z"/></svg><div><div class="t">A medida</div><div class="d">Cargá las medidas abajo</div></div></button>`;
}
function medidasCaja() {
  const L = +$('bL').value, W = +$('bW').value, H = +$('bH').value;
  return L > 0 && W > 0 && H > 0 ? { L, W, H, kg: Math.max(0, +$('bKg').value || 0) } : null;
}
function elegirCaja(i) {
  S.boxIdx = i;
  if (i >= 0) {
    const c = S.cat.embalajes[i];
    [$('bL').value, $('bW').value, $('bH').value] = c.interior_mm; $('bKg').value = c.carga_max_kg; $('bTare').value = c.tara_kg; S.taraOrigen = 'cat';
    ponerTipo(c.tipo, true); ponerManip(c.tipo === 'madera' ? 'autoelevador' : 'manual');
  }
  renderCajas(); renderCaja(); marcarDesactualizado(); if (S.vista === 'pack') { dibujarAcomodo(); encuadrarVista(); }
}
function ponerTipo(t, silencioso) {
  S.tipo = t; ['carton', 'madera', 'plastico'].forEach(k => $('bt-' + k).className = k === t ? 'on' : '');
  if (silencioso) return;
  if (S.boxIdx >= 0 && S.cat.embalajes[S.boxIdx].tipo !== t) { S.boxIdx = -1; renderCajas(); }
  estimarTara(); marcarDesactualizado(); if (S.vista === 'pack') dibujarAcomodo();
}
let tTara = null;
function estimarTara() {
  if (S.taraOrigen === 'man') { renderCaja(); return; }
  clearTimeout(tTara);
  tTara = setTimeout(async () => {
    const b = medidasCaja(); if (!b) return;
    try { const r = await api(`/v1/embalajes/tara?largo=${b.L}&ancho=${b.W}&alto=${b.H}&tipo=${S.tipo}`); $('bTare').value = r.tara_kg; S.taraOrigen = 'est'; renderCaja(); } catch (e) { /* se informa al calcular */ }
  }, 200);
}
function renderCaja() {
  const b = medidasCaja(), t = S.cat.tipos_embalaje[S.tipo], tara = +$('bTare').value || 0, rell = +$('bFill').value || 0;
  $('eName').textContent = S.boxIdx >= 0 ? S.cat.embalajes[S.boxIdx].nombre : 'A medida';
  $('tareHint').textContent = { cat: 'Tara de referencia del catálogo. Si tenés el peso real, cargalo.', est: `Estimada para ${t.nombre.toLowerCase()} según la superficie del embalaje. Si tenés el peso real, cargalo.`, man: 'Tara cargada a mano.' }[S.taraOrigen];
  if (!b) { $('eKv').innerHTML = '<dt>Medidas</dt><dd>incompletas</dd>'; return; }
  const e = t.espesor_mm;
  $('eKv').innerHTML = `<dt>Tipo</dt><dd style="font-family:var(--f-ui)">${t.nombre}</dd>
    <dt>Interior</dt><dd>${fmt(b.L)} × ${fmt(b.W)} × ${fmt(b.H)} mm</dd>
    <dt>Exterior aprox.</dt><dd>${fmt(b.L + 2 * e)} × ${fmt(b.W + 2 * e)} × ${fmt(b.H + e)} mm</dd>
    <dt>Volumen útil</dt><dd>${fmt(b.L * b.W * b.H / 1e6, 1)} L</dd>
    <dt>Carga máxima</dt><dd>${b.kg ? fmt(b.kg) + ' kg' : '—'}</dd>
    <dt>Tara</dt><dd>${fmt(tara, 2)} kg</dd>${rell ? `<dt>Relleno</dt><dd>${fmt(rell, 2)} kg</dd>` : ''}`;
}

// ═══════════════ PASO 3: CRITERIOS ═══════════════
function ponerManip(m) {
  S.manip = m; $('mh-man').className = m === 'manual' ? 'on' : ''; $('mh-fork').className = m === 'autoelevador' ? 'on' : '';
  $('manRow').hidden = m !== 'manual';
  $('mhHint').textContent = m === 'manual' ? 'El peso máximo manipulable se controla sobre el peso bruto: piezas + embalaje + relleno.' : 'Se mueve con autoelevador o zorra: no se aplica límite manual, solo la carga máxima del embalaje.';
  marcarDesactualizado();
}
function ponerPrio(p) {
  S.prio = p; ['cantidad', 'estabilidad', 'picking'].forEach(k => $('pr-' + k).className = k === p ? 'on' : '');
  $('prioHint').textContent = { cantidad: 'Gana el acomodo con más piezas.', estabilidad: 'Entre acomodos con cantidad similar (±5%), gana el que tiene más piezas apoyadas sobre su cara más grande.', picking: 'Entre acomodos con cantidad similar (±5%), gana el que usa menos orientaciones distintas: más fácil de sacar y contar.' }[p];
  marcarDesactualizado();
}

// ═══════════════ PASO 4: RESULTADO ═══════════════
function marcarDesactualizado() { S.desactualizado = true; if (S.paso === 3) $('resSub').textContent = 'Cambiaste datos: presioná Recalcular.'; }
async function calcular(opciones = {}) {
  const b = medidasCaja();
  if (!S.pieza) { aviso('Primero elegí o cargá una pieza.', true); irPaso(0); return; }
  if (!b) { aviso('Completá las medidas interiores del embalaje.', true); irPaso(1); return; }
  const params = {
    pieza: paramsPieza(),
    embalaje: { interior_mm: [b.L, b.W, b.H], tipo: S.tipo, nombre: S.boxIdx >= 0 ? S.cat.embalajes[S.boxIdx].nombre : 'A medida',
      carga_max_kg: b.kg, tara_kg: Math.max(0, +$('bTare').value || 0), relleno_kg: Math.max(0, +$('bFill').value || 0) },
    criterios: { modo: S.modo, validar_fisica: !!opciones.validar, holgura_mm: Math.max(0, +$('gap').value || 0), manipulacion: S.manip,
      peso_bruto_manipulable_kg: Math.max(0, +$('manKg').value || 0), mantener_posicion: $('upright').checked,
      prioridad: S.prio, piezas_actuales: Math.max(0, Math.floor(+$('audit').value || 0)) },
  };
  const fisica = S.modo === 'granel' || opciones.validar;
  ocupado(S.modo === 'granel' ? 'Simulando el volcado…' : opciones.validar ? 'Simulando el transporte…' : 'Calculando el mejor acomodo…');
  try {
    S.res = await trabajo('/v1/simulaciones', params, S.fuente === 'file' ? S.archivo : null, (p, txt) => ocupado(txt, p));
    S.desactualizado = false;
    S.anim = null; limpiar(gFis); $('v-phys').disabled = true;
    if (S.res.animacion) await cargarAnimacion(S.res);
    renderResultado(); ponerVista(fisica && S.anim ? 'phys' : 'pack');
  } catch (e) { if (!(e instanceof ErrorSesion)) aviso(e.message, true); }
  finally { ocupado(null); }
}
function htmlFisica(R, K) {
  const F = R.fisica;
  if (K.modo !== 'granel' && !F) return R.piezas ? `<div class="fis"><h4>Validación física</h4><div class="why">Simula el transporte en camión con el embalaje cerrado y mide cuánto se mueve cada pieza.</div><button class="btn sm w" style="margin-top:8px" data-accion="validar">Validar con vibración</button></div>` : '';
  if (!F) return '';
  if (F.error) return `<div class="fis"><h4>Validación física</h4><div class="why">${esc(F.error)}</div></div>`;
  const ver = S.anim ? '<button class="btn sm w" style="margin-top:8px" data-accion="verfisica">Ver la simulación</button>' : '';
  if (F.tipo === 'granel') {
    const m = F.muestra;
    return `<div class="fis"><h4>Simulación a granel <span class="chip geo">${fmt(F.tiempo_simulado_s, 0)} s simulados</span></h4><div class="why">
      ${m ? `Muestra de ${m.interior_mm.map(x => fmt(x)).join(' × ')} mm con ${fmt(m.piezas)} piezas, extrapolada al embalaje (±5%).` : F.llenado_parcial ? '' : `Se simularon todas las piezas (${fmt(R.maximo_posible)}).`}
      ${F.llenado_parcial ? `Se volcaron ${fmt(F.llenado_parcial.piezas)} piezas hasta ${fmt(F.llenado_parcial.altura_lecho_mm)} mm de altura; el resto del embalaje se estimó con la densidad de ese lecho (±10%).` : ''}
      ${F.ciclos} ciclo${F.ciclos === 1 ? '' : 's'} de llenado y vibrado. Acomodadas en orden entrarían ${fmt(F.maximo_ordenado)}.
      ${F.acotado_al_ordenado ? '<br>El conteo a granel superaba al ordenado y se acotó.' : ''}</div>${ver}</div>`;
  }
  const EST = { se_mantiene: ['ok', 'Se mantiene'], se_reacomoda: ['peso', 'Se reacomoda'], se_desarma: ['mal', 'Se desarma'] }[F.estado];
  return `<div class="fis"><h4>Validación física <span class="chip ${EST[0]}">${EST[1]}</span></h4>
    <dl class="kv" style="margin-top:4px">
      <dt>Piezas que se salen</dt><dd>${fmt(F.piezas_fuera)}</dd>
      <dt>Piezas volcadas (&gt; 30°)</dt><dd>${fmt(F.piezas_volcadas)}</dd>
      <dt>Piezas corridas</dt><dd>${fmt(F.piezas_corridas)} de ${fmt(F.piezas)}</dd>
      <dt>Desplazamiento medio / máx.</dt><dd>${fmt(F.desplazamiento_medio_mm, 1)} / ${fmt(F.desplazamiento_max_mm, 1)} mm</dd>
    </dl><div class="why" style="margin-top:6px">${esc(F.perfil)}. ${esc(F.criterio)}.</div>${ver}</div>`;
}
function ponerModo(m) {
  S.modo = m; $('md-ordenado').className = m === 'ordenado' ? 'on' : ''; $('md-granel').className = m === 'granel' ? 'on' : '';
  $('modoHint').textContent = m === 'ordenado' ? 'Las piezas se acomodan una por una siguiendo un patrón.' : 'Las piezas se vuelcan sin acomodar y se vibra el embalaje. El 100% es lo que entra así. Tarda entre segundos y un par de minutos.';
  marcarDesactualizado();
}

// ═══════════════ ANIMACIÓN FÍSICA ═══════════════
async function cargarAnimacion(T) {
  const buf = await api(T.animacion);
  const dv = new DataView(buf), n = dv.getUint32(0, true), f = dv.getUint32(4, true), fps = dv.getFloat32(8, true);
  const nacido = new Uint32Array(buf.slice(12, 12 + 4 * n)), datos = new Float32Array(buf.slice(12 + 4 * n));
  const R = T.resultado.resultado, F = R.fisica, E = T.resultado.embalaje;
  const caja = F && F.interior_simulado_mm ? F.interior_simulado_mm : E.interior_mm;
  S.anim = { n, f, fps, nacido, datos, caja, t: 0, dur: (f - 1) / fps, reproduciendo: true, ultimo: performance.now(), vel: 1 };
  limpiar(gFis);
  const tipoPrev = S.tipo; S.tipo = E.tipo; const bv = cajaVisual(caja[0], caja[1], caja[2]); S.tipo = tipoPrev;
  if (F && F.tipo === 'validacion') {   // embalaje cerrado: tapa translúcida
    const tapa = new THREE.Mesh(new THREE.BoxGeometry(caja[0], 2, caja[1]), new THREE.MeshLambertMaterial({ color: 0x9c8462, transparent: true, opacity: 0.12, depthWrite: false }));
    tapa.position.y = caja[2] + 1; tapa.userData.own = true; bv.add(tapa);
    bv.children.forEach(o => { if (o.parent === bv && o.rotation && o.type === 'Group') o.visible = false; });
  }
  gFis.add(bv); aplicarTransparencia();
  const c = T.resultado.pieza.centro_envolvente_mm, e = T.resultado.pieza.envolvente_mm;
  const caras = S.geo.index ? S.geo.index.count / 3 : S.geo.attributes.position.count / 3;
  const geo = caras * n > 6e6 ? new THREE.BoxGeometry(e[0], e[1], e[2]).translate(c[0], c[1], c[2]) : S.geo;
  const im = new THREE.InstancedMesh(geo, metal(colorPieza()), n);
  if (geo !== S.geo) im.userData.own = true;
  im.frustumCulled = false; gFis.add(im); S.anim.im = im;
  S.anim.T0 = new THREE.Matrix4().makeTranslation(-caja[0] / 2, 0, caja[1] / 2).multiply(CP);
  S.anim.Tc = new THREE.Matrix4().makeTranslation(-c[0], -c[1], -c[2]);
  $('v-phys').disabled = false;
  $('fisTag').innerHTML = F && F.tipo === 'validacion'
    ? `<b>Transporte simulado</b> con el embalaje cerrado<br>${fmt(F.piezas)} piezas · ${fmt(F.duracion_simulada_s, 0)} s de vibración`
    : `<b>Volcado a granel</b>${F && F.muestra ? ' · muestra del embalaje' : ''}<br>${fmt(caja[0])} × ${fmt(caja[1])} × ${fmt(caja[2])} mm`;
  pintarCuadro();
}
const _q = new THREE.Quaternion(), _p = new THREE.Vector3(), _s = new THREE.Vector3(1, 1, 1), _m = new THREE.Matrix4(), _M = new THREE.Matrix4(), _cero = new THREE.Matrix4().makeScale(0, 0, 0);
function pintarCuadro() {
  const A = S.anim; if (!A) return;
  const i = Math.max(0, Math.min(A.f - 1, Math.floor(A.t * A.fps))), base = i * A.n * 7;
  for (let k = 0; k < A.n; k++) {
    const o = base + k * 7;
    if (A.nacido[k] > i || Number.isNaN(A.datos[o])) { A.im.setMatrixAt(k, _cero); continue; }
    _p.set(A.datos[o], A.datos[o + 1], A.datos[o + 2]); _q.set(A.datos[o + 3], A.datos[o + 4], A.datos[o + 5], A.datos[o + 6]);
    _m.compose(_p, _q, _s); _M.copy(A.T0).multiply(_m).multiply(A.Tc); A.im.setMatrixAt(k, _M);
  }
  A.im.instanceMatrix.needsUpdate = true;
  $('reproT').value = Math.round(A.t / Math.max(A.dur, 1e-6) * 1000);
  $('reproLbl').textContent = fmt(A.t, 1) + ' s';
}
function avanzarAnimacion() {
  const A = S.anim, ahora = performance.now();
  if (!A) return;
  const dt = (ahora - A.ultimo) / 1000; A.ultimo = ahora;
  if (!A.reproduciendo || S.vista !== 'phys') return;
  A.t += dt * (+$('reproVel').value || 1);
  if (A.t >= A.dur) { A.t = A.dur; A.reproduciendo = false; $('btnPlay').textContent = '▶'; }
  pintarCuadro();
}

function limpiarResultado() {
  $('resBody').innerHTML = '<div class="why">Completá los pasos y presioná Calcular.</div>'; $('limChip').innerHTML = ''; $('dlBox').hidden = true;
  $('alts').innerHTML = ''; $('why').textContent = ''; $('layers').innerHTML = ''; $('resSub').textContent = 'Presioná Calcular.';
  $('fisBox').innerHTML = ''; S.anim = null; if (gFis) limpiar(gFis); $('v-phys').disabled = true; if (S.vista === 'phys') ponerVista('pack');
  if (S.vista === 'pack') dibujarAcomodo();
}
function anillo(f) {
  const r = 34, C = 2 * Math.PI * r, v = Math.max(0, Math.min(1, f)), col = v >= 0.95 ? '#1e8a5a' : v >= 0.7 ? '#1f5f9e' : '#b26a00';
  return `<svg width="84" height="84" viewBox="0 0 84 84" aria-hidden="true"><circle cx="42" cy="42" r="${r}" fill="none" stroke="#e3e7eb" stroke-width="8"/><circle cx="42" cy="42" r="${r}" fill="none" stroke="${col}" stroke-width="8" stroke-linecap="round" stroke-dasharray="${C * v} ${C}" transform="rotate(-90 42 42)"/></svg>`;
}
function renderResultado() {
  const T = S.res; if (!T) return;
  const { pieza: P, embalaje: E, criterios: K, resultado: R } = T.resultado;
  $('dlBox').hidden = false;
  $('limChip').innerHTML = R.auditoria ? '<span class="chip obj">Auditoría</span>' : R.limitado_por === 'espacio' ? '<span class="chip geo">Limitado por espacio</span>' : '<span class="chip peso">Limitado por peso</span>';
  const pb = R.peso_bruto_detalle_kg, man = K.peso_bruto_manipulable_kg || 0;
  let lead;
  if (R.auditoria) lead = `Hoy viajan <b>${fmt(R.piezas)}</b> de <b>${fmt(R.maximo_posible)}</b> piezas posibles.` + (R.piezas_que_faltan ? ` Entrarían <b>${fmt(R.piezas_que_faltan)}</b> más.` : '');
  else if (R.embalaje_vacio_excede_limite_manual) lead = `El embalaje vacío ya pesa <b>${fmt(pb.embalaje + pb.relleno, 1)} kg</b>, igual o más que el límite manual de ${fmt(man)} kg. Usá autoelevador o un embalaje más liviano.`;
  else if (R.limitado_por !== 'espacio') lead = `Entran <b>${fmt(R.maximo_posible)}</b> por espacio, pero ${R.limitado_por.startsWith('peso') ? 'el' : 'la'} ${R.limitado_por} corta en <b>${fmt(R.limite_por_peso)}</b>. Conviene un embalaje más chico.`;
  else lead = `<b>${fmt(R.piezas)}</b> de <b>${fmt(R.maximo_posible)}</b> piezas posibles: el embalaje queda lleno.`;
  const escala = Math.max(R.peso_bruto_kg, man, 1e-9), w = v => (v / escala * 100).toFixed(2) + '%';
  const COL = { p: '#1f5f9e', e: E.tipo === 'madera' ? '#8a6338' : E.tipo === 'plastico' ? '#4f78a3' : '#b8895a', r: '#9fb2c3' };
  $('resBody').innerHTML = `
    <div class="gauge">${anillo(R.saturacion)}<div><div class="gv">${Math.round(R.saturacion * 100)}%</div><div class="gl">${lead}</div></div></div>
    <div class="kpis">
      <div class="kpi"><div class="v">${fmt(R.piezas)}</div><div class="l">piezas por embalaje</div></div>
      <div class="kpi"><div class="v">${fmt(R.maximo_posible)}</div><div class="l">máximo posible (100%)</div></div>
      <div class="kpi"><div class="v">${fmt(R.peso_piezas_kg, R.peso_piezas_kg < 10 ? 2 : 1)} kg</div><div class="l">peso de las piezas</div></div>
      <div class="kpi"><div class="v">${Math.round(R.volumen_ocupado * 100)}%</div><div class="l">volumen ocupado por material</div></div>
    </div>
    <div class="gross">
      <div class="gh"><span>Peso bruto del embalaje</span><b>${fmt(R.peso_bruto_kg, R.peso_bruto_kg < 10 ? 2 : 1)} kg</b></div>
      <div class="stack"><i style="width:${w(pb.piezas)};background:${COL.p}"></i><i style="width:${w(pb.embalaje)};background:${COL.e}"></i><i style="width:${w(pb.relleno)};background:${COL.r}"></i>${man ? `<span class="mk" style="left:calc(${w(man)} - 1px)" title="Límite manipulable"></span>` : ''}</div>
      <dl class="kv">
        <dt><i style="background:${COL.p}"></i>Piezas (${fmt(R.piezas)} × ${kgTxt(P.peso_kg)})</dt><dd>${fmt(pb.piezas, 2)} kg</dd>
        <dt><i style="background:${COL.e}"></i>Embalaje vacío</dt><dd>${fmt(pb.embalaje, 2)} kg</dd>
        ${pb.relleno ? `<dt><i style="background:${COL.r}"></i>Relleno y separadores</dt><dd>${fmt(pb.relleno, 2)} kg</dd>` : ''}
        <dt class="tot">Total</dt><dd class="tot">${fmt(R.peso_bruto_kg, 2)} kg</dd>
      </dl>
      ${K.manipulacion === 'manual' && man ? `<div class="lim${R.peso_bruto_kg > man + 1e-9 ? ' over' : ''}">${R.peso_bruto_kg > man + 1e-9 ? 'Supera' : 'Dentro del'} límite manual de ${fmt(man)} kg</div>` : `<div class="lim">Manipulación con ${K.manipulacion === 'autoelevador' ? 'autoelevador' : 'límite manual sin definir'}${E.carga_max_kg ? ` · carga máxima ${fmt(E.carga_max_kg)} kg` : ''}</div>`}
    </div>`;
  $('fisBox').innerHTML = htmlFisica(R, K);
  $('resSub').textContent = `${P.nombre} en ${E.interior_mm.map(x => fmt(x)).join(' × ')} mm · ${K.modo === 'granel' ? 'a granel' : 'ordenado'} · calculado en ${fmt(T.duracion_ms / 1000, 1)} s.`;
  $('alts').innerHTML = R.alternativas.map(a => `<div class="alt${a.id === R.estrategia_id ? ' on' : ''}"><span class="t">${esc(a.nombre)}${a.id === R.estrategia_id ? ' <span class="chip obj" style="padding:1px 7px;font-size:10px">elegido</span>' : ''}</span><span class="n">${fmt(a.piezas)}</span><span class="s">${esc(a.detalle)} · ${a.orientaciones} orientación${a.orientaciones === 1 ? '' : 'es'}</span></div>`).join('');
  $('why').textContent = R.explicacion;
  $('layLbl').textContent = `Armado por capas · ${R.estrategia || ''} (${fmt(R.maximo_posible)} u.)`;
  $('layers').innerHTML = R.capas.slice(0, 12).map(c => `<tr><td>Nivel ${c.nivel} · centro a ${fmt(c.altura_centro_mm)} mm</td><td>${fmt(c.piezas)} u.</td></tr>`).join('') + (R.capas.length > 12 ? `<tr><td>… y ${R.capas.length - 12} niveles más</td><td></td></tr>` : '');
}

// ═══════════════ DESCARGAS ═══════════════
function descargar(blob, nombre) { const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = nombre; document.body.appendChild(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(a.href), 2000); }
function nombreBase() { return 'packsim_' + (S.res ? S.res.resultado.pieza.nombre : 'resultado').replace(/[^\w\-]+/g, '_').slice(0, 60); }
function descargarJson() {
  if (!S.res) return;
  descargar(new Blob([JSON.stringify({ ...S.res.resultado, advertencias: S.res.advertencias }, null, 2)], { type: 'application/json' }), nombreBase() + '.json');
}
function descargarImagen() {
  if (!S.res) return;
  if (S.vista !== 'pack') ponerVista('pack');
  renderer.render(scene, camera);
  const src = $('c3d'), { pieza: P, embalaje: E, resultado: R } = S.res.resultado;
  const W = src.width, H = src.height, pie = Math.round(84 * (W / 1200));
  const c = document.createElement('canvas'); c.width = W; c.height = H + pie; const g = c.getContext('2d');
  g.drawImage(src, 0, 0); g.fillStyle = '#ffffff'; g.fillRect(0, H, W, pie);
  const k = W / 1200, pad = 28 * k;
  g.fillStyle = '#1b2128'; g.font = `600 ${20 * k}px "IBM Plex Sans", sans-serif`; g.fillText(P.nombre, pad, H + 36 * k);
  g.fillStyle = '#56616d'; g.font = `${14 * k}px "IBM Plex Sans", sans-serif`;
  g.fillText(`${E.nombre} · ${E.interior_mm.map(x => fmt(x)).join(' × ')} mm · ${R.estrategia || ''} · ${new Date().toLocaleDateString('es-AR')}`, pad, H + 60 * k);
  const kv = [['Piezas', fmt(R.piezas)], ['Saturación', Math.round(R.saturacion * 100) + '%'], ['Máximo', fmt(R.maximo_posible)], ['Peso bruto', fmt(R.peso_bruto_kg, 1) + ' kg']];
  kv.forEach(([l, v], i) => {
    const x = W - pad - (kv.length - i) * 150 * k;
    g.fillStyle = '#8a949f'; g.font = `${12 * k}px "IBM Plex Sans", sans-serif`; g.fillText(l, x, H + 34 * k);
    g.fillStyle = '#1b2128'; g.font = `600 ${22 * k}px "IBM Plex Mono", monospace`; g.fillText(v, x, H + 62 * k);
  });
  c.toBlob(b => descargar(b, nombreBase() + '.png'), 'image/png');
}

// ═══════════════ NAVEGACIÓN Y AVISOS ═══════════════
function irPaso(p) {
  p = Math.max(0, Math.min(3, p));
  if (p > 0 && !S.pieza) { aviso(S.fuente === 'file' ? 'Primero subí el archivo de la pieza.' : 'Esperá a que se prepare la pieza.', true); return; }
  for (let i = 0; i < p; i++) S.hechos[i] = true;
  S.paso = p;
  for (let i = 0; i < 4; i++) { $('st' + i).className = 'step' + (i === p ? ' on' : S.hechos[i] ? ' done' : ''); $('p' + i).hidden = i !== p; }
  $('backBtn').disabled = p === 0;
  $('nextBtn').textContent = p === 2 ? 'Calcular' : p === 3 ? 'Recalcular' : 'Continuar';
  if (p === 0) ponerVista('part'); else if (S.vista === 'part') ponerVista('pack');
  if (p === 3 && (S.desactualizado || !S.res)) calcular();
}
let tAviso = null;
function aviso(txt, malo) { const t = $('toast'); t.textContent = txt; t.className = 'toast' + (malo ? ' bad' : ''); t.hidden = false; clearTimeout(tAviso); tAviso = setTimeout(() => t.hidden = true, 5000); }
function ocupado(txt, frac) { $('busy').hidden = !txt; if (txt) $('busyTxt').textContent = txt; $('busyPct').textContent = frac ? Math.round(frac * 100) + '%' : ''; }
function mostrarLogin() { $('login').hidden = false; setTimeout(() => $('clave').focus(), 50); }

// ═══════════════ EVENTOS ═══════════════
function conectarEventos() {
  document.addEventListener('click', e => {
    const b = e.target.closest('[data-paso],[data-fuente],[data-fam],[data-fin],[data-caja],[data-tipo],[data-manip],[data-prio],[data-vista],[data-modo],[data-accion]');
    if (!b || b.disabled) return;
    const d = b.dataset;
    if (d.paso !== undefined) irPaso(+d.paso);
    else if (d.fuente) ponerFuente(d.fuente);
    else if (d.fam) { S.famId = d.fam; renderFamilias(); renderCampos(); if (d.fam === 'rodamiento' && S.terminacion !== 'libre') { S.terminacion = 'inox'; renderTerminaciones(); } pedirAnalisis(0); }
    else if (d.fin) { S.terminacion = d.fin; renderTerminaciones(); renderPieza(); dibujarPieza(); dibujarAcomodo(); }
    else if (d.caja !== undefined) elegirCaja(+d.caja);
    else if (d.tipo) ponerTipo(d.tipo);
    else if (d.manip) ponerManip(d.manip);
    else if (d.prio) ponerPrio(d.prio);
    else if (d.vista) ponerVista(d.vista);
    else if (d.modo) ponerModo(d.modo);
    else if (d.accion === 'validar') calcular({ validar: true });
    else if (d.accion === 'verfisica') ponerVista('phys');
  });
  $('famFields').addEventListener('input', e => { const c = e.target.dataset.campo; if (!c) return; S.famVals[S.famId][c] = e.target.value; pedirAnalisis(); });
  $('famFields').addEventListener('change', e => { const c = e.target.dataset.campo; if (!c) return; S.famVals[S.famId][c] = e.target.value; pedirAnalisis(0); });
  $('q').addEventListener('input', renderFamilias);
  $('sws').addEventListener('input', e => { if (e.target.id === 'colorLibre') { S.colorLibre = e.target.value; S.terminacion = 'libre'; renderTerminaciones(); renderPieza(); dibujarPieza(); dibujarAcomodo(); } });
  $('mat').addEventListener('change', () => pedirAnalisis(0));
  $('fileIn').addEventListener('change', e => { elegirArchivo(e.target.files[0]); e.target.value = ''; });
  ['impUnit', 'impKg'].forEach(id => $(id).addEventListener('change', () => pedirAnalisis(0)));
  $('impName').addEventListener('change', () => pedirAnalisis(0));
  ['bL', 'bW', 'bH'].forEach(id => $(id).addEventListener('change', () => { S.boxIdx = -1; renderCajas(); estimarTara(); renderCaja(); marcarDesactualizado(); if (S.vista === 'pack') { dibujarAcomodo(); encuadrarVista(); } }));
  $('bKg').addEventListener('change', () => { S.boxIdx = -1; renderCajas(); renderCaja(); marcarDesactualizado(); });
  $('bTare').addEventListener('input', () => { S.taraOrigen = 'man'; renderCaja(); marcarDesactualizado(); });
  $('bFill').addEventListener('input', () => { renderCaja(); marcarDesactualizado(); });
  ['manKg', 'gap', 'upright', 'audit'].forEach(id => $(id).addEventListener('change', marcarDesactualizado));
  $('trans').addEventListener('input', aplicarTransparencia);
  $('colOri').addEventListener('change', dibujarAcomodo);
  $('cut').addEventListener('input', aplicarCorte);
  $('btnFit').addEventListener('click', encuadrarVista);
  $('backBtn').addEventListener('click', () => irPaso(S.paso - 1));
  $('nextBtn').addEventListener('click', () => S.paso === 3 ? calcular() : irPaso(S.paso + 1));
  $('btnPng').addEventListener('click', descargarImagen);
  $('btnPlay').addEventListener('click', () => { if (!S.anim) return; S.anim.reproduciendo = !S.anim.reproduciendo; if (S.anim.reproduciendo && S.anim.t >= S.anim.dur) S.anim.t = 0; $('btnPlay').textContent = S.anim.reproduciendo ? '❚❚' : '▶'; });
  $('reproT').addEventListener('input', e => { if (!S.anim) return; S.anim.reproduciendo = false; $('btnPlay').textContent = '▶'; S.anim.t = +e.target.value / 1000 * S.anim.dur; pintarCuadro(); });
  $('btnJson').addEventListener('click', descargarJson);
  $('btnSalir').addEventListener('click', async () => { try { await api('/v1/sesion', { method: 'DELETE' }); } catch (e) { /* nada */ } location.reload(); });
  $('loginForm').addEventListener('submit', async e => {
    e.preventDefault(); $('loginErr').textContent = '';
    try { await api('/v1/sesion', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ clave: $('clave').value }) }); $('login').hidden = true; $('clave').value = ''; if (!S.cat) arrancar(); }
    catch (err) { $('loginErr').textContent = err.message; }
  });
  ['dragenter', 'dragover'].forEach(ev => addEventListener(ev, e => { e.preventDefault(); $('drop').classList.add('over'); }));
  ['dragleave', 'drop'].forEach(ev => addEventListener(ev, e => { e.preventDefault(); if (ev === 'drop' || !e.relatedTarget) $('drop').classList.remove('over'); }));
  addEventListener('drop', e => { const f = e.dataTransfer && e.dataTransfer.files[0]; if (f && S.cat) elegirArchivo(f); });
}

// ═══════════════ ARRANQUE ═══════════════
async function arrancar() {
  try { S.cat = await api('/v1/catalogo'); } catch (e) { if (!(e instanceof ErrorSesion)) aviso('No se pudo cargar el catálogo: ' + e.message, true); return; }
  $('fmts').textContent = S.cat.formatos.filter(f => !['stp', 'igs'].includes(f)).map(f => f.toUpperCase()).join(' · ');
  $('fileIn').accept = S.cat.formatos.map(f => '.' + f).join(',');
  $('mat').innerHTML = S.cat.materiales.map(m => `<option value="${m.id}">${esc(m.nombre)} (${m.densidad_g_cm3} g/cm³)</option>`).join('');
  renderFamilias(); renderCampos(); renderTerminaciones(); renderCajas(); elegirCaja(1); ponerManip('manual'); ponerPrio('cantidad'); ponerModo('ordenado');
  irPaso(0); pedirAnalisis(0);
}
addEventListener('DOMContentLoaded', async () => {
  if (typeof THREE === 'undefined') { document.body.innerHTML = '<p style="padding:24px">No se pudo cargar el visor 3D. Revisá la conexión a internet.</p>'; return; }
  iniciar3D(); conectarEventos();
  try {
    const s = await api('/v1/sesion');
    if (s.requiere_clave && !s.activa) { mostrarLogin(); return; }
  } catch (e) { aviso('No se pudo conectar con el servidor.', true); return; }
  arrancar();
});
