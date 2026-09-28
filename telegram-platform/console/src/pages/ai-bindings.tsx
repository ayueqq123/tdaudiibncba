import { useEffect, useState } from 'react'
import { Pencil, Plus, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type AiBinding, type AiGroupPolicy, type TgAccount } from '@/lib/api'
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
  account_ids: string[]
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
  account_ids: [],
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

interface GroupRow {
  tenant_id: number
  project_id: number
  chat_id: number
  topic_id: number | null
  bindings: AiBinding[]
}

interface PolicyForm {
  reply_min: string
  reply_max: string
  account_cooldown_s: string
  account_hourly_max: string
  stale_max_messages: string
}

const POLICY_DEFAULT = { reply_min: 1, reply_max: 1, account_cooldown_s: 60, account_hourly_max: 20, stale_max_messages: 10 }

const groupKey = (tenant: number, project: number, chat: number, topic: number | null) =>
  `${tenant}:${project}:${chat}:${topic ?? ''}`

export default function AiBindingsPage() {
  const [rows, setRows] = useState<AiBinding[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<FormState>(EMPTY)
  const [saving, setSaving] = useState(false)
  const [policies, setPolicies] = useState<AiGroupPolicy[]>([])
  const [editGroup, setEditGroup] = useState<GroupRow | null>(null)
  const [pform, setPform] = useState<PolicyForm | null>(null)

  const accLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return a ? `@${a.username || a.phone || a.telegram_user_id || id}` : `#${id}`
  }

  const load = async () => {
    setLoading(true)
    try {
      const [b, a, p] = await Promise.all([tgApi.aiBindings(), tgApi.accounts(), tgApi.aiGroupPolicies()])
      setRows(b)
      setAccounts(a)
      setPolicies(p)
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
    if (!form.account_ids.length || !form.chat_id.trim()) {
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
      let ok = 0
      const failed: string[] = []
      for (const id of form.account_ids) {
        try {
          await tgApi.createAiBinding({
            tenant_id: ws.tenant_id,
            project_id: ws.project_id,
            account_id: Number(id),
            engine: 'openai',
            chat_id: form.chat_id.trim(),
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
          ok++
        } catch (e) {
          const acc = accounts.find((a) => a.id === Number(id))
          failed.push(`${acc ? `@${acc.username || acc.phone || acc.id}` : id}: ${e instanceof Error ? e.message : '失败'}`)
        }
      }
      if (failed.length) {
        toast.warning(`成功 ${ok} 个,失败 ${failed.length} 个:${failed.join(';')}`)
      } else {
        toast.success(`已创建 ${ok} 个绑定,群里来消息会自动生成回复进审批`)
      }
      if (ok) {
        setOpen(false)
        setForm(EMPTY)
      }
      void load()
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

  const groups: GroupRow[] = []
  for (const b of rows) {
    if (b.engine !== 'openai' || b.chat_id == null) continue
    const k = groupKey(b.tenant_id, b.project_id, b.chat_id, b.topic_id)
    const g = groups.find((x) => groupKey(x.tenant_id, x.project_id, x.chat_id, x.topic_id) === k)
    if (g) g.bindings.push(b)
    else groups.push({ tenant_id: b.tenant_id, project_id: b.project_id, chat_id: b.chat_id, topic_id: b.topic_id, bindings: [b] })
  }
  const policyOf = (g: GroupRow) =>
    policies.find((p) => groupKey(p.tenant_id, p.project_id, p.chat_id, p.topic_id) === groupKey(g.tenant_id, g.project_id, g.chat_id, g.topic_id)) ??
    POLICY_DEFAULT

  const openPolicy = (g: GroupRow) => {
    const p = policyOf(g)
    setEditGroup(g)
    setPform({
      reply_min: String(p.reply_min),
      reply_max: String(p.reply_max),
      account_cooldown_s: String(p.account_cooldown_s),
      account_hourly_max: String(p.account_hourly_max),
      stale_max_messages: String(p.stale_max_messages),
    })
  }

  const savePolicy = async () => {
    if (!editGroup || !pform) return
    const reply_min = Number(pform.reply_min) || 1
    const reply_max = Number(pform.reply_max) || 1
    if (reply_max < reply_min) {
      toast.error('最多号数不能小于最少号数')
      return
    }
    setSaving(true)
    try {
      await tgApi.saveAiGroupPolicy({
        tenant_id: editGroup.tenant_id,
        project_id: editGroup.project_id,
        chat_id: editGroup.chat_id,
        topic_id: editGroup.topic_id,
        reply_min,
        reply_max,
        account_cooldown_s: Number(pform.account_cooldown_s) || 0,
        account_hourly_max: Number(pform.account_hourly_max) || 0,
        stale_max_messages: Number(pform.stale_max_messages) || 0,
      })
      toast.success('群策略已保存,下一条群消息起生效')
      setEditGroup(null)
      void load()
    } catch (e) {
      toast.error(e instanceof Error ? e.message : '保存失败')
    } finally {
      setSaving(false)
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

      <div>
        <h2 className="text-base font-semibold">群策略</h2>
        <p className="text-sm text-muted-foreground">
          同一个群里多个号时:每条群消息只决策一次,按「接话号数」随机挑几个号同时回复(被 @ 的号必回);每个号有冷却和每小时上限
        </p>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>群</TableHead>
                  <TableHead>绑定的号</TableHead>
                  <TableHead>每条消息接话号数</TableHead>
                  <TableHead>每号冷却 / 每小时上限</TableHead>
                  <TableHead>过期作废</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {groups.map((g) => {
                  const p = policyOf(g)
                  return (
                    <TableRow key={groupKey(g.tenant_id, g.project_id, g.chat_id, g.topic_id)}>
                      <TableCell className="font-mono text-xs">
                        {g.chat_id}
                        {g.topic_id != null && <div className="text-muted-foreground">话题 {g.topic_id}</div>}
                      </TableCell>
                      <TableCell className="text-xs">
                        {g.bindings.map((b) => accLabel(b.account_id)).join('、')}
                        <div className="text-muted-foreground">
                          运行中 {g.bindings.filter((b) => b.status === 'active').length} / {g.bindings.length}
                        </div>
                      </TableCell>
                      <TableCell>
                        {p.reply_min === p.reply_max ? `${p.reply_min} 个号` : `${p.reply_min}-${p.reply_max} 个号(随机)`}
                      </TableCell>
                      <TableCell className="text-xs">
                        {p.account_cooldown_s > 0 ? `${p.account_cooldown_s}s` : '不冷却'} /{' '}
                        {p.account_hourly_max > 0 ? `${p.account_hourly_max} 条` : '不限'}
                      </TableCell>
                      <TableCell className="text-xs">
                        {p.stale_max_messages > 0 ? `新增 ≥${p.stale_max_messages} 条不发` : '不检查'}
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => openPolicy(g)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  )
                })}
                {groups.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-8 text-center text-muted-foreground">
                      建好炒群绑定后,这里会按群列出策略
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={editGroup != null} onOpenChange={(v) => !v && setEditGroup(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>群策略 · {editGroup?.chat_id}</DialogTitle>
          </DialogHeader>
          {pform && (
            <div className="space-y-3">
              <div>
                <Label>每条消息接话号数(并发区间)</Label>
                <div className="flex items-center gap-2">
                  <Input type="number" min={1} max={20} value={pform.reply_min}
                    onChange={(e) => setPform({ ...pform, reply_min: e.target.value })} />
                  <span className="text-muted-foreground">至</span>
                  <Input type="number" min={1} max={20} value={pform.reply_max}
                    onChange={(e) => setPform({ ...pform, reply_max: e.target.value })} />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">
                  每条消息在区间内随机取一个数,从能发言的号里随机挑这么多个同时回复(各自按发言延迟错开);能发言的号不够时有几个用几个。被 @ 的号一定回
                </p>
              </div>
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <Label>每号冷却(秒,0=不冷却)</Label>
                  <Input type="number" min={0} max={86400} value={pform.account_cooldown_s}
                    onChange={(e) => setPform({ ...pform, account_cooldown_s: e.target.value })} />
                </div>
                <div>
                  <Label>每号每小时上限(条,0=不限)</Label>
                  <Input type="number" min={0} max={1000} value={pform.account_hourly_max}
                    onChange={(e) => setPform({ ...pform, account_hourly_max: e.target.value })} />
                </div>
              </div>
              <div>
                <Label>过期作废(条,0=不检查)</Label>
                <Input type="number" min={0} max={100} value={pform.stale_max_messages}
                  onChange={(e) => setPform({ ...pform, stale_max_messages: e.target.value })} />
                <p className="mt-1 text-xs text-muted-foreground">
                  发言延迟到点时,如果群里在这条消息之后已经又刷了这么多条,这次回复就不发了,免得答非所问
                </p>
              </div>
              <Button className="w-full" onClick={() => void savePolicy()} disabled={saving}>
                {saving ? '保存中…' : '保存'}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建炒群绑定</DialogTitle>
          </DialogHeader>
          <div className="space-y-3">
            <div>
              <Label>发言账号(可多选,每个号建一条绑定)</Label>
              <div className="max-h-40 overflow-y-auto rounded-md border p-1">
                {accounts.map((a) => {
                  const id = String(a.id)
                  const checked = form.account_ids.includes(id)
                  return (
                    <label key={a.id} className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() =>
                          setForm({
                            ...form,
                            account_ids: checked ? form.account_ids.filter((x) => x !== id) : [...form.account_ids, id],
                          })
                        }
                      />
                      @{a.username || a.phone || a.telegram_user_id || a.id}
                    </label>
                  )
                })}
                {!accounts.length && <p className="px-2 py-1.5 text-sm text-muted-foreground">暂无账号</p>}
              </div>
              {form.account_ids.length > 0 && (
                <p className="mt-1 text-xs text-muted-foreground">已选 {form.account_ids.length} 个账号</p>
              )}
            </div>
            <div>
              <Label>群(填 chat_id 或 t.me 群链接)</Label>
              <Input
                value={form.chat_id}
                onChange={(e) => setForm({ ...form, chat_id: e.target.value })}
                placeholder="-1002822138285 或 https://t.me/xxx"
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
              <Label>上下文条数(0-100;生成时带群里最近 N 条消息)</Label>
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
