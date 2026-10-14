// The Lorenz attractor, drawn as the fading trail of a single particle (the particle itself isn't shown).
// Decorative only: one canvas, a few hundred strokes per frame, paused when hidden.
// On the homepage the particle runs on its own. With data-lorenz-paced (onboarding step 4) it only moves when
// you rate a story: each like or dislike in the tally ([data-tally]) carries it about one loop further.
// Turbo swaps pages without running this script again, so it starts on each page's canvas (see the bottom) and
// returns a function that stops it, keeping its state for next time.
function startLorenz(canvas) {
  const stops = [];
  const stop = () => stops.forEach((f) => f());
  // Observers and listeners here go when it stops.
  const watch = (observer, target, options) => { observer.observe(target, options); stops.push(() => observer.disconnect()); };
  const ctx = canvas.getContext("2d");
  const tally = canvas.hasAttribute("data-lorenz-paced") && document.querySelector("[data-tally]");

  const SIGMA = 10;
  const DT = 0.004;          // integration step
  const STEPS_PER_FRAME = 1; // speed of the particle
  const TRAIL = 10000;        // points kept in the trail
  const BUCKETS = 40;        // age steps for the fade (alpha)
  const SPIN = 0.00006;      // slow rotation of the view around the z-axis, rad/frame
  const MIN_WIDTH = 0.5, MAX_WIDTH = 2.2; // px, far side → near side
  const WIDTH_LEVELS = 7;
  const DEPTH_RANGE = 28;    // attractor spans about ±28 along the hidden axis
  const DRAW_EVERY = 2;      // draw every 2nd trail point: steps are only a few px apart
  const PER_RATING = 200;    // paced: steps per rating, about one loop
  const TOP_SPEED = 2;       // paced: steps per frame at most
  const SPEED_UP = 0.018;    // paced: added to the speed each frame, so it starts gently
  const SLOW_OVER = 12;      // paced: slows down over the last this-many steps
  const STEP_LENGTH = 0.4;   // paced: path covered by an average step; the attractor itself runs ~30× faster
                             // on the outer arcs than near the centre, so each frame covers a set length instead

  let x = 0.1, y = 0, z = 0;
  const xs = new Float32Array(TRAIL), ys = new Float32Array(TRAIL), zs = new Float32Array(TRAIL);
  let head = 0, count = 0, angle = 0.6;
  // Paced: ratings already turned into steps, steps still to go, current speed (steps/frame).
  let seen = 0, owed = 0, speed = 0;
  const ratings = () => Number(tally.dataset.liked) + Number(tally.dataset.disliked);

  // rho and beta drift with wall-clock time, so the two focal points (the wing centres)
  // wander visibly over a few minutes and carry on where they were after a reload.
  // rho stays above ~26, where the wings would stop being chaotic and the particle spirals in.
  let rho = 28, beta = 8 / 3;
  function drift() {
    const t = Date.now() / 1000;
    rho = 29 + 2.5 * Math.sin((2 * Math.PI * t) / 240);
    beta = 8 / 3 + 0.2 * Math.sin((2 * Math.PI * t) / 370);
  }
  drift();

  function deriv(x, y, z) {
    return [SIGMA * (y - x), x * (rho - z) - y, x * y - beta * z];
  }

  function step(dt = DT) {
    const [k1x, k1y, k1z] = deriv(x, y, z);
    const [k2x, k2y, k2z] = deriv(x + k1x * dt / 2, y + k1y * dt / 2, z + k1z * dt / 2);
    const [k3x, k3y, k3z] = deriv(x + k2x * dt / 2, y + k2y * dt / 2, z + k2z * dt / 2);
    const [k4x, k4y, k4z] = deriv(x + k3x * dt, y + k3y * dt, z + k3z * dt);
    x += (k1x + 2 * k2x + 2 * k3x + k4x) * dt / 6;
    y += (k1y + 2 * k2y + 2 * k3y + k4y) * dt / 6;
    z += (k1z + 2 * k2z + 2 * k3z + k4z) * dt / 6;
  }

  function push() {
    xs[head] = x; ys[head] = y; zs[head] = z;
    head = (head + 1) % TRAIL;
    count = Math.min(count + 1, TRAIL);
  }

  // Persist across page loads (tab switches) so the figure continues instead of restarting.
  // The trail is stored as raw Float32 bytes in base64 to keep it small and fast.
  const STORE_KEY = tally ? "okaeri.lorenz.taste" : "okaeri.lorenz";
  function save() {
    try {
      const all = new Float32Array(TRAIL * 3);
      all.set(xs, 0); all.set(ys, TRAIL); all.set(zs, 2 * TRAIL);
      const bytes = new Uint8Array(all.buffer);
      let bin = "";
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
      sessionStorage.setItem(STORE_KEY, JSON.stringify({ trail: TRAIL, x, y, z, head, count, angle, seen, owed, data: btoa(bin) }));
    } catch (e) {}
  }
  function restore() {
    try {
      const saved = JSON.parse(sessionStorage.getItem(STORE_KEY));
      if (!saved || saved.trail !== TRAIL) return false; // trail length changed: start fresh
      if (tally && (saved.seen ?? 0) > ratings()) return false; // ratings were cleared (redo onboarding): start fresh
      const all = new Float32Array(Uint8Array.from(atob(saved.data), (c) => c.charCodeAt(0)).buffer);
      xs.set(all.subarray(0, TRAIL)); ys.set(all.subarray(TRAIL, 2 * TRAIL)); zs.set(all.subarray(2 * TRAIL));
      ({ x, y, z, head, count, angle, seen = 0, owed = 0 } = saved);
      return true;
    } catch (e) {
      return false;
    }
  }
  addEventListener("pagehide", save);
  stops.push(save, () => removeEventListener("pagehide", save));

  // Otherwise skip the transient so the particle starts on the attractor (paced: with one loop drawn as a hint).
  if (!restore()) {
    for (let i = 0; i < 3000; i++) step();
    if (tally) for (let i = 0; i < PER_RATING; i++) { step(); push(); }
  }
  if (tally) {
    // Ratings from before this page load are drawn at once; only new ones are traced.
    owed += (ratings() - seen) * PER_RATING;
    seen = ratings();
    for (; owed > 0; owed--) { step(); push(); }
    watch(new MutationObserver(() => {
      owed += (ratings() - seen) * PER_RATING;
      seen = ratings();
    }), tally, { attributes: true, attributeFilter: ["data-liked", "data-disliked"] });
  }

  // Warm from top to bottom of the figure. On a theme switch the page's blind (style.css: theme-drop / theme-lift,
  // 640ms, cubic-bezier(0.45, 0, 0.2, 1)) slides between dark above and light below; the trail changes colour along
  // the same edge, so it never shows one theme's colours on the other's background.
  const BLIND_MS = 640;
  const rgb = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const mix = (a, b, t) => `rgb(${a.map((v, i) => Math.round(v + (b[i] - v) * t))})`;
  const bezier = (p1, p2, t) => 3 * p1 * t * (1 - t) ** 2 + 3 * p2 * t * t * (1 - t) + t ** 3;
  function ease(x) {
    let lo = 0, hi = 1;
    for (let i = 0; i < 16; i++) {
      const t = (lo + hi) / 2;
      if (bezier(0.45, 0.2, t) < x) lo = t; else hi = t;
    }
    return bezier(0, 1, (lo + hi) / 2);
  }

  let palette = null, blind = null;  // blind: the switch under way, with the palette it came from
  function readColors() {
    const css = getComputedStyle(document.documentElement);
    const before = palette;
    palette = [rgb(css.getPropertyValue("--warm").trim()), rgb(css.getPropertyValue("--warm-end").trim())];
    const direction = document.documentElement.dataset.themeTransition;
    if (direction && before) blind = { start: performance.now(), down: direction === "down", before, top: canvas.getBoundingClientRect().top };
  }
  readColors();

  function trailColor(now) {
    const top = cy - 50 * scale, bottom = cy;  // the figure's ends (z runs 0..50)
    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    // One palette from height `from` to `to`: its colour at both ends, and at the figure's ends in between.
    const paint = (colors, from, to) => {
      for (const y of [from, top, bottom, to]) {
        if (y < from || y > to) continue;
        gradient.addColorStop(y / h, mix(colors[0], colors[1], Math.min(1, Math.max(0, (y - top) / (bottom - top)))));
      }
    };
    if (blind && now - blind.start >= BLIND_MS) blind = null;
    if (!blind) {
      paint(palette, 0, h);
      return gradient;
    }
    const p = ease((now - blind.start) / BLIND_MS);
    const edge = Math.min(h, Math.max(0, innerHeight * (blind.down ? p : 1 - p) - blind.top));
    const [dark, light] = blind.down ? [palette, blind.before] : [blind.before, palette];
    paint(dark, 0, edge);
    paint(light, edge, h);
    return gradient;
  }
  watch(new MutationObserver(readColors), document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
  const scheme = matchMedia("(prefers-color-scheme: dark)");
  scheme.addEventListener("change", readColors);
  stops.push(() => scheme.removeEventListener("change", readColors));

  let w = 0, h = 0, scale = 1, cx = 0, cy = 0;
  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = canvas.clientWidth; h = canvas.clientHeight;
    canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    // Attractor spans roughly ±28 horizontally (any rotation) and 0..50 in z.
    // Paced sits in a square of its own, so it can fill it; the homepage leaves room in a tall side panel.
    // At its widest (face-on, as the view turns) it spans about 56 units, so 0.98 of the width never clips.
    scale = tally ? Math.min((w * 0.98) / 56, (h * 0.9) / 50) : Math.min((w * 0.8) / 56, (h * 0.55) / 50);
    cx = w / 2; cy = h / 2 + 25 * scale;
  }
  watch(new ResizeObserver(resize), canvas);
  resize();

  // Scalar helpers (no per-point arrays) so drawing 10k points doesn't churn the GC,
  // whose pauses show up as stutter during the theme transition.
  let cos = 1, sin = 0;
  const screenX = (i) => cx + (xs[i] * cos - ys[i] * sin) * scale;
  const screenY = (i) => cy - zs[i] * scale;

  // The hidden axis: distance towards the viewer, mapped to line thickness.
  // Quantised so consecutive segments of equal width share one stroke.
  const nearness = (i) =>
    Math.min(1, Math.max(0, (xs[i] * sin + ys[i] * cos + DEPTH_RANGE) / (2 * DEPTH_RANGE)));
  const widthLevel = (i) => Math.round(nearness(i) * (WIDTH_LEVELS - 1));
  const widthOf = (level) => MIN_WIDTH + (MAX_WIDTH - MIN_WIDTH) * (level / (WIDTH_LEVELS - 1));

  function draw() {
    ctx.clearRect(0, 0, w, h);
    if (count < 2) return;
    cos = Math.cos(angle); sin = Math.sin(angle);
    const start = (head - count + TRAIL) % TRAIL;

    ctx.lineJoin = "round";
    ctx.lineCap = "butt"; // round caps would overlap at stroke joins and show as beads
    ctx.strokeStyle = trailColor(performance.now());
    let px = screenX(start), py = screenY(start);
    let bucket = -1, level = -1;
    for (let k = 1; k < count; k++) {
      const i = (start + k) % TRAIL;
      // Skip by buffer index, not by k, so the same points are drawn every frame (no shimmer).
      if (i % DRAW_EVERY && k !== count - 1) continue;
      const b = Math.min(BUCKETS - 1, Math.floor((k * BUCKETS) / count)); // age: 0 = oldest
      const l = widthLevel(i);
      if (b !== bucket || l !== level) {
        if (bucket >= 0) ctx.stroke();
        bucket = b; level = l;
        const t = (b + 1) / BUCKETS;
        ctx.globalAlpha = 0.55 * t * t;
        ctx.lineWidth = widthOf(l);
        ctx.beginPath();
        ctx.moveTo(px, py);
      }
      px = screenX(i); py = screenY(i);
      ctx.lineTo(px, py);
    }
    ctx.stroke();
  }

  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    // Static drawing, no animation: one full trail, or (paced) each rating's steps at once.
    if (!tally && count < TRAIL) for (let i = 0; i < TRAIL; i++) { step(); push(); }
    if (tally) watch(new MutationObserver(() => { for (; owed > 0; owed--) { step(); push(); } draw(); }),
      tally, { attributes: true, attributeFilter: ["data-liked", "data-disliked"] });
    watch(new ResizeObserver(draw), canvas);
    draw();
    return stop;
  }

  // Paced: one segment per frame, as long as the current speed, so the particle glides instead of jumping whole
  // steps at a time. It speeds up gently, then slows with what's left; a new rating adds to that.
  function pacedAdvance() {
    const want = Math.min(TOP_SPEED, owed / SLOW_OVER);
    speed = want > speed ? Math.min(want, speed + SPEED_UP) : want;
    const n = Math.min(owed, Math.max(speed, owed ? 0.12 : 0));  // a slow crawl at the very end, so it does arrive
    owed -= n;
    return n;
  }

  function frame() {
    if (canvas.clientWidth > 0) { // skip work when hidden on narrow screens
      drift();
      if (tally) {
        const n = pacedAdvance();
        const pathSpeed = Math.hypot(...deriv(x, y, z));
        // The time step that covers n average steps of path here; capped where the path is slowest, to stay accurate.
        if (n > 0) { step(Math.min(3 * DT, (n * STEP_LENGTH) / pathSpeed)); push(); }
      } else {
        for (let i = 0; i < STEPS_PER_FRAME; i++) { step(); push(); }
      }
      angle += SPIN;
      draw();
    }
    raf = requestAnimationFrame(frame);
  }
  let raf = requestAnimationFrame(frame);
  stops.push(() => cancelAnimationFrame(raf));
  return stop;
}

{
  // The homepage's canvas is kept across tab switches (data-turbo-permanent): then it just carries on.
  let running = null;
  const start = () => {
    const canvas = document.querySelector("[data-lorenz]");
    if (canvas === running?.canvas) return;
    running?.stop();
    running = canvas && { canvas, stop: startLorenz(canvas) };
  };
  start();
  document.addEventListener("turbo:render", start);
}
