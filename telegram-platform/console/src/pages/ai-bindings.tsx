import { useEffect, useState } from 'react'
import { Plus, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type AiBinding, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

interface FormState {
  account_id: string
  chat_id: string
  persona: string
  base_url: string
  provider_model: string
  provider_key: string
  speak_policy: string
  reply_delay_s: string
  random_prob: string
  context_max: string
  remark: string
}

const EMPTY: FormState = {
  account_id: '',
  chat_id: '',
  persona: '',
  base_url: 'https://api.deepseek.com/v1',
  provider_model: 'deepseek-chat',
  provider_key: '',
  speak_policy: 'all',
  reply_delay_s: '10',
  random_prob: '30',
  context_max: '12',
  remark: '',
}

export default function AiBindingsPage() {
  const [rows, setRows] = useState<AiBinding[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [saving, setSaving] = useState(false)

  const accLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return a ? `@${a.username || a.phone || a.telegram_user_id || id}` : `#${id}`
  }

  const load = async () => {
    setLoading(true)
    try {
      const [b, a] = await Promise.all([tgApi.aiBindings(), tgApi.accounts()])
      setRows(b)
      setAccounts(a)
    } catch {
      toast.error('加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const doCreate = async () => {
    if (!form.account_id || !form.chat_id.trim()) {
      toast.error('账号和群 ID 必填')
      return
    }
    if (!form.provider_key.trim()) {
      toast.error('请填模型 API Key')
      return
    }
    setSaving(true)
    try {
      const ws = await tgApi.ensureWorkspace()
      await tgApi.createAiBinding({
        tenant_id: ws.tenant_id,
        project_id: ws.project_id,
        account_id: Number(form.account_id),
        engine: 'openai',
        chat_id: Number(form.chat_id.trim()),
        persona: form.persona.trim() || null,
        base_url: form.base_url.trim(),
        provider_model: form.provider_model.trim(),
        provider_key: form.provider_key.trim(),
        speak_policy: form.speak_policy,
        reply_delay_s: Number(form.reply_delay_s) || 0,
        random_prob: Number(form.random_prob) || 30,
        context_max_messages: Number(form.context_max) || 12,
        remark: form.remark.trim() || null,
      })
      toast.success('已创建,群里来消息会自动生成回复进审批')
      setOpen(false)
      setForm(EMPTY)
      void load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '创建失败')
    } finally {
      setSaving(false)
    }
  }

  const doToggle = async (b: AiBinding) => {
    const status = b.status === 'active' ? 'paused' : 'active'
    setRows((prev) => prev.map((x) => (x.id === b.id ? { ...x, status } : x)))
    try {
      await tgApi.updateAiBinding(b.id, { status })
    } catch {
      toast.error('操作失败')
    } finally {
      void load()
    }
  }

  const doDelete = async (b: AiBinding) => {
    if (!confirm(`删除绑定 ${accLabel(b.account_id)} / ${b.chat_id}?`)) return
    try {
      await tgApi.deleteAiBinding(b.id)
      void load()
    } catch {
      toast.error('删除失败')
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">炒群配置</h1>
          <p className="text-sm text-muted-foreground">
            绑定的群来消息 → AI 按人设生成回复 → 进「AI 回复审批」,通过才会发出
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
          <Button size="sm" onClick={() => setOpen(true)}>
            <Plus className="mr-1 h-4 w-4" />
            新建绑定
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>账号</TableHead>
                  <TableHead>绑定群</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead>人设</TableHead>
                  <TableHead>发言策略</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((b) => (
                  <TableRow key={b.id}>
                    <TableCell className="whitespace-nowrap">{accLabel(b.account_id)}</TableCell>
                    <TableCell className="font-mono text-xs">{b.chat_id ?? '-'}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {b.provider_model || '-'}
                      <div className="max-w-[180px] truncate text-muted-foreground">{b.base_url}</div>
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground">
                      {b.persona || '默认人设'}
                    </TableCell>
                    <TableCell>
                      {b.speak_policy === 'mention' ? '仅被@时' : b.speak_policy === 'random' ? `随机 ~${b.random_prob ?? 30}%` : '每条消息'}
                      {(b.reply_delay_s ?? 0) > 0 && (
                        <div className="text-xs text-muted-foreground">延迟 ~{b.reply_delay_s}s</div>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <Switch checked={b.status === 'active'} onCheckedChange={() => void doToggle(b)} />
                        <Badge variant={b.status === 'active' ? 'default' : 'secondary'}>
                          {b.status === 'active' ? '运行中' : '已暂停'}
                        </Badge>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      <Button variant="ghost" size="sm" onClick={() => void doDelete(b)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                      {loading ? '加载中…' : '还没有绑定,点「新建绑定」开始'}
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建炒群绑定</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>发言账号</Label>
              <Select value={form.account_id} onValueChange={(v) => setForm({ ...form, account_id: v })}>
                <SelectTrigger>
                  <SelectValue placeholder="选账号" />
                </SelectTrigger>
                <SelectContent>
                  {accounts.map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      @{a.username || a.phone || a.telegram_user_id || a.id}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label>群 ID(填 -100 开头的 chat_id)</Label>
              <Input
                value={form.chat_id}
                onChange={(e) => setForm({ ...form, chat_id: e.target.value })}
                placeholder="-1002822138285"
              />
            </div>
            <div>
              <Label>人设提示词(留空用默认)</Label>
              <Textarea
                value={form.persona}
                onChange={(e) => setForm({ ...form, persona: e.target.value })}
                placeholder="你是群里的老群友,说话简短自然…"
                rows={3}
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <Label>接口地址(OpenAI 兼容)</Label>
                <Input
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  placeholder="https://api.deepseek.com/v1"
                />
              </div>
              <div>
                <Label>模型名</Label>
                <Input
                  value={form.provider_model}
                  onChange={(e) => setForm({ ...form, provider_model: e.target.value })}
                  placeholder="deepseek-chat"
                />
              </div>
            </div>
            <div>
              <Label>API Key(加密存储,不回显)</Label>
              <Input
                type="password"
                value={form.provider_key}
                onChange={(e) => setForm({ ...form, provider_key: e.target.value })}
                placeholder="sk-..."
              />
            </div>
            <div>
              <Label>发言策略</Label>
              <Select value={form.speak_policy} onValueChange={(v) => setForm({ ...form, speak_policy: v })}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">每条消息都接话</SelectItem>
                  <SelectItem value="mention">仅被 @ 时回复</SelectItem>
                  <SelectItem value="random">随机接话(按概率)</SelectItem>
                </SelectContent>
              </Select>
            </div>
            {form.speak_policy === 'random' && (
              <div>
                <Label>发言概率(%,1-100;每条消息按此概率回复)</Label>
                <Input
                  type="number"
                  min={1}
                  max={100}
                  value={form.random_prob}
                  onChange={(e) => setForm({ ...form, random_prob: e.target.value })}
                />
              </div>
            )}
            <div>
              <Label>上下文条数(0-100;生成时带最近 N 条已发送的群聊记录)</Label>
              <Input
                type="number"
                min={0}
                max={100}
                value={form.context_max}
                onChange={(e) => setForm({ ...form, context_max: e.target.value })}
              />
            </div>
            <div>
              <Label>发言延迟(秒,0-300;实际等待 = 该值 ±30%,更像真人)</Label>
              <Input
                type="number"
                min={0}
                max={300}
                value={form.reply_delay_s}
                onChange={(e) => setForm({ ...form, reply_delay_s: e.target.value })}
              />
            </div>
            <div>
              <Label>备注</Label>
              <Input
                value={form.remark}
                onChange={(e) => setForm({ ...form, remark: e.target.value })}
              />
            </div>
            <Button className="w-full" onClick={() => void doCreate()} disabled={saving}>
              {saving ? '创建中…' : '创建'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
