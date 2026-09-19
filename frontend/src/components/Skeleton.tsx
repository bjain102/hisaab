/** Loading placeholder. Shapes: line (text), stat (hero figure), block (chart/panel body). */
export default function Skeleton({
  shape = 'line',
  className = '',
}: {
  shape?: 'line' | 'stat' | 'block'
  className?: string
}) {
  const base = 'animate-pulse rounded-panel bg-carbon-2'
  const shapes = {
    line: 'h-4 w-32',
    stat: 'h-7 w-40',
    block: 'h-48 w-full',
  }
  return <div className={`${base} ${shapes[shape]} ${className}`} aria-hidden="true" />
}
