import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Send } from 'lucide-react'
import { toast } from 'sonner'
import { fetchCaptcha, fetchLogin, fetchMe, setToken, type CaptchaInfo } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
    <div className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <div className="flex items-center gap-2">
            <Send className="h-6 w-6 text-primary" />
            <CardTitle className="text-xl">TG 自动化平台</CardTitle>
          </div>
          <p className="text-sm text-muted-foreground">多账号 Userbot · 消息 Clone · 炒群 AI</p>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="u">用户名</Label>
              <Input id="u" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoFocus />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="p">密码</Label>
              <Input id="p" type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
            </div>
            {cap?.is_enabled && (
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="c">验证码</Label>
                <div className="flex items-center gap-2">
                  <Input id="c" value={form.captcha} onChange={(e) => setForm({ ...form, captcha: e.target.value })} />
                  <img
                    src={`data:image/jpeg;base64,${cap.image}`}
                    alt="captcha"
                    className="h-9 w-20 cursor-pointer rounded border object-cover"
                    onClick={loadCaptcha}
                    title="点击刷新"
                  />
                </div>
              </div>
            )}
            <Button type="submit" className="mt-1 w-full" disabled={loading}>
              {loading ? '登录中…' : '登 录'}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
