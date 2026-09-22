import { useEffect, useRef, useState } from 'react'
import { RefreshCw, Upload } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [importing, setImporting] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

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
                <p className="text-sm text-muted-foreground">上传 zip 协议号包,自动验证并归入你的账号列表</p>
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
