import { useEffect, useState } from 'react'
import { AnimatePresence, motion } from 'motion/react'

export type ToastTone = 'info' | 'good' | 'alert'
type ToastMsg = { id: number; text: string; tone: ToastTone }

let nextId = 1
let push: ((t: ToastMsg) => void) | null = null

/** Fire a toast from anywhere: toast('Imported 34 transactions', 'good') */
export function toast(text: string, tone: ToastTone = 'info') {
  push?.({ id: nextId++, text, tone })
}

const toneClass: Record<ToastTone, string> = {
  info: 'border-line-strong text-ink',
  good: 'border-sector-green/40 text-sector-green',
  alert: 'border-alert/50 text-alert',
}

/** Mount once in the shell. Renders the toast stack bottom-right. */
export default function ToastHost() {
  const [items, setItems] = useState<ToastMsg[]>([])

  useEffect(() => {
    push = (t) => {
      setItems((cur) => [...cur, t])
      setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== t.id)), 3500)
    }
    return () => {
      push = null
    }
  }, [])

  return (
    <div className="pointer-events-none fixed right-6 bottom-6 z-50 flex flex-col gap-2">
      <AnimatePresence>
        {items.map((t) => (
          <motion.div
            key={t.id}
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 6 }}
            transition={{ duration: 0.22, ease: [0.2, 0, 0, 1] }}
            className={`rounded-panel border bg-carbon-2 px-4 py-2.5 text-sm shadow-lg ${toneClass[t.tone]}`}
          >
            {t.text}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  )
}
