import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { fetchMe, getToken, clearToken } from './api'

interface User {
  id: number
  username: string
  nickname: string
  roles: string[]
  is_superuser: boolean
}

interface AuthCtx {
  user: User | null
  ready: boolean
  setUser: (u: User | null) => void
  logout: () => void
}

const Ctx = createContext<AuthCtx>({ user: null, ready: false, setUser: () => {}, logout: () => {} })
export const useAuth = () => useContext(Ctx)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (!getToken()) {
      setReady(true)
      return
    }
    fetchMe()
      .then((u) => setUser(u))
      .catch(() => setUser(null))
      .finally(() => setReady(true))
  }, [])

  const logout = () => {
    clearToken()
    setUser(null)
  }

  return <Ctx.Provider value={{ user, ready, setUser, logout }}>{children}</Ctx.Provider>
}
