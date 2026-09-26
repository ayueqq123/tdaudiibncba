import { useEffect, useState } from 'react'
import { tgApi, type TgAlert } from '@/lib/api'

const ACK_KEY = 'tg-alert-acks'

type Acks = Record<string, string>

export function loadAcks(): Acks {
  try {
    return JSON.parse(localStorage.getItem(ACK_KEY) || '{}')
  } catch {
    return {}
  }
}

/** 标记已处理:记住处理时的最近发生时间,之后再次发生会重新出现 */
export function ackAlerts(alerts: TgAlert[]) {
  const acks = loadAcks()
  for (const a of alerts) acks[a.key] = a.last_at || ''
  localStorage.setItem(ACK_KEY, JSON.stringify(acks))
  window.dispatchEvent(new Event('tg-alerts-changed'))
}

export function isAcked(a: TgAlert, acks: Acks) {
  return a.key in acks && (acks[a.key] || '') >= (a.last_at || '')
}

export function useUnhandledAlertCount() {
  const [n, setN] = useState(0)
  useEffect(() => {
    let alive = true
    const refresh = () =>
      tgApi
        .alerts()
        .then((list) => {
          const acks = loadAcks()
          if (alive) setN(list.filter((a) => !isAcked(a, acks)).length)
        })
        .catch(() => {})
    refresh()
    const t = setInterval(refresh, 60_000)
    window.addEventListener('tg-alerts-changed', refresh)
    return () => {
      alive = false
      clearInterval(t)
      window.removeEventListener('tg-alerts-changed', refresh)
    }
  }, [])
  return n
}
