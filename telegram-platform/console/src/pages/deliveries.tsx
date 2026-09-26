import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, RefreshCw } from 'lucide-react'
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
const STATUS_LABELS: Record<string, string> = {
  ready: '待发送',
  in_flight: '发送中',
  retry_scheduled: '等待重试',
  gated_approval: '等待审批',
  succeeded: '已送达',
  failed_permanent: '发送失败',
  dead_letter: '已放弃',
  cancelled: '已取消',
}
const KIND_LABELS: Record<string, string> = {
  create: '新消息搬运',
  edit: '编辑同步',
  delete: '删除同步',
  send_reply: 'AI 回复',
}
const statusLabel = (s: string) => STATUS_LABELS[s] || s
const kindLabel = (s: string) => KIND_LABELS[s] || s

const PAGE_SIZE = 20

/** UTC ISO → 北京时间(UTC+8) 显示 */
function fmtTs(s?: string | null) {
  if (!s) return '-'
  const d = new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z')
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  const bj = new Date(d.getTime() + 8 * 3600 * 1000)
  return `${bj.getUTCFullYear()}-${pad(bj.getUTCMonth() + 1)}-${pad(bj.getUTCDate())} ${pad(bj.getUTCHours())}:${pad(bj.getUTCMinutes())}:${pad(bj.getUTCSeconds())}`
}

export default function DeliveriesPage() {
  const [rows, setRows] = useState<DeliveryJob[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [status, setStatus] = useState('')
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<DeliveryJob | null>(null)
  const [open, setOpen] = useState(false)
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  async function load() {
    setLoading(true)
    try {
      const res = await tgApi.deliveries({ ...(status ? { status } : {}), page, size: PAGE_SIZE })
      setRows(res.items)
      setTotal(res.total)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [status, page])

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
          <Select
            value={status}
            onValueChange={(v) => {
              setStatus(v)
              setPage(1)
            }}
          >
            <SelectTrigger className="w-44">
              <SelectValue placeholder="按状态筛选" />
            </SelectTrigger>
            <SelectContent>
              {STATUS_OPTS.map((s) => (
                <SelectItem key={s} value={s}>
                  {statusLabel(s)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {status && (
            <Button
              variant="ghost"
              onClick={() => {
                setStatus('')
                setPage(1)
              }}
            >
              清除
            </Button>
          )}
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
        </div>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>任务</TableHead>
              <TableHead>账号</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>源(群:消息)</TableHead>
              <TableHead>目标群</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>尝试</TableHead>
              <TableHead>创建时间</TableHead>
              <TableHead>错误</TableHead>
              <TableHead className="w-52">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell className="font-mono text-xs">{r.id.slice(0, 8)}</TableCell>
                <TableCell className="whitespace-nowrap text-xs">{r.account_label || r.account_id?.slice(0, 8) || '-'}</TableCell>
                <TableCell className="whitespace-nowrap">{kindLabel(r.kind)}</TableCell>
                <TableCell className="font-mono text-xs">
                  {r.source_chat_id}:{r.source_message_id}
                </TableCell>
                <TableCell className="font-mono text-xs">{r.target_chat_id}</TableCell>
                <TableCell>
                  <Badge variant={statusVariant[r.status] || 'secondary'}>{statusLabel(r.status)}</Badge>
                </TableCell>
                <TableCell>{r.attempt_count}</TableCell>
                <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{fmtTs(r.created_at)}</TableCell>
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
                <TableCell colSpan={10} className="py-8 text-center text-muted-foreground">
                  暂无投递记录
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      <div className="mt-3 flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          共 {total} 条 · 第 {page}/{totalPages} 页
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1 || loading} onClick={() => setPage((p) => p - 1)}>
            <ChevronLeft className="h-4 w-4" /> 上一页
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页 <ChevronRight className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>投递明细</DialogTitle>
          </DialogHeader>
          {detail && (
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-sm">
              <div>
                <span className="text-muted-foreground">任务 ID:</span> <span className="font-mono text-xs">{detail.id}</span>
              </div>
              <div>
                <span className="text-muted-foreground">账号:</span> {detail.account_label || detail.account_id}
              </div>
              <div>
                <span className="text-muted-foreground">类型:</span> {kindLabel(detail.kind)} · {detail.mode === 'forward' ? '官方转发' : '复制重发'}
                {detail.requires_approval ? ' · 需审批' : ''}
              </div>
              <div>
                <span className="text-muted-foreground">规则:</span> <span className="font-mono text-xs">{detail.rule_id.slice(0, 8)}</span> v{detail.rule_version}
              </div>
              <div>
                <span className="text-muted-foreground">源:</span> <span className="font-mono text-xs">{detail.source_chat_id}:{detail.source_message_id}</span>
              </div>
              <div>
                <span className="text-muted-foreground">目标:</span>{' '}
                <span className="font-mono text-xs">
                  {detail.target_chat_id}
                  {detail.target_topic_id ? ` 话题${detail.target_topic_id}` : ''}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">状态:</span> {statusLabel(detail.status)} · 尝试 {detail.attempt_count} 次
              </div>
              <div>
                <span className="text-muted-foreground">最近错误:</span> {detail.last_error_class || '-'}
              </div>
              <div>
                <span className="text-muted-foreground">创建:</span> {fmtTs(detail.created_at)}
              </div>
              <div>
                <span className="text-muted-foreground">更新:</span> {fmtTs(detail.updated_at)}
              </div>
              {detail.next_attempt_at && (
                <div>
                  <span className="text-muted-foreground">下次执行:</span> {fmtTs(detail.next_attempt_at)}
                </div>
              )}
              {detail.flood_wait_until && (
                <div>
                  <span className="text-muted-foreground">限流至:</span> {fmtTs(detail.flood_wait_until)}
                </div>
              )}
              <div className="col-span-2">
                <span className="text-muted-foreground">幂等键:</span> <span className="font-mono text-xs">{detail.idempotency_key}</span>
              </div>
            </div>
          )}
          <div className="mt-2 text-sm font-medium">发送尝试记录</div>
          <div className="max-h-72 overflow-y-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>#</TableHead>
                  <TableHead>开始时间</TableHead>
                  <TableHead>结束时间</TableHead>
                  <TableHead>结果</TableHead>
                  <TableHead>错误分类</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail?.attempts || []).map((a) => (
                  <TableRow key={a.attempt_no}>
                    <TableCell>{a.attempt_no}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{fmtTs(a.started_at)}</TableCell>
                    <TableCell className="whitespace-nowrap text-muted-foreground">{fmtTs(a.finished_at)}</TableCell>
                    <TableCell>
                      <Badge variant={a.result_status === 'success' ? 'success' : a.result_status ? 'destructive' : 'secondary'}>
                        {a.result_status === 'success' ? '成功' : a.result_status || '进行中'}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{a.error_class || '-'}</TableCell>
                  </TableRow>
                ))}
                {!(detail?.attempts || []).length && (
                  <TableRow>
                    <TableCell colSpan={5} className="py-4 text-center text-muted-foreground">
                      还没有尝试记录
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
