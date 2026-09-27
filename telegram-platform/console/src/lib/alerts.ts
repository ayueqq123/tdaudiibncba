import { useEffect, useState } from 'react'
import { tgApi } from '@/lib/api'

export const ALERTS_CHANGED = 'tg-alerts-changed'

export function useUnhandledAlertCount() {
  const [n, setN] = useState(0)
  useEffect(() => {
    let alive = true
    const refresh = () =>
      tgApi
        .alerts()
        .then((list) => {
          if (alive) setN(list.filter((a) => !a.handled).length)
        })
        .catch(() => {})
    refresh()
    const t = setInterval(refresh, 60_000)
    window.addEventListener(ALERTS_CHANGED, refresh)
    return () => {
      alive = false
      clearInterval(t)
      window.removeEventListener(ALERTS_CHANGED, refresh)
    }
  }, [])
  return n
}
