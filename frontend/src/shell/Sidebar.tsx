import { NavLink } from 'react-router'
import { motion } from 'motion/react'

type NavItem = { to: string; label: string; soon?: boolean }

const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/import', label: 'Import' },
  { to: '/rewards', label: 'Rewards' },
]

/** The brand mark: a tally — three strokes crossed by a fifth, the oldest way
 *  anyone has kept an account, which is what "hisaab" means. Free-standing
 *  rather than in a filled badge, so it reads as a drawn mark rather than an
 *  app-store icon.
 *
 *  Inline SVG, not an <img>: the strokes take their colour from the design
 *  tokens, so the mark follows a future palette change instead of drifting out
 *  of sync as a committed asset would. Kept in sync by hand with
 *  frontend/public/favicon.svg, which is the same geometry with literal hex
 *  (a standalone file has no stylesheet in scope) on a dark rounded ground.
 *
 *  gradientUnits="userSpaceOnUse" is REQUIRED, not stylistic. The default,
 *  objectBoundingBox, resolves gradient coordinates against each element's own
 *  bounding box — and a vertical line's bbox is zero-WIDE, so the gradient
 *  degenerates and paints NOTHING. The three tally strokes silently vanished
 *  that way once, leaving only the flat-coloured diagonal; computed styles
 *  reported the stops resolving correctly the whole time, so only looking at
 *  rendered output caught it. */
function BrandMark() {
  return (
    <svg width="32" height="32" viewBox="0 0 32 32" className="shrink-0" role="img" aria-label="Hisaab">
      <defs>
        <linearGradient id="hisaab-mark-gradient" gradientUnits="userSpaceOnUse" x1="5" y1="25" x2="26" y2="6">
          <stop offset="0" stopColor="var(--color-sector-green)" />
          <stop offset="1" stopColor="var(--color-sector-yellow)" />
        </linearGradient>
      </defs>
      <g stroke="url(#hisaab-mark-gradient)" strokeWidth="3" strokeLinecap="round">
        <line x1="8" y1="7" x2="8" y2="25" />
        <line x1="15" y1="7" x2="15" y2="25" />
        <line x1="22" y1="7" x2="22" y2="25" />
      </g>
      <line x1="5" y1="24" x2="26" y2="8" stroke="var(--color-ink)" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

export default function Sidebar() {
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-line bg-carbon-1">
      <div className="px-5 pt-6 pb-8">
        <div className="flex items-center gap-2.5">
          <BrandMark />
          <span className="display text-lg text-ink">Hisaab</span>
        </div>
      </div>

      <nav className="flex flex-col gap-0.5 px-3" aria-label="Primary">
        {NAV.map((item) => (
          <NavLink key={item.to} to={item.to} end={item.to === '/'} className="group relative block">
            {({ isActive }) => (
              <span className="relative flex items-center justify-between rounded-panel px-3 py-2">
                {isActive && (
                  <motion.span
                    layoutId="nav-pill"
                    className="absolute inset-0 rounded-panel bg-carbon-2"
                    transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
                  />
                )}
                <span
                  className={`relative font-sans text-sm font-medium transition-colors duration-150 ${
                    isActive ? 'text-ink' : 'text-ink-mute group-hover:text-ink'
                  }`}
                >
                  {item.label}
                </span>
                {item.soon && (
                  <span className="relative rounded-chip border border-line px-1.5 py-0.5 text-2xs tracking-wide text-ink-faint uppercase">
                    soon
                  </span>
                )}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      <div className="mt-auto px-5 pb-5">
        <p className="text-2xs text-ink-faint">
          <span className="text-sector-green">●</span> Local only — nothing leaves this device
        </p>
      </div>
    </aside>
  )
}
