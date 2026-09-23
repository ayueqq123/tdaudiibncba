import { useEffect, useState } from 'react'
import { Ban, CheckCircle2, Copy, KeyRound, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { sysApi, tgApi, type SysUser } from '@/lib/api'
import { useAuth } from '@/lib/auth'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

// 新用户默认绑定到内置部门和"测试"角色(拥有 TG 模块权限)
const DEFAULT_DEPT = 1
const DEFAULT_ROLES = [1]

export default function LoginUsersPage() {
  const { user: me } = useAuth()
  const [rows, setRows] = useState<SysUser[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ username: '', password: '', nickname: '' })
  const [pwdOpen, setPwdOpen] = useState(false)
  const [pwdUser, setPwdUser] = useState<SysUser | null>(null)
  const [newPwd, setNewPwd] = useState('')
  const [cred, setCred] = useState<{ username: string; password: string } | null>(null)

  async function load() {
    setLoading(true)
    try {
      const r = await sysApi.users()
      setRows(r.items)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function save() {
    if (!form.username || !form.password) {
      toast.warning('用户名/密码必填')
      return
    }
    try {
      await sysApi.createUser({
        username: form.username,
        password: form.password,
        nickname: form.nickname || form.username,
        dept_id: DEFAULT_DEPT,
        roles: DEFAULT_ROLES,
      })
      try {
        const list = await sysApi.users()
        const nu = list.items.find((u) => u.username === form.username)
        if (nu) await tgApi.ensureWorkspace(nu.id)
      } catch {
        /* 空间会在对方首次使用时再建,失败不阻塞 */
      }
      setCred({ username: form.username, password: form.password })
      setOpen(false)
      setForm({ username: '', password: '', nickname: '' })
      load()
    } catch (e: any) {
      toast.error(e?.detail || '创建失败')
    }
  }

  async function resetPwd() {
    if (!pwdUser || !newPwd) {
      toast.warning('请输入新密码')
      return
    }
    try {
      await sysApi.resetPassword(pwdUser.id, newPwd)
      toast.success('密码已重置')
      setPwdOpen(false)
      setNewPwd('')
    } catch (e: any) {
      toast.error(e?.detail || '重置失败')
    }
  }

  async function toggle(r: SysUser) {
    try {
      await sysApi.toggleStatus(r.id)
      toast.success(r.status === 1 ? '已停用,对方无法登录' : '已启用')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
    }
  }

  async function del(r: SysUser) {
    if (!confirm(`确认删除账号「${r.username}」?对方将立即无法登录`)) return
    try {
      await sysApi.deleteUser(r.id)
      toast.success('已删除')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '删除失败')
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">用户</h2>
        <div className="flex gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> 开账号
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>开登录账号</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>用户名(登录用)</Label>
                  <Input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>初始密码</Label>
                  <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>昵称(可选)</Label>
                  <Input value={form.nickname} onChange={(e) => setForm({ ...form, nickname: e.target.value })} />
                </div>
                <p className="text-xs text-muted-foreground">新账号有独立空间,只能看自己的数据;登录后可自行上传 TG 账号</p>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={save}>创建</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
        </div>
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>用户名</TableHead>
              <TableHead>昵称</TableHead>
              <TableHead>当前密码</TableHead>
              <TableHead>状态</TableHead>
              <TableHead className="w-64">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell className="font-medium">
                  {r.username}
                  {r.username === me?.username && <Badge className="ml-2">我</Badge>}
                </TableCell>
                <TableCell>{r.nickname || '-'}</TableCell>
                <TableCell className="font-mono text-xs">{r.last_password || '-'}</TableCell>
                <TableCell>
                  <Badge variant={r.status === 1 ? 'success' : 'secondary'}>{r.status === 1 ? '启用' : '禁用'}</Badge>
                </TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setPwdUser(r)
                        setNewPwd('')
                        setPwdOpen(true)
                      }}
                    >
                      <KeyRound className="h-3.5 w-3.5" /> 改密
                    </Button>
                    {r.username !== me?.username && (
                      <>
                        <Button size="sm" variant="outline" onClick={() => toggle(r)}>
                          {r.status === 1 ? (
                            <>
                              <Ban className="h-3.5 w-3.5" /> 停用
                            </>
                          ) : (
                            <>
                              <CheckCircle2 className="h-3.5 w-3.5" /> 启用
                            </>
                          )}
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => del(r)}>
                          <Trash2 className="h-3.5 w-3.5" /> 删除
                        </Button>
                      </>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                  暂无账号
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={!!cred} onOpenChange={() => setCred(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>账号已创建</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-2 rounded-md border bg-muted/40 p-3 text-sm">
            <div>
              用户名:<span className="font-mono font-medium">{cred?.username}</span>
            </div>
            <div>
              初始密码:<span className="font-mono font-medium">{cred?.password}</span>
            </div>
            <p className="text-xs text-muted-foreground">密码只显示这一次,请复制发给对方;之后只能重置不能查看</p>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                navigator.clipboard?.writeText(`用户名:${cred?.username} 密码:${cred?.password}`)
                toast.success('已复制')
              }}
            >
              <Copy className="h-4 w-4" /> 复制凭据
            </Button>
            <Button onClick={() => setCred(null)}>知道了</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={pwdOpen} onOpenChange={setPwdOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>重置「{pwdUser?.username}」的密码</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-1.5">
            <Label>新密码</Label>
            <Input type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPwdOpen(false)}>
              取消
            </Button>
            <Button onClick={resetPwd}>重置</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
