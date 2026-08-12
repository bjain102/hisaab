import { NavLink } from 'react-router'
import { motion } from 'motion/react'

type NavItem = { to: string; label: string }

const NAV: NavItem[] = [
  { to: '/', label: 'Dashboard' },
  { to: '/transactions', label: 'Transactions' },
  { to: '/import', label: 'Import' },
  { to: '/rewards', label: 'Rewards' },
]

export default function Sidebar() {
  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-line bg-carbon-1">
      <div className="px-5 pt-6 pb-8">
        <div className="flex items-center gap-2.5">
          <span
            className="flex h-[34px] w-[34px] shrink-0 items-center justify-center rounded-[10px]"
            style={{ background: 'linear-gradient(135deg, var(--color-sector-green), var(--color-sector-yellow))' }}
            aria-hidden="true"
          >
            <span className="h-3 w-3 rounded-[3px] bg-carbon-0" />
          </span>
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
