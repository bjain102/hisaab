/**
 * Two independently-animated blurred gradient orbs — the ambient background
 * texture for this palette (paired with the static dot-grid in tokens.css's
 * html::after). Real elements, not ::before/::after: two shapes with
 * different sizes/positions/timings need two elements, and the pseudo-element
 * pair is already spoken for by the dot grid.
 *
 * prefers-reduced-motion is handled by tokens.css's global rule (`* { animation-duration: 0.01ms }`), which matches real DOM elements same as pseudo-elements —
 * no extra handling needed here.
 */
export default function AmbientOrbs() {
  return (
    <div className="pointer-events-none fixed inset-0 z-0" aria-hidden="true">
      <div
        className="absolute rounded-full"
        style={{
          top: '-120px',
          right: '-100px',
          width: '480px',
          height: '480px',
          background: 'radial-gradient(circle, var(--color-sector-green-dim), transparent 70%)',
          filter: 'blur(40px)',
          animation: 'breathe 9s ease-in-out infinite',
        }}
      />
      <div
        className="absolute rounded-full"
        style={{
          bottom: '-160px',
          left: '220px',
          width: '520px',
          height: '520px',
          background: 'radial-gradient(circle, var(--color-sector-yellow-dim), transparent 70%)',
          filter: 'blur(50px)',
          animation: 'drift 14s ease-in-out infinite',
        }}
      />
    </div>
  )
}
