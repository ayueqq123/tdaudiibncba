import { useEffect, useRef, useState } from 'react'
import { Play, RefreshCw, Smartphone, Trash2, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type ApiCredential, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const statusVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  active: 'success',
  running: 'success',
  stopped: 'secondary',
  imported_quarantine: 'warning',
  imported_verified: 'default',
  reauth_required: 'warning',
  revoked: 'destructive',
  disabled: 'secondary',
  auth_dead: 'destructive',
  banned: 'destructive',
  frozen: 'destructive',
  error: 'destructive',
}

const statusLabel: Record<string, string> = {
  active: '运行中',
  stopped: '已停止',
  error: '连接失败',
  imported_quarantine: '待启动',
  imported_verified: '已验证',
  reauth_required: '需重新登录',
  revoked: '已失效',
  disabled: '已禁用',
  auth_dead: '登录失效',
  banned: '已禁言',
  frozen: '已冻结',
}

export default function AccountsPage() {
  const [rows, setRows] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const [loginOpen, setLoginOpen] = useState(false)
  const [loginStep, setLoginStep] = useState<'form' | 'code'>('form')
  const [loginBusy, setLoginBusy] = useState(false)
  const [loginId, setLoginId] = useState('')
  const [needPwd, setNeedPwd] = useState(false)
  const [lf, setLf] = useState({ phone: '', api_id: '', api_hash: '', code: '', password: '' })
  const [creds, setCreds] = useState<ApiCredential[]>([])
  const [credIdx, setCredIdx] = useState('')

  function pickCred(idx: string) {
    setCredIdx(idx)
    if (idx === 'manual') {
      setLf((p) => ({ ...p, api_id: '', api_hash: '' }))
      return
    }
    const c = creds[Number(idx)]
    if (c) setLf((p) => ({ ...p, api_id: String(c.api_id), api_hash: c.api_hash }))
  }

  async function load() {
    setLoading(true)
    try {
      const acc = await tgApi.accounts()
      setRows(acc)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function setDesired(r: TgAccount, status: string) {
    setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, desired_status: status } : x)))
    try {
      await tgApi.updateAccount(r.id, {
        tenant_id: r.tenant_id,
        project_id: r.project_id,
        desired_status: status,
        observed_status: r.observed_status,
      })
      toast.success(status === 'running' ? '已下发启动' : '已下发停止')
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
    } finally {
      load()
    }
  }

  async function syncChats(r: TgAccount) {
    try {
      await tgApi.issueCommand(r.id, { type: 'SyncChats' })
      toast.success('已下发同步群列表')
    } catch (e: any) {
      toast.error(e?.detail || '下发失败')
    }
  }

  // 死态:这些号起不来也不该动
  const DEAD = ['auth_dead', 'revoked', 'banned', 'frozen', 'reauth_required', 'error', 'disabled']
  const [startAllBusy, setStartAllBusy] = useState(false)
  const [delFrozenOpen, setDelFrozenOpen] = useState(false)
  const [delFrozenBusy, setDelFrozenBusy] = useState(false)
  const frozenCount = rows.filter((r) => r.observed_status === 'frozen').length
  async function deleteFrozen() {
    setDelFrozenBusy(true)
    try {
      const r = await tgApi.deleteFrozenAccounts()
      toast.success(`已删除 ${r.deleted} 个冻结账号`)
      setDelFrozenOpen(false)
    } catch (e: any) {
      toast.error(e?.detail || '删除失败')
    } finally {
      setDelFrozenBusy(false)
      load()
    }
  }
  async function startAll() {
    const normal = rows.filter(
      (r) => r.desired_status !== 'running' && !DEAD.includes(r.observed_status),
    )
    if (!normal.length) {
      toast.warning('没有可启动的正常账号')
      return
    }
    setStartAllBusy(true)
    let ok = 0
    let fail = 0
    for (const r of normal) {
      try {
        await tgApi.updateAccount(r.id, {
          tenant_id: r.tenant_id,
          project_id: r.project_id,
          desired_status: 'running',
          observed_status: r.observed_status,
        })
        ok++
      } catch {
        fail++
      }
    }
    setStartAllBusy(false)
    toast.success(`已下发启动 ${ok} 个账号${fail ? `,${fail} 个失败` : ''}(已自动跳过死号)`)
    load()
  }

  async function loginSend() {
    if (!lf.phone.trim() || !lf.api_id.trim() || !lf.api_hash.trim()) {
      toast.warning('手机号、api_id、api_hash 必填')
      return
    }
    setLoginBusy(true)
    try {
      const ws = await tgApi.ensureWorkspace()
      const r = await tgApi.loginStart({
        tenant_id: ws.tenant_id,
        project_id: ws.project_id,
        phone: lf.phone.trim(),
        api_id: Number(lf.api_id.trim()),
        api_hash: lf.api_hash.trim(),
      })
      setLoginId(r.login_id)
      setLoginStep('code')
      toast.success('验证码已发送,去 Telegram 查看')
    } catch (e: any) {
      toast.error(e?.detail || '发送失败')
    } finally {
      setLoginBusy(false)
    }
  }

  async function loginSubmit() {
    if (!lf.code.trim()) {
      toast.warning('请输入验证码')
      return
    }
    setLoginBusy(true)
    try {
      const r = await tgApi.loginComplete({
        login_id: loginId,
        code: lf.code.trim(),
        password: lf.password || undefined,
      })
      if (r.need_password) {
        setNeedPwd(true)
        toast.warning('该账号开启了两步验证,请输入密码再提交')
        return
      }
      toast.success(`登录成功${r.username ? ` @${r.username}` : ''},账号已创建`)
      setLoginOpen(false)
      setLoginStep('form')
      setLf({ phone: '', api_id: '', api_hash: '', code: '', password: '' })
      setNeedPwd(false)
      load()
    } catch (e: any) {
      toast.error(e?.detail || '登录失败')
    } finally {
      setLoginBusy(false)
    }
  }

  async function doImport() {
    if (!file) {
      toast.warning('请选择 zip 文件')
      return
    }
    setImporting(true)
    try {
      const ws = await tgApi.ensureWorkspace()
      await tgApi.importAccounts(ws.tenant_id, ws.project_id, file)
      toast.success('导入完成,去"Session 导入"页看分级结果')
      setOpen(false)
      setFile(null)
      load()
    } catch (e: any) {
      toast.error(e?.detail || '导入失败')
    } finally {
      setImporting(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">TG 账号</h2>
        <div className="flex gap-2">
          <Button variant="outline" onClick={startAll} disabled={startAllBusy}>
            <Play className="h-4 w-4" /> {startAllBusy ? '启动中…' : '一键启动'}
          </Button>
          <Dialog open={delFrozenOpen} onOpenChange={setDelFrozenOpen}>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Trash2 className="h-4 w-4" /> 清除冻结账号
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>一键删除冻结账号</DialogTitle>
              </DialogHeader>
              <p className="text-sm text-muted-foreground">
                将删除当前 {frozenCount} 个状态为"已冻结"的账号,删除后不可恢复。正常账号不受影响。
              </p>
              <DialogFooter>
                <Button variant="outline" onClick={() => setDelFrozenOpen(false)}>
                  取消
                </Button>
                <Button variant="destructive" onClick={deleteFrozen} disabled={delFrozenBusy || !frozenCount}>
                  {delFrozenBusy ? '删除中…' : `删除 ${frozenCount} 个冻结账号`}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Upload className="h-4 w-4" /> 导入 Session 包
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>批量导入账号包(zip)</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">
                  支持两种 zip:① 协议号包(.session+.json);② tdata 包(直接打包 Telegram 桌面版 tdata 目录)。上传后自动验证并归入账号列表
                </p>
                <div className="flex flex-col gap-1.5">
                  <Label>zip 文件</Label>
                  <Input ref={fileRef} type="file" accept=".zip" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={doImport} disabled={importing}>
                  {importing ? '导入中…' : '上传并验证'}
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Dialog
            open={loginOpen}
            onOpenChange={(v) => {
              setLoginOpen(v)
              if (v) {
                tgApi
                  .apiCredentials()
                  .then((list) => {
                    setCreds(list)
                    if (list.length) pickCred('0')
                    else setCredIdx('manual')
                  })
                  .catch(() => {})
              } else {
                setLoginStep('form')
                setNeedPwd(false)
                setCredIdx('')
              }
            }}
          >
            <DialogTrigger asChild>
              <Button variant="outline">
                <Smartphone className="h-4 w-4" /> 验证码登录
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>验证码登录账号</DialogTitle>
              </DialogHeader>
              {loginStep === 'form' ? (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">
                    输入手机号和你的 api 凭据(my.telegram.org 申请),验证码会发到该号码的 Telegram
                  </p>
                  <div className="flex flex-col gap-1.5">
                    <Label>手机号(带国家码)</Label>
                    <Input placeholder="+86138xxxxxxxx" value={lf.phone} onChange={(e) => setLf({ ...lf, phone: e.target.value })} />
                  </div>
                  {creds.length > 0 && (
                    <div className="flex flex-col gap-1.5">
                      <Label>API 凭据</Label>
                      <Select value={credIdx} onValueChange={pickCred}>
                        <SelectTrigger>
                          <SelectValue placeholder="选择已用过的凭据" />
                        </SelectTrigger>
                        <SelectContent>
                          {creds.map((c, i) => (
                            <SelectItem key={i} value={String(i)}>
                              {`api_id: ${c.api_id} · ${c.account_count || c.phones.length} 个账号`}
                            </SelectItem>
                          ))}
                          <SelectItem value="manual">手动输入新凭据</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                  {(!creds.length || credIdx === 'manual') && (
                    <>
                      <div className="flex flex-col gap-1.5">
                        <Label>api_id</Label>
                        <Input placeholder="数字" value={lf.api_id} onChange={(e) => setLf({ ...lf, api_id: e.target.value })} />
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label>api_hash</Label>
                        <Input placeholder="32 位字符串" value={lf.api_hash} onChange={(e) => setLf({ ...lf, api_hash: e.target.value })} />
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <div className="flex flex-col gap-3">
                  <p className="text-sm text-muted-foreground">验证码已发到 {lf.phone} 的 Telegram,10 分钟内有效</p>
                  <div className="flex flex-col gap-1.5">
                    <Label>验证码</Label>
                    <Input placeholder="12345" value={lf.code} onChange={(e) => setLf({ ...lf, code: e.target.value })} />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>两步验证密码{needPwd ? '(必填)' : '(可选)'}</Label>
                    <Input type="password" value={lf.password} onChange={(e) => setLf({ ...lf, password: e.target.value })} />
                  </div>
                </div>
              )}
              <DialogFooter>
                <Button variant="outline" onClick={() => setLoginOpen(false)}>
                  取消
                </Button>
                {loginStep === 'form' ? (
                  <Button onClick={loginSend} disabled={loginBusy}>
                    {loginBusy ? '发送中…' : '发送验证码'}
                  </Button>
                ) : (
                  <Button onClick={loginSubmit} disabled={loginBusy}>
                    {loginBusy ? '登录中…' : '登录'}
                  </Button>
                )}
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
              <TableHead>TG UID</TableHead>
              <TableHead>手机号</TableHead>
              <TableHead>用户名</TableHead>
              <TableHead>期望</TableHead>
              <TableHead>实际</TableHead>
              <TableHead>备注</TableHead>
              <TableHead className="w-44">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell className="font-mono text-xs">{r.telegram_user_id ?? '-'}</TableCell>
                <TableCell>{r.phone || '-'}</TableCell>
                <TableCell>{r.username ? `@${r.username}` : '-'}</TableCell>
                <TableCell>
                  <Badge variant={r.desired_status === 'running' ? 'success' : 'secondary'}>{r.desired_status === 'running' ? '运行' : '停止'}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant[r.observed_status] || 'secondary'}>{statusLabel[r.observed_status] || r.observed_status}</Badge>
                  {r.last_error && (
                    <div className="mt-1 max-w-56 truncate text-xs text-destructive" title={r.last_error}>
                      {r.last_error}
                    </div>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{r.remark || '-'}</TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    {r.desired_status !== 'running' ? (
                      <Button size="sm" onClick={() => setDesired(r, 'running')}>
                        启动
                      </Button>
                    ) : (
                      <Button size="sm" variant="outline" onClick={() => setDesired(r, 'stopped')}>
                        停止
                      </Button>
                    )}
                    <Button size="sm" variant="outline" onClick={() => syncChats(r)}>
                      同步群
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                  暂无账号,点右上"导入 Session 包"开始
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
