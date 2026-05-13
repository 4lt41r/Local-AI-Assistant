/**
 * animation.js — JARVIS Molecular Animation System
 * Standalone controller that can be imported by other pages
 * Requires Three.js r128 loaded globally
 *
 * Usage:
 *   const mol = MolecularSystem.init(canvasEl, options);
 *   mol.setMicLevel(0.5);   // 0–1
 *   mol.setMousePos(x, y);  // NDC coords
 *   mol.dispose();
 */

const MolecularSystem = (() => {

  const DEFAULTS = {
    nodeCount:   120,
    bondDist:    22,
    bondMax:     3,
    spread:      60,
    mouseForce:  0.04,
    micGain:     2.5,
    colorA:      0x00d4ff,
    colorB:      0x0080ff,
    colorC:      0x00ff88,
  };

  function init(canvas, opts = {}) {
    const C = { ...DEFAULTS, ...opts };

    // ── Renderer ────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(canvas.clientWidth, canvas.clientHeight);
    renderer.setClearColor(0x020408, 1);

    const scene  = new THREE.Scene();
    scene.fog    = new THREE.FogExp2(0x020408, 0.008);

    const camera = new THREE.PerspectiveCamera(
      60, canvas.clientWidth / canvas.clientHeight, 0.1, 1000
    );
    camera.position.set(0, 0, 90);

    const colA = new THREE.Color(C.colorA);
    const colB = new THREE.Color(C.colorB);
    const colC = new THREE.Color(C.colorC);

    // ── Nodes ────────────────────────────────────────────────
    const nodes  = [];
    const geo    = new THREE.SphereGeometry(0.55, 7, 7);

    function randSphere(r) {
      const u=Math.random(), v=Math.random(), w=Math.random();
      const theta=2*Math.PI*u, phi=Math.acos(2*v-1), rad=r*Math.cbrt(w);
      return new THREE.Vector3(
        rad*Math.sin(phi)*Math.cos(theta),
        rad*Math.sin(phi)*Math.sin(theta),
        rad*Math.cos(phi)
      );
    }

    for (let i = 0; i < C.nodeCount; i++) {
      const pos   = randSphere(C.spread);
      const c     = Math.random();
      const color = c < 0.6 ? colA.clone() : c < 0.85 ? colB.clone() : colC.clone();
      const mat   = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.75 });
      const mesh  = new THREE.Mesh(geo, mat);
      mesh.position.copy(pos);
      scene.add(mesh);
      nodes.push({
        mesh, baseColor: color.clone(),
        vel:   new THREE.Vector3((Math.random()-.5)*.012, (Math.random()-.5)*.012, (Math.random()-.5)*.012),
        phase: Math.random() * Math.PI * 2
      });
    }

    // ── Bonds ────────────────────────────────────────────────
    const bondGroup = new THREE.Group();
    scene.add(bondGroup);
    const bonds = [];

    function rebuildBonds() {
      while (bondGroup.children.length) bondGroup.remove(bondGroup.children[0]);
      bonds.length = 0;
      const cnt = new Array(C.nodeCount).fill(0);
      for (let i = 0; i < nodes.length; i++) {
        if (cnt[i] >= C.bondMax) continue;
        for (let j = i + 1; j < nodes.length; j++) {
          if (cnt[j] >= C.bondMax) continue;
          const d = nodes[i].mesh.position.distanceTo(nodes[j].mesh.position);
          if (d < C.bondDist) {
            const bg = new THREE.BufferGeometry().setFromPoints([
              nodes[i].mesh.position.clone(),
              nodes[j].mesh.position.clone()
            ]);
            const bm = new THREE.LineBasicMaterial({ color:0x00d4ff, transparent:true, opacity:(1-d/C.bondDist)*0.35 });
            const ln = new THREE.Line(bg, bm);
            bondGroup.add(ln);
            bonds.push({ line:ln, i, j });
            cnt[i]++; cnt[j]++;
          }
        }
      }
    }
    rebuildBonds();

    // ── Internal state ────────────────────────────────────────
    let mouse3   = new THREE.Vector3();
    let micLevel = 0;
    let frame    = 0;
    let rafId    = null;

    const raycaster = new THREE.Raycaster();
    const planeZ    = new THREE.Plane(new THREE.Vector3(0, 0, 1), 0);
    const mouseNDC  = new THREE.Vector2();

    // ── Loop ─────────────────────────────────────────────────
    function tick() {
      rafId = requestAnimationFrame(tick);
      const t = performance.now() * 0.001;
      frame++;

      camera.position.x = Math.sin(t * 0.04) * 7;
      camera.position.y = Math.cos(t * 0.03) * 4;
      camera.lookAt(scene.position);

      for (let i = 0; i < nodes.length; i++) {
        const n = nodes[i], pos = n.mesh.position;
        n.vel.x += Math.sin(t * 0.3  + n.phase)       * 0.0003;
        n.vel.y += Math.cos(t * 0.25 + n.phase * 1.3)  * 0.0003;
        n.vel.z += Math.sin(t * 0.2  + n.phase * 0.7)  * 0.0002;

        if (micLevel > 0.05) {
          n.vel.addScaledVector(pos.clone().normalize(), micLevel * C.micGain * 0.001);
        }

        if (mouse3.lengthSq() > 0) {
          const diff = pos.clone().sub(mouse3);
          const d2   = diff.lengthSq();
          if (d2 < 400 && d2 > 0.1)
            n.vel.addScaledVector(diff.normalize(), C.mouseForce / (d2 + 1) * 8);
        }

        n.vel.multiplyScalar(0.985);
        if (pos.length() > C.spread * 1.2)
          n.vel.addScaledVector(pos.clone().negate().normalize(), 0.002);
        pos.add(n.vel);

        n.mesh.material.opacity = Math.min(1, 0.55 + 0.2 * Math.sin(t * 1.5 + n.phase) + micLevel * 0.3);
        if (micLevel > 0.15) n.mesh.material.color.lerpColors(n.baseColor, colC, micLevel * 0.5);
        else n.mesh.material.color.lerp(n.baseColor, 0.05);
        n.mesh.scale.setScalar(1 + micLevel * 1.5);
      }

      if (frame % 2 === 0) {
        for (const b of bonds) {
          const pi = nodes[b.i].mesh.position, pj = nodes[b.j].mesh.position;
          const pa = b.line.geometry.attributes.position;
          pa.setXYZ(0, pi.x, pi.y, pi.z);
          pa.setXYZ(1, pj.x, pj.y, pj.z);
          pa.needsUpdate = true;
          b.line.material.opacity = (1 - pi.distanceTo(pj) / C.bondDist) * 0.35;
        }
      }

      if (frame % 180 === 0) rebuildBonds();

      renderer.render(scene, camera);
    }
    tick();

    // ── Resize ────────────────────────────────────────────────
    function onResize() {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    }
    window.addEventListener('resize', onResize);

    // ── Public API ────────────────────────────────────────────
    return {
      setMicLevel(level) { micLevel = Math.max(0, Math.min(1, level)); },

      setMouseNDC(x, y) {
        mouseNDC.set(x, y);
        raycaster.setFromCamera(mouseNDC, camera);
        raycaster.ray.intersectPlane(planeZ, mouse3);
      },

      setMouseScreen(ex, ey) {
        this.setMouseNDC(
          (ex / canvas.clientWidth)  * 2 - 1,
          -(ey / canvas.clientHeight) * 2 + 1
        );
      },

      dispose() {
        cancelAnimationFrame(rafId);
        window.removeEventListener('resize', onResize);
        renderer.dispose();
      }
    };
  }

  return { init };
})();

if (typeof module !== 'undefined') module.exports = MolecularSystem;
