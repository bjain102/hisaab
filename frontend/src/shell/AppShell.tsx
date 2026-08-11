import { useLocation, useOutlet } from 'react-router'
import { AnimatePresence, motion } from 'motion/react'
import Sidebar from './Sidebar'
import AmbientOrbs from './AmbientOrbs'
import ToastHost from '../components/Toast'

export default function AppShell() {
  const location = useLocation()
  // useOutlet (not <Outlet/>) so the exiting page keeps its own element
  // during AnimatePresence transitions instead of re-rendering the new one.
  const outlet = useOutlet()

  return (
    <div className="flex min-h-screen bg-carbon-0">
      <AmbientOrbs />
      <Sidebar />
      <main className="min-w-0 flex-1">
        <AnimatePresence mode="wait" initial={false}>
          <motion.div
            key={location.pathname}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
            className="mx-auto max-w-6xl px-8 py-8"
          >
            {outlet}
          </motion.div>
        </AnimatePresence>
      </main>
      <ToastHost />
    </div>
  )
}
