// A single particle on the Lorenz attractor with a fading trail.
// Decorative only: one canvas, ~40 strokes per frame, paused when hidden.
(() => {
  const canvas = document.querySelector("[data-lorenz]");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");

  const SIGMA = 10, RHO = 28, BETA = 8 / 3;
  const DT = 0.004;          // integration step
  const STEPS_PER_FRAME = 1; // speed of the particle
  const TRAIL = 5000;        // points kept in the trail
  const BUCKETS = 40;        // trail drawn as this many strokes of equal alpha
  const SPIN = 0.00006;      // slow rotation of the view around the z-axis, rad/frame

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

  // Skip the transient so the particle starts on the attractor.
  for (let i = 0; i < 3000; i++) step();

  let trailColor = "", headColor = "";
  function readColors() {
    const css = getComputedStyle(document.documentElement);
    trailColor = css.getPropertyValue("--muted").trim();
    headColor = css.getPropertyValue("--accent").trim();
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

  function draw() {
    ctx.clearRect(0, 0, w, h);
    if (count < 2) return;
    const cos = Math.cos(angle), sin = Math.sin(angle);
    const start = (head - count + TRAIL) % TRAIL;
    const per = Math.ceil(count / BUCKETS);

    ctx.lineWidth = 1;
    ctx.lineJoin = "round";
    ctx.strokeStyle = trailColor;
    for (let b = 0; b * per < count - 1; b++) {
      const from = b * per, to = Math.min(from + per, count - 1);
      const t = (b + 1) / BUCKETS; // 0 = oldest, 1 = newest
      ctx.globalAlpha = 0.55 * t * t;
      ctx.beginPath();
      let [px, py] = project((start + from) % TRAIL, cos, sin);
      ctx.moveTo(px, py);
      for (let k = from + 1; k <= to; k++) {
        [px, py] = project((start + k) % TRAIL, cos, sin);
        ctx.lineTo(px, py);
      }
      ctx.stroke();
    }

    const [hx, hy] = project((head - 1 + TRAIL) % TRAIL, cos, sin);
    ctx.globalAlpha = 1;
    ctx.fillStyle = headColor;
    ctx.beginPath();
    ctx.arc(hx, hy, 2.25, 0, Math.PI * 2);
    ctx.fill();
  }

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    // Static drawing: one full trail, no animation.
    for (let i = 0; i < TRAIL; i++) { step(); push(); }
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
