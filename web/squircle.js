/* Squircle (superellipse) corners via clip-path, ported from the mountains
 * project's SquircleBox component. CSS border-radius draws circular corners;
 * this traces Apple-style continuous corners and re-clips on every resize.
 */

function buildSquirclePath(w, h, r, n = 4, topOnly = false) {
  const cr = Math.min(r, w / 2, h / 2);
  if (cr === 0) return `M 0 0 L ${w} 0 L ${w} ${h} L 0 ${h} Z`;
  // Bezier control-point ratio derived by matching the superellipse at its 45° parameter.
  // n=2 (circle) → k≈0.552 | n=4 (Apple squircle) → k≈0.909
  const f = Math.pow(Math.SQRT1_2, 2 / n);
  const k = Math.min((f - 0.5) / 0.375, 1);
  const kc = cr * k;
  const p = (v) => v.toFixed(2);
  const top = [
    `M ${p(cr)} 0`,
    `L ${p(w - cr)} 0`,
    `C ${p(w - cr + kc)} 0 ${p(w)} ${p(cr - kc)} ${p(w)} ${p(cr)}`,
  ];
  const left = [
    `L 0 ${p(cr)}`,
    `C 0 ${p(cr - kc)} ${p(cr - kc)} 0 ${p(cr)} 0`,
    "Z",
  ];
  if (topOnly) return [...top, `L ${p(w)} ${p(h)}`, `L 0 ${p(h)}`, ...left].join(" ");
  return [
    ...top,
    `L ${p(w)} ${p(h - cr)}`,
    `C ${p(w)} ${p(h - cr + kc)} ${p(w - cr + kc)} ${p(h)} ${p(w - cr)} ${p(h)}`,
    `L ${p(cr)} ${p(h)}`,
    `C ${p(cr - kc)} ${p(h)} 0 ${p(h - cr + kc)} 0 ${p(h - cr)}`,
    ...left,
  ].join(" ");
}

// Keeps `el` clipped to a squircle. `opts()` is re-read on each resize so the
// shape can change with the layout (e.g. top corners only as a mobile sheet).
// Pass an <svg> sitting over `el` as `outline` to stroke the same shape.
function squircle(el, opts, outline = null) {
  const update = () => {
    const { r = 28, n = 4, topOnly = false } = opts();
    const w = el.offsetWidth, h = el.offsetHeight;
    if (w > 0 && h > 0) {
      const d = buildSquirclePath(w, h, r, n, topOnly);
      el.style.clipPath = `path("${d}")`;
      el.style.borderRadius = "0";
      if (outline) {
        outline.setAttribute("viewBox", `0 0 ${w} ${h}`);
        // Inset half a pixel so a 1px stroke lands crisply inside the edge.
        const path = outline.querySelector("path");
        path.setAttribute("d", buildSquirclePath(w - 1, h - 1, r - 0.5, n, topOnly));
        path.setAttribute("transform", "translate(0.5 0.5)");
      }
    }
  };
  update();
  new ResizeObserver(update).observe(el);
  return update;
}
