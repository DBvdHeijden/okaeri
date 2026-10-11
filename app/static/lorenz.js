// A single particle on the Lorenz attractor with a fading trail.
// Decorative only: one canvas, a few hundred strokes per frame, paused when hidden.
(() => {
  const canvas = document.querySelector("[data-lorenz]");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const SIGMA = 10, RHO = 28, BETA = 8 / 3;
  const DT = 0.004;          // integration step
  const STEPS_PER_FRAME = 1; // speed of the particle
  const TRAIL = 10000;        // points kept in the trail
  const BUCKETS = 40;        // age steps for the fade (alpha)
  const SPIN = 0.00006;      // slow rotation of the view around the z-axis, rad/frame
  const MIN_WIDTH = 0.5, MAX_WIDTH = 2.2; // px, far side → near side
  const WIDTH_LEVELS = 7;
  const DEPTH_RANGE = 28;    // attractor spans about ±28 along the hidden axis

  let x = 0.1, y = 0, z = 0;
  const xs = new Float32Array(TRAIL), ys = new Float32Array(TRAIL), zs = new Float32Array(TRAIL);
  let head = 0, count = 0, angle = 0.6;

  function deriv(x, y, z) {
    return [SIGMA * (y - x), x * (RHO - z) - y, x * y - BETA * z];
  }

  function step() {
    const [k1x, k1y, k1z] = deriv(x, y, z);
    const [k2x, k2y, k2z] = deriv(x + k1x * DT / 2, y + k1y * DT / 2, z + k1z * DT / 2);
    const [k3x, k3y, k3z] = deriv(x + k2x * DT / 2, y + k2y * DT / 2, z + k2z * DT / 2);
    const [k4x, k4y, k4z] = deriv(x + k3x * DT, y + k3y * DT, z + k3z * DT);
    x += (k1x + 2 * k2x + 2 * k3x + k4x) * DT / 6;
    y += (k1y + 2 * k2y + 2 * k3y + k4y) * DT / 6;
    z += (k1z + 2 * k2z + 2 * k3z + k4z) * DT / 6;
  }

  function push() {
    xs[head] = x; ys[head] = y; zs[head] = z;
    head = (head + 1) % TRAIL;
    count = Math.min(count + 1, TRAIL);
  }

  // Persist across page loads (tab switches) so the figure continues instead of restarting.
  // The trail is stored as raw Float32 bytes in base64 to keep it small and fast.
  const STORE_KEY = "okaeri.lorenz";
  function save() {
    try {
      const all = new Float32Array(TRAIL * 3);
      all.set(xs, 0); all.set(ys, TRAIL); all.set(zs, 2 * TRAIL);
      const bytes = new Uint8Array(all.buffer);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ trail: TRAIL, x, y, z, head, count, angle, data: btoa(bin) }));
    } catch (e) {}
  }
  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORE_KEY));
      if (!saved || saved.trail !== TRAIL) return false; // trail length changed: start fresh
      const all = new Float32Array(Uint8Array.from(atob(saved.data), (c) => c.charCodeAt(0)).buffer);
      xs.set(all.subarray(0, TRAIL)); ys.set(all.subarray(TRAIL, 2 * TRAIL)); zs.set(all.subarray(2 * TRAIL));
      ({ x, y, z, head, count, angle } = saved);
      return true;
    } catch (e) {
      return false;
    }
  }
  addEventListener("pagehide", save);

  // Otherwise skip the transient so the particle starts on the attractor.
  if (!restore()) for (let i = 0; i < 3000; i++) step();

  let trailColor = "";
  function readColors() {
    const css = getComputedStyle(document.documentElement);
    trailColor = css.getPropertyValue("--muted").trim();
  }
  readColors();
  new MutationObserver(readColors).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", readColors);

  let w = 0, h = 0, scale = 1, cx = 0, cy = 0;
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Attractor spans roughly ±28 horizontally (any rotation) and 0..50 in z.
    scale = Math.min((w * 0.8) / 56, (h * 0.55) / 50);
    cx = w / 2; cy = h / 2 + 25 * scale;
  }
  new ResizeObserver(resize).observe(canvas);
  resize();

  const project = (i, cos, sin) => [
    cx + (xs[i] * cos - ys[i] * sin) * scale,
    cy - zs[i] * scale,
  ];

  // The hidden axis: distance towards the viewer, mapped to line thickness.
  // Quantised so consecutive segments of equal width share one stroke.
  const nearness = (i, cos, sin) =>
    Math.min(1, Math.max(0, (xs[i] * sin + ys[i] * cos + DEPTH_RANGE) / (2 * DEPTH_RANGE)));
  const widthLevel = (i, cos, sin) => Math.round(nearness(i, cos, sin) * (WIDTH_LEVELS - 1));
  const widthOf = (level) => MIN_WIDTH + (MAX_WIDTH - MIN_WIDTH) * (level / (WIDTH_LEVELS - 1));

  function draw() {
    ctx.clearRect(0, 0, w, h);
    if (count < 2) return;
    const cos = Math.cos(angle), sin = Math.sin(angle);
    const start = (head - count + TRAIL) % TRAIL;

    ctx.lineJoin = "round";
    ctx.lineCap = "butt"; // round caps would overlap at stroke joins and show as beads
    ctx.strokeStyle = trailColor;
    let [px, py] = project(start, cos, sin);
    let bucket = -1, level = -1;
    for (let k = 1; k < count; k++) {
      const i = (start + k) % TRAIL;
      const b = Math.min(BUCKETS - 1, Math.floor((k * BUCKETS) / count)); // age: 0 = oldest
      const l = widthLevel(i, cos, sin);
      if (b !== bucket || l !== level) {
        if (bucket >= 0) ctx.stroke();
        bucket = b; level = l;
        const t = (b + 1) / BUCKETS;
        ctx.globalAlpha = 0.55 * t * t;
        ctx.lineWidth = widthOf(l);
        ctx.beginPath();
        ctx.moveTo(px, py);
      }
      [px, py] = project(i, cos, sin);
      ctx.lineTo(px, py);
    }
    ctx.stroke();

    const last = (head - 1 + TRAIL) % TRAIL;
    const [hx, hy] = project(last, cos, sin);
    ctx.globalAlpha = 0.8;
    ctx.fillStyle = trailColor;
    ctx.beginPath();
    ctx.arc(hx, hy, 1.5 + 1.5 * nearness(last, cos, sin), 0, Math.PI * 2);
    ctx.fill();
  }

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    // Static drawing: one full trail, no animation.
    if (count < TRAIL) for (let i = 0; i < TRAIL; i++) { step(); push(); }
    new ResizeObserver(draw).observe(canvas);
    draw();
    return;
  }

  function frame() {
    if (canvas.clientWidth > 0) { // skip work when hidden on narrow screens
      for (let i = 0; i < STEPS_PER_FRAME; i++) { step(); push(); }
      angle += SPIN;
      draw();
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
})();
