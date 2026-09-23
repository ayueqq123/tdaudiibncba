import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type RuntimeCommand } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

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
  const [loading, setLoading] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setRows(await tgApi.commands())
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">命令记录</h2>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className="h-4 w-4" /> 刷新
        </Button>
      </div>
      <p className="mb-3 text-sm text-muted-foreground">
        控制面下发给 worker 的指令流水,只读;常用操作在"TG 账号"(启停/同步群)和"Clone 规则"(发布自动刷新)页直接点。
      </p>
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
