import { useEffect, useState } from 'react'
import { RefreshCw, Send } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type RuntimeCommand, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

const CMD_TYPES = ['StartAccount', 'StopAccount', 'ReloadConfig', 'SyncChats', 'ReconcileSource', 'CancelJob', 'PauseAccount', 'ResumeAccount']
const CMD_LABELS: Record<string, string> = {
  StartAccount: '启动账号',
  StopAccount: '停止账号',
  PauseAccount: '暂停账号',
  ResumeAccount: '恢复账号',
  ReloadConfig: '重载配置(刷新规则)',
  SyncChats: '同步群列表',
  ReconcileSource: '校准源会话',
  CancelJob: '取消任务',
}
const cmdLabel = (t: string) => CMD_LABELS[t] || t
const STATUS_LABELS: Record<string, string> = {
  pending: '待执行',
  done: '已完成',
  acked: '已确认',
  rejected: '已拒绝',
  failed: '失败',
  cancelled: '已取消',
}
const RESULT_LABELS: Record<string, string> = {
  rules_refreshed: '规则已刷新',
  dialogs_warmed: '群列表已同步',
  released: '已释放账号',
  already_hosted: '已在运行',
  paused: '已暂停',
  resumed: '已恢复',
  cancelled: '已取消',
  job_not_cancellable: '任务不可取消',
}
const resultLabel = (r?: string | null) => (r ? RESULT_LABELS[r] || r : '-')
const statusLabel = (s: string) => STATUS_LABELS[s] || s
const statusVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  pending: 'warning',
  done: 'success',
  acked: 'success',
  rejected: 'destructive',
  failed: 'destructive',
  cancelled: 'secondary',
}

export default function CommandsPage() {
  const [rows, setRows] = useState<RuntimeCommand[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ account_id: '', command_type: '', payload: '{}' })

  async function load() {
    setLoading(true)
    try {
      const [c, a] = await Promise.all([tgApi.commands(), tgApi.accounts()])
      setRows(c)
      setAccounts(a)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function issue() {
    if (!form.account_id || !form.command_type) {
      toast.warning('账号和命令类型必填')
      return
    }
    let payload = {}
    try {
      payload = JSON.parse(form.payload || '{}')
    } catch {
      toast.warning('payload 不是合法 JSON')
      return
    }
    try {
      await tgApi.issueCommand(+form.account_id, { command_type: form.command_type, payload })
      toast.success('命令已下发')
      setOpen(false)
      load()
    } catch (e: any) {
      toast.error(e?.detail || '下发失败')
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">运行时命令</h2>
        <div className="flex gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Send className="h-4 w-4" /> 下发命令
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>给账号下发运行时命令</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>账号</Label>
                  <Select value={form.account_id} onValueChange={(v) => setForm({ ...form, account_id: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择账号" />
                    </SelectTrigger>
                    <SelectContent>
                      {accounts.map((a) => (
                        <SelectItem key={a.id} value={String(a.id)}>
                          {a.phone || String(a.telegram_user_id || a.id)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>命令类型</Label>
                  <Select value={form.command_type} onValueChange={(v) => setForm({ ...form, command_type: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择命令" />
                    </SelectTrigger>
                    <SelectContent>
                      {CMD_TYPES.map((t) => (
                        <SelectItem key={t} value={t}>
                          {cmdLabel(t)}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>payload(JSON)</Label>
                  <Textarea value={form.payload} onChange={(e) => setForm({ ...form, payload: e.target.value })} rows={4} />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={issue}>下发</Button>
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
              <TableHead>账号</TableHead>
              <TableHead>命令</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>回执</TableHead>
              <TableHead>时间</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell>{r.account_id}</TableCell>
                <TableCell>{cmdLabel(r.type)}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant[r.status] || 'secondary'}>{statusLabel(r.status)}</Badge>
                </TableCell>
                <TableCell className="max-w-xs truncate text-xs text-muted-foreground">{resultLabel(r.result)}</TableCell>
                <TableCell className="text-muted-foreground">{r.created_time?.slice(0, 19).replace('T', ' ')}</TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                  暂无命令
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
