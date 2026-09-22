import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type TgAccount, type Tenant, type Project } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const statusVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  running: 'success',
  imported_quarantine: 'warning',
  imported_verified: 'default',
  auth_dead: 'destructive',
  error: 'destructive',
}

export default function AccountsPage() {
  const [rows, setRows] = useState<TgAccount[]>([])
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [imp, setImp] = useState<{ tenant: string; project: string; file: File | null }>({ tenant: '', project: '', file: null })
  const [importing, setImporting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  async function load() {
    setLoading(true)
    try {
      const [acc, ten, proj] = await Promise.all([tgApi.accounts(), tgApi.tenants(), tgApi.projects()])
      setRows(acc)
      setTenants(ten)
      setProjects(proj)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  const projName = (id: number) => projects.find((p) => p.id === id)?.name ?? `#${id}`

  async function setDesired(r: TgAccount, status: string) {
    try {
      await tgApi.updateAccount(r.id, {
        tenant_id: r.tenant_id,
        project_id: r.project_id,
        desired_status: status,
        observed_status: r.observed_status,
      })
      toast.success(status === 'running' ? '已下发启动' : '已下发停止')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
    }
  }

  async function doImport() {
    if (!imp.tenant || !imp.project || !imp.file) {
      toast.warning('请选择用户、项目和 zip 文件')
      return
    }
    setImporting(true)
    try {
      await tgApi.importAccounts(Number(imp.tenant), Number(imp.project), imp.file)
      toast.success('导入完成,去"Session 导入"页看分级结果')
      setOpen(false)
      setImp({ tenant: '', project: '', file: null })
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
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Upload className="h-4 w-4" /> 导入 Session 包
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>批量导入 Session 包(zip)</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>用户(租户)</Label>
                  <Select value={imp.tenant} onValueChange={(v) => setImp({ ...imp, tenant: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择用户" />
                    </SelectTrigger>
                    <SelectContent>
                      {tenants.map((t) => (
                        <SelectItem key={t.id} value={String(t.id)}>
                          {t.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>项目</Label>
                  <Select value={imp.project} onValueChange={(v) => setImp({ ...imp, project: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择项目" />
                    </SelectTrigger>
                    <SelectContent>
                      {projects
                        .filter((p) => !imp.tenant || p.tenant_id === Number(imp.tenant))
                        .map((p) => (
                          <SelectItem key={p.id} value={String(p.id)}>
                            {p.name}
                          </SelectItem>
                        ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>zip 文件</Label>
                  <Input ref={fileRef} type="file" accept=".zip" onChange={(e) => setImp({ ...imp, file: e.target.files?.[0] || null })} />
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
              <TableHead>项目</TableHead>
              <TableHead>期望</TableHead>
              <TableHead>实际</TableHead>
              <TableHead>备注</TableHead>
              <TableHead className="w-28">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell className="font-mono text-xs">{r.telegram_user_id ?? '-'}</TableCell>
                <TableCell>{r.phone || '-'}</TableCell>
                <TableCell>{projName(r.project_id)}</TableCell>
                <TableCell>
                  <Badge variant={r.desired_status === 'running' ? 'success' : 'secondary'}>{r.desired_status}</Badge>
                </TableCell>
                <TableCell>
                  <Badge variant={statusVariant[r.observed_status] || 'secondary'}>{r.observed_status}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{r.remark || '-'}</TableCell>
                <TableCell>
                  {r.desired_status !== 'running' ? (
                    <Button size="sm" onClick={() => setDesired(r, 'running')}>
                      启动
                    </Button>
                  ) : (
                    <Button size="sm" variant="outline" onClick={() => setDesired(r, 'stopped')}>
                      停止
                    </Button>
                  )}
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
