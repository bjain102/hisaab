import { useEffect, useRef } from 'react'
import { animate, motion, useMotionValue, useReducedMotion, useTransform } from 'motion/react'
import { formatINR } from '../lib/format'

/**
 * Timing-screen number ticker. Counts up on mount, re-springs on change.
 * Always rendered in the mono figure style — every number in the app that
 * moves is a figure.
 */
export default function AnimatedNumber({
  value,
  format = formatINR,
  className = '',
}: {
  value: number
  format?: (v: number) => string
  className?: string
}) {
  const reduced = useReducedMotion()
  const mv = useMotionValue(reduced ? value : 0)
  const text = useTransform(mv, (v) => format(v))
  const first = useRef(true)

  useEffect(() => {
    if (reduced) {
      mv.set(value)
      return
    }
    const controls = animate(mv, value, {
      duration: first.current ? 0.6 : 0.35,
      ease: [0.2, 0, 0, 1],
    })
    first.current = false
    return () => controls.stop()
  }, [value, reduced, mv])

  return <motion.span className={`figure ${className}`}>{text}</motion.span>
}
