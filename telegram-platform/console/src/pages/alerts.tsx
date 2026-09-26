import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import { CheckCheck, RefreshCw } from 'lucide-react'
import { tgApi, type TgAlert } from '@/lib/api'
import { ackAlerts, isAcked, loadAcks } from '@/lib/alerts'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const CATEGORY: Record<string, string> = {
  account: '账号',
  heartbeat: '心跳',
  route: '路线/进群',
  delivery: '投递失败',
  uncertain: '待确认',
  ai: 'AI 调用',
}

function fmtTs(s?: string | null) {
  if (!s) return '-'
  const d = new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z')
  if (Number.isNaN(d.getTime())) return s
  const pad = (n: number) => String(n).padStart(2, '0')
  const bj = new Date(d.getTime() + 8 * 3600 * 1000)
  return `${bj.getUTCFullYear()}-${pad(bj.getUTCMonth() + 1)}-${pad(bj.getUTCDate())} ${pad(bj.getUTCHours())}:${pad(bj.getUTCMinutes())}`
}

export default function AlertsPage() {
  const [rows, setRows] = useState<TgAlert[]>([])
  const [acks, setAcks] = useState(loadAcks())
  const [loading, setLoading] = useState(false)
  const [state, setState] = useState<'open' | 'done' | 'all'>('open')
  const [cat, setCat] = useState('all')

  async function load() {
    setLoading(true)
    try {
      setRows(await tgApi.alerts())
      setAcks(loadAcks())
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  const shown = useMemo(
    () =>
      rows.filter((a) => {
        const done = isAcked(a, acks)
        if (state === 'open' && done) return false
        if (state === 'done' && !done) return false
        return cat === 'all' || a.category === cat
      }),
    [rows, acks, state, cat],
  )

  function ack(list: TgAlert[]) {
    ackAlerts(list)
    setAcks(loadAcks())
  }

  return (
    <div>
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold">异常告警</h2>
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          汇总账号、进群/路线、投递、AI 调用和 worker 心跳的问题(投递和 AI 统计近 24 小时)。问题解决后会自动消失;标记已处理后,同一问题再次发生会重新出现。
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Select value={state} onValueChange={(v) => setState(v as any)}>
            <SelectTrigger className="w-28">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="open">未处理</SelectItem>
              <SelectItem value="done">已处理</SelectItem>
              <SelectItem value="all">全部</SelectItem>
            </SelectContent>
          </Select>
          <Select value={cat} onValueChange={setCat}>
            <SelectTrigger className="w-32">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">全部类型</SelectItem>
              {Object.entries(CATEGORY).map(([k, v]) => (
                <SelectItem key={k} value={k}>{v}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          {state !== 'done' && shown.some((a) => !isAcked(a, acks)) && (
            <Button variant="outline" onClick={() => ack(shown)}>
              <CheckCheck className="h-4 w-4" /> 全部标记已处理
            </Button>
          )}
        </div>
      </div>
      <div className="overflow-x-auto rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>最近发生(北京时间)</TableHead>
              <TableHead>类型</TableHead>
              <TableHead>问题</TableHead>
              <TableHead>账号</TableHead>
              <TableHead>次数</TableHead>
              <TableHead>状态</TableHead>
              <TableHead>操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((a) => {
              const done = isAcked(a, acks)
              return (
                <TableRow key={a.key}>
                  <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{fmtTs(a.last_at)}</TableCell>
                  <TableCell>
                    <Badge variant={a.level === 'error' ? 'destructive' : 'warning'}>{CATEGORY[a.category] || a.category}</Badge>
                  </TableCell>
                  <TableCell className="min-w-64">
                    <div className="font-medium">{a.title}</div>
                    <div className="break-all text-xs text-muted-foreground">{a.detail}</div>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">{a.account_label}</TableCell>
                  <TableCell>{a.count}</TableCell>
                  <TableCell>
                    <Badge variant={done ? 'secondary' : 'destructive'}>{done ? '已处理' : '未处理'}</Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="outline" asChild>
                        <Link to={a.link}>去处理</Link>
                      </Button>
                      {!done && (
                        <Button size="sm" variant="outline" onClick={() => ack([a])}>
                          标记已处理
                        </Button>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
            {!shown.length && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  {state === 'open' ? '没有未处理的异常,一切正常' : '暂无记录'}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
