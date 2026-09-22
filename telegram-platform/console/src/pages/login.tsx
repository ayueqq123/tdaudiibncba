import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { RefreshCw, Send } from 'lucide-react'
import { toast } from 'sonner'
import { fetchCaptcha, fetchLogin, fetchMe, setToken, type CaptchaInfo } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/theme-toggle'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export default function LoginPage() {
  const { setUser } = useAuth()
  const nav = useNavigate()
  const [form, setForm] = useState({ username: '', password: '', captcha: '' })
  const [cap, setCap] = useState<CaptchaInfo | null>(null)
  const [loading, setLoading] = useState(false)

  async function loadCaptcha() {
    try {
      const c = await fetchCaptcha()
      setCap(c)
      setForm((f) => ({ ...f, captcha: '' }))
    } catch {
      setCap({ is_enabled: false, expire_seconds: 0, uuid: '', image: '' })
    }
  }

  useEffect(() => {
    loadCaptcha()
  }, [])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!form.username || !form.password) return
    setLoading(true)
    try {
      const r = await fetchLogin(form.username, form.password, cap?.uuid || '', form.captcha)
      setToken(r.access_token)
      const me = await fetchMe()
      setUser(me)
      nav('/')
    } catch (err: any) {
      toast.error(err?.detail || '登录失败')
      if (cap?.is_enabled) loadCaptcha()
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-background p-4">
      {/* 背景装饰 */}
      <div className="pointer-events-none absolute -top-40 -left-40 h-96 w-96 rounded-full bg-primary/15 blur-3xl" />
      <div className="pointer-events-none absolute -right-40 -bottom-40 h-96 w-96 rounded-full bg-primary/10 blur-3xl" />

      <div className="absolute top-4 right-4">
        <ThemeToggle />
      </div>

      <div className="w-full max-w-md">
        <div className="mb-8 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl bg-primary shadow-lg shadow-primary/30">
            <Send className="h-7 w-7 text-primary-foreground" />
          </div>
          <h1 className="text-2xl font-bold tracking-tight">TG 自动化平台</h1>
          <p className="text-sm text-muted-foreground">多账号 Userbot · 消息 Clone · 炒群 AI</p>
        </div>

        <div className="rounded-2xl border bg-card p-6 shadow-xl shadow-black/5">
          <form onSubmit={submit} className="flex flex-col gap-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="u">用户名</Label>
              <Input id="u" className="h-11" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoFocus placeholder="请输入用户名" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="p">密码</Label>
              <Input id="p" className="h-11" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="请输入密码" />
            </div>
            {cap?.is_enabled && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="c">验证码</Label>
                <div className="flex items-stretch gap-2">
                  <Input id="c" className="h-14 flex-1 text-lg tracking-widest" value={form.captcha} onChange={(e) => setForm({ ...form, captcha: e.target.value })} placeholder="输入右图字符" />
                  <button
                    type="button"
                    onClick={loadCaptcha}
                    title="看不清?点击换一张"
                    className="relative h-14 w-36 shrink-0 cursor-pointer overflow-hidden rounded-md border bg-white"
                  >
                    <img src={`data:image/jpeg;base64,${cap.image}`} alt="captcha" className="h-full w-full object-cover" />
                    <span className="absolute right-1 bottom-1 rounded bg-black/50 p-0.5">
                      <RefreshCw className="h-3 w-3 text-white" />
                    </span>
                  </button>
                </div>
                <p className="text-xs text-muted-foreground">看不清?点图片换一张</p>
              </div>
            )}
            <Button type="submit" className="mt-1 h-11 w-full text-base" disabled={loading}>
              {loading ? '登录中…' : '登 录'}
            </Button>
          </form>
        </div>
        <p className="mt-6 text-center text-xs text-muted-foreground">Telegram 多账号自动化运营平台</p>
      </div>
    </div>
  )
}
