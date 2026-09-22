import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type DeliveryJob } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const statusVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  succeeded: 'success',
  ready: 'default',
  in_flight: 'warning',
  retry_scheduled: 'warning',
  gated_approval: 'warning',
  failed_permanent: 'destructive',
  dead_letter: 'destructive',
  cancelled: 'secondary',
}
const STATUS_OPTS = ['ready', 'in_flight', 'retry_scheduled', 'gated_approval', 'succeeded', 'failed_permanent', 'dead_letter', 'cancelled']

export default function DeliveriesPage() {
  const [rows, setRows] = useState<DeliveryJob[]>([])
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<DeliveryJob | null>(null)
  const [open, setOpen] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setRows(await tgApi.deliveries(status ? { status } : {}))
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [status])

  async function act(r: DeliveryJob, kind: 'retry' | 'cancel') {
    try {
      await (kind === 'retry' ? tgApi.retryDelivery(r.id) : tgApi.cancelDelivery(r.id))
      toast.success('已执行')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
    }
  }

  async function openDetail(id: string) {
    try {
      setDetail(await tgApi.delivery(id))
      setOpen(true)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">投递任务</h2>
        <div className="flex gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-44">
              <SelectValue placeholder="按状态筛选" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTS.map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {status && (
            <Button variant="ghost" onClick={() => setStatus('')}>
              清除
            </Button>
          )}
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
        </div>
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任务</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>源(群:消息)</TableHead>
              <TableHead>目标群</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>尝试</TableHead>
              <TableHead>错误</TableHead>
              <TableHead className="w-52">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}</TableCell>
                <TableCell>{r.kind}</TableCell>
                <TableCell className="font-mono text-xs">
                  {r.source_chat_id}:{r.source_message_id}
                </TableCell>
                <TableCell className="font-mono text-xs">{r.target_chat_id}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant[r.status] || 'secondary'}>{r.status}</Badge>
                </TableCell>
                <TableCell>{r.attempt_count}</TableCell>
                <TableCell className="text-xs text-muted-foreground">{r.last_error_class || '-'}</TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    <Button size="sm" variant="outline" onClick={() => openDetail(r.id)}>
                      明细
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!['failed_permanent', 'dead_letter', 'cancelled'].includes(r.status)}
                      onClick={() => act(r, 'retry')}
                    >
                      重试
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={['succeeded', 'cancelled', 'dead_letter'].includes(r.status)}
                      onClick={() => act(r, 'cancel')}
                    >
                      取消
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                  暂无投递记录
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>投递明细</DialogTitle>
          </DialogHeader>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div className="text-muted-foreground">job: {detail?.id}</div>
            <div className="text-muted-foreground">
              规则: {detail?.rule_id} v{detail?.rule_version}
            </div>
          </div>
          <div className="max-h-72 overflow-y-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>开始</TableHead>
                  <TableHead>结果</TableHead>
                  <TableHead>错误分类</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail?.attempts || []).map((a) => (
                  <TableRow key={a.attempt_no}>
                    <TableCell>{a.attempt_no}</TableCell>
                    <TableCell className="text-muted-foreground">{a.started_at?.slice(0, 19).replace('T', ' ')}</TableCell>
                    <TableCell>
                      <Badge variant={a.result_status === 'success' ? 'success' : a.result_status ? 'destructive' : 'secondary'}>
                        {a.result_status || '进行中'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{a.error_class || '-'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
