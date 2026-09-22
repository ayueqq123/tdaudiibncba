import { useEffect, useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type ImportBatch } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const gradeVariant: Record<string, 'success' | 'warning' | 'destructive' | 'default' | 'secondary'> = {
  verified: 'success',
  unverified: 'warning',
  duplicate: 'secondary',
  invalid: 'destructive',
  dead: 'destructive',
}

export default function ImportsPage() {
  const [rows, setRows] = useState<ImportBatch[]>([])
  const [loading, setLoading] = useState(false)
  const [detail, setDetail] = useState<ImportBatch | null>(null)
  const [open, setOpen] = useState(false)

  async function load() {
    setLoading(true)
    try {
      setRows(await tgApi.imports())
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function openDetail(id: number) {
    try {
      const d = await tgApi.importDetail(id)
      setDetail(d)
      setOpen(true)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    }
  }

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">Session 导入批次</h2>
        <Button variant="outline" onClick={load} disabled={loading}>
          <RefreshCw className="h-4 w-4" /> 刷新
        </Button>
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>批次</TableHead>
              <TableHead>总数</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>时间</TableHead>
              <TableHead className="w-24">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>#{r.id}</TableCell>
                <TableCell>{r.total ?? '-'}</TableCell>
                <TableCell>
                  <Badge variant="secondary">{r.status}</Badge>
                </TableCell>
                <TableCell className="text-muted-foreground">{r.created_time?.slice(0, 19).replace('T', ' ')}</TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" onClick={() => openDetail(r.id)}>
                    明细
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  暂无导入记录
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>批次 #{detail?.id} 明细</DialogTitle>
          </DialogHeader>
          <div className="max-h-96 overflow-y-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>手机号</TableHead>
                  <TableHead>TG UID</TableHead>
                  <TableHead>分级</TableHead>
                  <TableHead>原因</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(detail?.results || []).map((it, i) => (
                  <TableRow key={i}>
                    <TableCell>{it.phone || '-'}</TableCell>
                    <TableCell className="font-mono text-xs">{it.telegram_user_id ?? '-'}</TableCell>
                    <TableCell>
                      <Badge variant={gradeVariant[it.grade] || 'secondary'}>{it.grade}</Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{it.reason || '-'}</TableCell>
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
