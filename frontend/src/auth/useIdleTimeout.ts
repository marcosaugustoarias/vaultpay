import { useEffect, useRef, useState } from 'react'

/**
 * SEC-FE-03: automatic sign-out after inactivity (PCI DSS 8.2.8 asks for <= 15 min;
 * banking apps typically use 5). Shows a warning during the last `warnMs`.
 */
export function useIdleTimeout(timeoutMs: number, warnMs: number, onTimeout: () => void, enabled: boolean) {
  const [remaining, setRemaining] = useState<number | null>(null)
  const last = useRef(Date.now())
  const cb = useRef(onTimeout)
  cb.current = onTimeout

  useEffect(() => {
    if (!enabled) return
    last.current = Date.now()
    const bump = () => {
      last.current = Date.now()
    }
    const events = ['pointerdown', 'keydown', 'scroll', 'touchstart'] as const
    events.forEach((e) => window.addEventListener(e, bump, { passive: true }))
    const id = window.setInterval(() => {
      const left = timeoutMs - (Date.now() - last.current)
      if (left <= 0) {
        setRemaining(null)
        cb.current()
      } else setRemaining(left <= warnMs ? left : null)
    }, 1000)
    return () => {
      events.forEach((e) => window.removeEventListener(e, bump))
      window.clearInterval(id)
    }
  }, [enabled, timeoutMs, warnMs])

  return { remainingMs: remaining, stayActive: () => (last.current = Date.now()) }
}
