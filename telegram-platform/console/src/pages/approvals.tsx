import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type Approval, type ReplyCandidate } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

const statusVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  pending: 'warning',
  approved: 'success',
  rejected: 'destructive',
  expired: 'secondary',
}

export default function ApprovalsPage() {
  const [rows, setRows] = useState<Approval[]>([])
  const [cands, setCands] = useState<Record<number, ReplyCandidate>>({})
  const [status, setStatus] = useState('pending')
  const [loading, setLoading] = useState(false)
  const [cur, setCur] = useState<Approval | null>(null)
  const [reason, setReason] = useState('')
  const [open, setOpen] = useState(false)
  const [acting, setActing] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const [list, candList] = await Promise.all([tgApi.approvals(status ? { status } : {}), tgApi.candidates()])
      setRows(list)
      const map: Record<number, ReplyCandidate> = {}
      for (const c of candList) map[c.id] = c
      setCands(map)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [status])

  async function decide(approve: boolean) {
    if (!cur) return
    if (!approve && !reason.trim()) {
      toast.warning('驳回需要填写理由')
      return
    }
    const c = cands[cur.candidate_id]
    if (!c) {
      toast.error('候选内容缺失,无法审批')
      return
    }
    setActing(true)
    try {
      const payload = {
        candidate_version: c.version,
        content_hash: c.content_hash,
        ...(approve ? {} : { reason: reason.trim() }),
      }
      await (approve ? tgApi.approve(cur.id, payload) : tgApi.reject(cur.id, payload))
      toast.success(approve ? '已通过,回复将自动发出' : '已驳回')
      setOpen(false)
      load()
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
    } finally {
      setActing(false)
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">AI 回复审批</h2>
        <div className="flex gap-2">
          <Select value={status} onValueChange={setStatus}>
            <SelectTrigger className="w-40">
              <SelectValue placeholder="状态" />
            </SelectTrigger>
            <SelectContent>
              {['pending', 'approved', 'rejected', 'expired'].map((s) => (
                <SelectItem key={s} value={s}>
                  {s}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
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
              <TableHead>候选内容</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>过期时间</TableHead>
              <TableHead className="w-24">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => {
              const c = cands[r.candidate_id]
              return (
                <TableRow key={r.id}>
                  <TableCell>{r.id}</TableCell>
                  <TableCell className="max-w-md truncate">{c?.content || `#${r.candidate_id}`}</TableCell>
                  <TableCell>
                    <Badge variant={statusVariant[r.status] || 'secondary'}>{r.status}</Badge>
                  </TableCell>
                  <TableCell className="text-muted-foreground">{r.expires_at?.slice(0, 19).replace('T', ' ')}</TableCell>
                  <TableCell>
                    {r.status === 'pending' && (
                      <Button
                        size="sm"
                        onClick={() => {
                          setCur(r)
                          setReason('')
                          setOpen(true)
                        }}
                      >
                        审批
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              )
            })}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  暂无审批任务
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>审批候选回复</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="rounded-md border bg-muted/40 p-3">
              <p className="whitespace-pre-wrap break-words text-sm">
                {(cur && cands[cur.candidate_id]?.content) || '(候选内容)'}
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>驳回理由(驳回时必填)</Label>
              <Textarea value={reason} onChange={(e) => setReason(e.target.value)} placeholder="通过可不填" />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={() => decide(false)} disabled={acting}>
                驳回
              </Button>
              <Button onClick={() => decide(true)} disabled={acting}>
                {acting ? '处理中…' : '通过并发送'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
