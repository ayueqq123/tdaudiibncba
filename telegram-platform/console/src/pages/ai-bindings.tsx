import { useEffect, useRef, useState } from 'react'
import { ArrowLeft, Pause, Pencil, Play, Plus, RefreshCw, Save, Sparkles, Square, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import {
  tgApi,
  type AiGroup,
  type AiGroupMessage,
  type AiGroupRun,
  type AiMember,
  type AiPersona,
  type AiPrivateReply,
  type AiScript,
  type TgAccount,
} from '@/lib/api'
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

const errMsg = (e: unknown, fallback: string) => (e instanceof Error && e.message ? e.message : fallback)

function fmtTs(s?: string | number | null) {
  if (s === undefined || s === null || s === '') return '-'
  const d =
    typeof s === 'number' ? new Date(s * 1000) : new Date(s.endsWith('Z') || s.includes('+') ? s : s + 'Z')
  if (Number.isNaN(d.getTime())) return String(s)
  const pad = (n: number) => String(n).padStart(2, '0')
  const bj = new Date(d.getTime() + 8 * 3600 * 1000)
  return `${pad(bj.getUTCMonth() + 1)}-${pad(bj.getUTCDate())} ${pad(bj.getUTCHours())}:${pad(bj.getUTCMinutes())}:${pad(bj.getUTCSeconds())}`
}

const accLabel = (a?: TgAccount) => (a ? `@${a.username || a.phone || a.telegram_user_id || a.id}` : '-')

const RUN_STATUS: Record<string, string> = {
  pending: '排队中',
  running: '生成中',
  completed: '已生成',
  failed: '失败/拦截',
  cancelled: '已取消',
  incomplete: '超时',
  stale: '过期作废',
}
const CAND_STATUS: Record<string, string> = {
  pending: '待审批',
  approved: '已通过',
  rejected: '已拒绝',
  sent: '已发送',
  expired: '已过期',
}
const MODE: Record<string, string> = { reply: '接话', warmup: '暖场', script: '剧本' }

function gateReason(err: string | null) {
  if (!err) return ''
  if (err.startsWith('gate:blocked_word')) return `命中黑名单「${err.split(':')[2] ?? ''}」`
  if (err === 'gate:duplicate') return '与近期内容重复'
  if (err === 'gate:too_long') return '超过字数上限'
  if (err === 'gate:empty') return '模型返回空'
  if (err.includes('401') || err.includes('403')) return 'API Key 无效'
  if (err.includes('429')) return '模型限流/余额不足'
  return err.slice(0, 80)
}

// ---------------- 群设置表单 ----------------
interface GroupForm {
  name: string
  chat: string
  join_account_id: string
  topic_id: string
  theme: string
  base_url: string
  provider_model: string
  provider_key: string
  reply_min: string
  reply_max: string
  account_cooldown_s: string
  account_hourly_max: string
  stale_max_messages: string
  context_max_messages: string
  bot_chain_max: string
  active_start_hour: string
  active_end_hour: string
  mention_bypass_hours: boolean
  idle_warmup_min: string
  quote_prob: string
  punct_space_prob: string
  blocked_words: string
  max_reply_chars: string
  auto_approve: boolean
  remark: string
}

const GROUP_DEFAULT: GroupForm = {
  name: '',
  chat: '',
  join_account_id: '',
  topic_id: '',
  theme: '',
  base_url: 'https://api.deepseek.com/v1',
  provider_model: 'deepseek-chat',
  provider_key: '',
  reply_min: '0',
  reply_max: '1',
  account_cooldown_s: '60',
  account_hourly_max: '20',
  stale_max_messages: '10',
  context_max_messages: '12',
  bot_chain_max: '0',
  active_start_hour: '0',
  active_end_hour: '0',
  mention_bypass_hours: true,
  idle_warmup_min: '0',
  quote_prob: '30',
  punct_space_prob: '70',
  blocked_words: '',
  max_reply_chars: '200',
  auto_approve: false,
  remark: '',
}

const toForm = (g: AiGroup): GroupForm => ({
  name: g.name,
  chat: g.chat_ref || String(g.chat_id),
  join_account_id: '',
  topic_id: g.topic_id ? String(g.topic_id) : '',
  theme: g.theme || '',
  base_url: g.base_url,
  provider_model: g.provider_model || '',
  provider_key: '',
  reply_min: String(g.reply_min),
  reply_max: String(g.reply_max),
  account_cooldown_s: String(g.account_cooldown_s),
  account_hourly_max: String(g.account_hourly_max),
  stale_max_messages: String(g.stale_max_messages),
  context_max_messages: String(g.context_max_messages),
  bot_chain_max: String(g.bot_chain_max),
  active_start_hour: String(g.active_start_hour),
  active_end_hour: String(g.active_end_hour),
  mention_bypass_hours: g.mention_bypass_hours,
  idle_warmup_min: String(g.idle_warmup_min),
  quote_prob: String(g.quote_prob),
  punct_space_prob: String(g.punct_space_prob),
  blocked_words: (g.blocked_words || []).join('\n'),
  max_reply_chars: String(g.max_reply_chars),
  auto_approve: g.auto_approve,
  remark: g.remark || '',
})

const num = (s: string, d = 0) => (s.trim() === '' || Number.isNaN(Number(s)) ? d : Number(s))

const formPayload = (f: GroupForm) => ({
  name: f.name.trim(),
  theme: f.theme.trim() || null,
  base_url: f.base_url.trim(),
  provider_model: f.provider_model.trim() || null,
  provider_key: f.provider_key.trim() || null,
  reply_min: num(f.reply_min),
  reply_max: num(f.reply_max, 1),
  account_cooldown_s: num(f.account_cooldown_s),
  account_hourly_max: num(f.account_hourly_max),
  stale_max_messages: num(f.stale_max_messages),
  context_max_messages: num(f.context_max_messages, 12),
  bot_chain_max: num(f.bot_chain_max),
  active_start_hour: num(f.active_start_hour),
  active_end_hour: num(f.active_end_hour),
  mention_bypass_hours: f.mention_bypass_hours,
  idle_warmup_min: num(f.idle_warmup_min),
  quote_prob: num(f.quote_prob),
  punct_space_prob: num(f.punct_space_prob, 70),
  blocked_words: f.blocked_words
    .split(/[\n,，]/)
    .map((w) => w.trim())
    .filter(Boolean),
  max_reply_chars: num(f.max_reply_chars),
  auto_approve: f.auto_approve,
  remark: f.remark.trim() || null,
})

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      {children}
      {hint && <p className="text-[11px] text-muted-foreground">{hint}</p>}
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-3 rounded-md border p-3">
      <div className="text-sm font-medium">{title}</div>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </div>
  )
}

function GroupSettings({
  form,
  setForm,
  creating,
  accounts,
  hasKey,
  scope,
}: {
  form: GroupForm
  setForm: (f: GroupForm) => void
  creating: boolean
  accounts: TgAccount[]
  hasKey: boolean
  scope?: { tenant_id: number; project_id: number } | null
}) {
  const set = (k: keyof GroupForm) => (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
    setForm({ ...form, [k]: e.target.value })
  return (
    <div className="space-y-3">
      <Section title="基本信息">
        <Field label="任务名称">
          <Input value={form.name} onChange={set('name')} placeholder="如:USDT 交流群" />
        </Field>
        <Field label="群(链接 / @用户名 / 数字 ID)" hint={creating ? '填链接需选一个账号去解析并进群' : '群创建后不可修改'}>
          <Input value={form.chat} onChange={set('chat')} disabled={!creating} placeholder="https://t.me/xxx" />
        </Field>
        {creating && (
          <Field label="用于解析/进群的账号">
            <Select value={form.join_account_id} onValueChange={(v) => setForm({ ...form, join_account_id: v })}>
              <SelectTrigger>
                <SelectValue placeholder="填数字 ID 可不选" />
              </SelectTrigger>
              <SelectContent>
                {accounts
                  .filter((a) => !scope || (a.tenant_id === scope.tenant_id && a.project_id === scope.project_id))
                  .map((a) => (
                    <SelectItem key={a.id} value={String(a.id)}>
                      {accLabel(a)}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
          </Field>
        )}
        {creating && (
          <Field label="话题 ID(可选)">
            <Input value={form.topic_id} onChange={set('topic_id')} placeholder="论坛群的话题,不填=全群" />
          </Field>
        )}
        <div className="sm:col-span-2">
          <Field label="群主题 / 背景" hint="所有成员都会知道:这是什么群、聊什么、氛围如何">
            <Textarea rows={3} value={form.theme} onChange={set('theme')} placeholder="USDT 交易群,大家聊行情和出入金,氛围轻松" />
          </Field>
        </div>
      </Section>

      <Section title="模型">
        <Field label="接口地址(OpenAI 兼容)">
          <Input value={form.base_url} onChange={set('base_url')} />
        </Field>
        <Field label="模型名">
          <Input value={form.provider_model} onChange={set('provider_model')} />
        </Field>
        <div className="sm:col-span-2">
          <Field label="API Key" hint={hasKey ? '已保存,留空不更换' : '加密保存,不会回显'}>
            <Input type="password" value={form.provider_key} onChange={set('provider_key')} placeholder={hasKey ? '••••••(已保存)' : 'sk-...'} />
          </Field>
        </div>
      </Section>

      <Section title="发言节奏">
        <Field label="每条消息最少接话号数" hint="0 = 没人想说就不说;≥1 = 至少凑够这么多">
          <Input value={form.reply_min} onChange={set('reply_min')} />
        </Field>
        <Field label="每条消息最多接话号数(并发)" hint="几个号可以同时回同一条消息">
          <Input value={form.reply_max} onChange={set('reply_max')} />
        </Field>
        <Field label="每号冷却(秒)">
          <Input value={form.account_cooldown_s} onChange={set('account_cooldown_s')} />
        </Field>
        <Field label="每号每小时上限(0=不限)">
          <Input value={form.account_hourly_max} onChange={set('account_hourly_max')} />
        </Field>
        <Field label="过期作废(条)" hint="等发言期间群里又刷过这么多条就不发;0=不作废">
          <Input value={form.stale_max_messages} onChange={set('stale_max_messages')} />
        </Field>
        <Field label="上下文条数">
          <Input value={form.context_max_messages} onChange={set('context_max_messages')} />
        </Field>
        <Field label="号与号最多连续接几轮" hint="0 = 自己人发言不触发接话">
          <Input value={form.bot_chain_max} onChange={set('bot_chain_max')} />
        </Field>
        <Field label="标点转空格概率 %" hint="按概率把逗号句号换成空格,越高越像随手打字;0=保留原文">
          <Input value={form.punct_space_prob} onChange={set('punct_space_prob')} />
        </Field>
        <Field label="引用回复概率 %" hint="接话时按概率「回复」原消息">
          <Input value={form.quote_prob} onChange={set('quote_prob')} />
        </Field>
      </Section>

      <Section title="活跃时段与暖场(北京时间)">
        <Field label="开始小时(0-23)" hint="开始=结束 表示全天">
          <Input value={form.active_start_hour} onChange={set('active_start_hour')} />
        </Field>
        <Field label="结束小时(0-23)" hint="可跨夜,如 9 → 1">
          <Input value={form.active_end_hour} onChange={set('active_end_hour')} />
        </Field>
        <div className="flex items-center gap-2">
          <Switch checked={form.mention_bypass_hours} onCheckedChange={(v) => setForm({ ...form, mention_bypass_hours: v })} />
          <span className="text-sm">非活跃时段被 @ / 被回复仍然回</span>
        </div>
        <Field label="冷场暖场(分钟,0=关)" hint="群里这么久没人说话,挑一个号按主题开话题">
          <Input value={form.idle_warmup_min} onChange={set('idle_warmup_min')} />
        </Field>
      </Section>

      <Section title="内容闸门与审批">
        <Field label="关键词黑名单" hint="每行一个;命中就拦截不发">
          <Textarea rows={3} value={form.blocked_words} onChange={set('blocked_words')} placeholder={'微信\n私聊'} />
        </Field>
        <div className="space-y-3">
          <Field label="单条最大字数(0=不限)">
            <Input value={form.max_reply_chars} onChange={set('max_reply_chars')} />
          </Field>
          <div className="flex items-center gap-2">
            <Switch checked={form.auto_approve} onCheckedChange={(v) => setForm({ ...form, auto_approve: v })} />
            <span className="text-sm">自动审批(生成后直接发送)</span>
          </div>
        </div>
      </Section>
      <Field label="备注">
        <Input value={form.remark} onChange={set('remark')} />
      </Field>
    </div>
  )
}

// ---------------- 成员表单 ----------------
interface MemberForm {
  account_id: string
  account_ids: string[]
  role_name: string
  persona: string
  talkativeness: string
  reply_delay_s: string
  provider_model: string
  provider_key: string
  status: string
}
const MEMBER_DEFAULT: MemberForm = {
  account_id: '',
  account_ids: [],
  role_name: '',
  persona: '',
  talkativeness: '30',
  reply_delay_s: '10',
  provider_model: '',
  provider_key: '',
  status: 'active',
}

// ---------------- 页面 ----------------
type Tab = 'settings' | 'members' | 'chat' | 'runs' | 'scripts'
const TABS: { key: Tab; label: string }[] = [
  { key: 'members', label: '成员与人设' },
  { key: 'settings', label: '群设置' },
  { key: 'chat', label: '实时对话' },
  { key: 'runs', label: '发言记录' },
  { key: 'scripts', label: '剧本' },
]

export default function AiBindingsPage() {
  const [groups, setGroups] = useState<AiGroup[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [current, setCurrent] = useState<AiGroup | null>(null)
  const [creating, setCreating] = useState(false)
  const [form, setForm] = useState<GroupForm>(GROUP_DEFAULT)
  const [ws, setWs] = useState<{ tenant_id: number; project_id: number } | null>(null)
  const [saving, setSaving] = useState(false)
  const [privateOpen, setPrivateOpen] = useState(false)

  const loadSeq = useRef(0)
  const load = async () => {
    const seq = ++loadSeq.current
    setLoading(true)
    try {
      const [g, a, w] = await Promise.all([tgApi.aiGroups(), tgApi.accounts(), tgApi.ensureWorkspace()])
      if (seq !== loadSeq.current) return
      setGroups(g)
      setAccounts(a)
      setWs(w)
      setCurrent((c) => (c ? (g.find((x) => x.id === c.id) ?? null) : c))
    } catch (e) {
      if (seq === loadSeq.current) toast.error(errMsg(e, '加载失败'))
    } finally {
      if (seq === loadSeq.current) setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const doCreate = async () => {
    if (!form.name.trim() || !form.chat.trim()) {
      toast.error('名称和群必填')
      return
    }
    const isId = /^-?\d+$/.test(form.chat.trim())
    if (!isId && !form.join_account_id) {
      toast.error('填链接时请选一个账号用于解析/进群')
      return
    }
    setSaving(true)
    try {
      const ws = await tgApi.ensureWorkspace()
      const g = await tgApi.createAiGroup({
        ...formPayload(form),
        tenant_id: ws.tenant_id,
        project_id: ws.project_id,
        chat: form.chat.trim(),
        topic_id: form.topic_id.trim() ? Number(form.topic_id) : null,
        join_account_id: form.join_account_id ? Number(form.join_account_id) : null,
        status: 'paused',
      })
      toast.success('已创建,下一步添加成员并设置人设')
      setCreating(false)
      await load()
      setCurrent(g)
    } catch (e) {
      toast.error(errMsg(e, '创建失败'))
    } finally {
      setSaving(false)
    }
  }

  const toggle = async (g: AiGroup) => {
    const status = g.status === 'active' ? 'paused' : 'active'
    setGroups((prev) => prev.map((x) => (x.id === g.id ? { ...x, status } : x)))
    setCurrent((c) => (c && c.id === g.id ? { ...c, status } : c))
    try {
      await tgApi.updateAiGroup(g.id, { status })
      toast.success(status === 'active' ? '已启动' : '已暂停')
    } catch (e) {
      toast.error(errMsg(e, '操作失败'))
    } finally {
      void load()
    }
  }

  const remove = async (g: AiGroup) => {
    if (!confirm(`删除炒群任务「${g.name}」?成员和剧本一起删除`)) return
    try {
      await tgApi.deleteAiGroup(g.id)
      setCurrent(null)
      void load()
    } catch (e) {
      toast.error(errMsg(e, '删除失败'))
    }
  }

  if (current) {
    return (
      <GroupDetail
        key={current.id}
        group={current}
        accounts={accounts}
        onBack={() => setCurrent(null)}
        onToggle={() => void toggle(current)}
        onDelete={() => void remove(current)}
        onChanged={() => void load()}
      />
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-lg font-semibold">炒群配置</h1>
          <p className="text-sm text-muted-foreground">按群管理:每个群一个主题,选多个账号当群成员,每个号单独设人设</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => setPrivateOpen(true)}>
            私信自动回复
          </Button>
          <Button variant="outline" size="sm" onClick={() => void load()} disabled={loading}>
            <RefreshCw className="mr-1 h-4 w-4" />
            刷新
          </Button>
          <Button
            size="sm"
            onClick={() => {
              setForm(GROUP_DEFAULT)
              setCreating(true)
            }}
          >
            <Plus className="mr-1 h-4 w-4" />
            新建炒群任务
          </Button>
        </div>
      </div>

      {groups.length === 0 && !loading && (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">还没有炒群任务,点右上角新建</CardContent>
        </Card>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {groups.map((g) => (
          <Card key={g.id} className="cursor-pointer transition-colors hover:border-primary/60" onClick={() => setCurrent(g)}>
            <CardContent className="space-y-2 p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="truncate font-medium">{g.name}</div>
                  <div className="truncate font-mono text-xs text-muted-foreground">
                    {g.chat_ref ? `${g.chat_ref}(${g.chat_id})` : g.chat_id}
                    {g.topic_id ? ` / 话题 ${g.topic_id}` : ''}
                  </div>
                </div>
                <button
                  type="button"
                  className="flex shrink-0 items-center gap-2 rounded-md border px-2 py-1 text-xs"
                  onClick={(e) => {
                    e.stopPropagation()
                    void toggle(g)
                  }}
                >
                  <Switch checked={g.status === 'active'} className="pointer-events-none" />
                  {g.status === 'active' ? '运行中' : '已暂停'}
                </button>
              </div>
              <p className="line-clamp-2 min-h-[2.5rem] text-xs text-muted-foreground">{g.theme || '未设置主题'}</p>
              <div className="flex flex-wrap gap-1.5 text-xs">
                <Badge variant="secondary">
                  成员 {g.active_member_count}/{g.member_count}
                </Badge>
                <Badge variant="secondary">今日发言 {g.today_replies}</Badge>
                <Badge variant={g.pending_approvals ? 'default' : 'secondary'}>待审批 {g.pending_approvals}</Badge>
                <Badge variant="outline">
                  并发 {g.reply_min}-{g.reply_max}
                </Badge>
                {g.auto_approve && <Badge variant="outline">自动审批</Badge>}
                {!g.has_provider_key && <Badge variant="destructive">未填 Key</Badge>}
              </div>
            </CardContent>
          </Card>
        ))}
      </div>

      <Dialog open={creating} onOpenChange={setCreating}>
        <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>新建炒群任务</DialogTitle>
          </DialogHeader>
          <GroupSettings form={form} setForm={setForm} creating accounts={accounts} hasKey={false} scope={ws} />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setCreating(false)}>
              取消
            </Button>
            <Button onClick={() => void doCreate()} disabled={saving}>
              {saving ? '创建中…' : '创建'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>

      <PrivateReplyDialog
        open={privateOpen}
        onOpenChange={setPrivateOpen}
        accounts={accounts.filter((a) => !ws || (a.tenant_id === ws.tenant_id && a.project_id === ws.project_id))}
      />
    </div>
  )
}

function GroupDetail({
  group,
  accounts,
  onBack,
  onToggle,
  onDelete,
  onChanged,
}: {
  group: AiGroup
  accounts: TgAccount[]
  onBack: () => void
  onToggle: () => void
  onDelete: () => void
  onChanged: () => void
}) {
  const [tab, setTab] = useState<Tab>('members')
  const [members, setMembers] = useState<AiMember[]>([])
  const memberSeq = useRef(0)

  const loadMembers = async () => {
    const seq = ++memberSeq.current
    try {
      const rows = await tgApi.aiMembers(group.id)
      if (seq === memberSeq.current) setMembers(rows)
    } catch (e) {
      if (seq === memberSeq.current) toast.error(errMsg(e, '成员加载失败'))
    }
  }
  useEffect(() => {
    void loadMembers()
  }, [group.id])

  const warmup = async () => {
    try {
      const r = await tgApi.aiGroupWarmup(group.id)
      toast[r.started ? 'success' : 'error'](r.started ? '已安排一个号开话题' : '没有可发言的成员(冷却/上限/离线)')
    } catch (e) {
      toast.error(errMsg(e, '暖场失败'))
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Button variant="ghost" size="sm" onClick={onBack}>
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-semibold">{group.name}</h1>
            <p className="truncate font-mono text-xs text-muted-foreground">
              {group.chat_ref ? `${group.chat_ref}(${group.chat_id})` : group.chat_id}
            </p>
          </div>
          <Badge variant={group.status === 'active' ? 'default' : 'secondary'}>{group.status === 'active' ? '运行中' : '已暂停'}</Badge>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void warmup()} disabled={group.status !== 'active'}>
            <Sparkles className="mr-1 h-4 w-4" />
            立即暖场
          </Button>
          <Button size="sm" variant={group.status === 'active' ? 'outline' : 'default'} onClick={onToggle}>
            {group.status === 'active' ? <Pause className="mr-1 h-4 w-4" /> : <Play className="mr-1 h-4 w-4" />}
            {group.status === 'active' ? '暂停' : '启动'}
          </Button>
          <Button size="sm" variant="outline" onClick={onDelete}>
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-1 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === t.key ? 'border-primary font-medium' : 'border-transparent text-muted-foreground'}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'members' && (
        <MembersTab group={group} members={members} setMembers={setMembers} accounts={accounts} reload={() => {
          void loadMembers()
          onChanged()
        }} />
      )}
      {tab === 'settings' && <SettingsTab group={group} accounts={accounts} onSaved={onChanged} />}
      {tab === 'chat' && <ChatTab group={group} members={members} />}
      {tab === 'runs' && <RunsTab group={group} />}
      {tab === 'scripts' && <ScriptsTab group={group} members={members} />}
    </div>
  )
}

function SettingsTab({ group, accounts, onSaved }: { group: AiGroup; accounts: TgAccount[]; onSaved: () => void }) {
  const [form, setForm] = useState<GroupForm>(toForm(group))
  const [saving, setSaving] = useState(false)
  const save = async () => {
    if (num(form.reply_max, 1) < num(form.reply_min)) {
      toast.error('最多接话号数不能小于最少接话号数')
      return
    }
    setSaving(true)
    try {
      await tgApi.updateAiGroup(group.id, formPayload(form))
      toast.success('已保存,下一条群消息起生效')
      setForm({ ...form, provider_key: '' })
      onSaved()
    } catch (e) {
      toast.error(errMsg(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }
  return (
    <div className="space-y-3">
      <GroupSettings form={form} setForm={setForm} creating={false} accounts={accounts} hasKey={group.has_provider_key} scope={{ tenant_id: group.tenant_id, project_id: group.project_id }} />
      <div className="flex justify-end">
        <Button onClick={() => void save()} disabled={saving}>
          <Save className="mr-1 h-4 w-4" />
          {saving ? '保存中…' : '保存设置'}
        </Button>
      </div>
    </div>
  )
}

function MembersTab({
  group,
  members,
  setMembers,
  accounts,
  reload,
}: {
  group: AiGroup
  members: AiMember[]
  setMembers: (fn: (rows: AiMember[]) => AiMember[]) => void
  accounts: TgAccount[]
  reload: () => void
}) {
  const [edit, setEdit] = useState<AiMember | null>(null)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<MemberForm>(MEMBER_DEFAULT)
  const [saving, setSaving] = useState(false)
  const [personas, setPersonas] = useState<AiPersona[]>([])

  useEffect(() => {
    tgApi.aiPersonas().then(setPersonas).catch(() => undefined)
  }, [])

  const openNew = () => {
    setEdit(null)
    setForm(MEMBER_DEFAULT)
    setOpen(true)
  }
  const openEdit = (m: AiMember) => {
    setEdit(m)
    setForm({
      account_id: String(m.account_id),
      account_ids: [],
      role_name: m.role_name || '',
      persona: m.persona || '',
      talkativeness: String(m.talkativeness),
      reply_delay_s: String(m.reply_delay_s),
      provider_model: m.provider_model || '',
      provider_key: '',
      status: m.status,
    })
    setOpen(true)
  }

  const save = async () => {
    if (!edit && !form.account_ids.length) {
      toast.error('请选择账号')
      return
    }
    const body = {
      role_name: form.role_name.trim() || null,
      persona: form.persona.trim() || null,
      talkativeness: num(form.talkativeness, 30),
      reply_delay_s: num(form.reply_delay_s),
      provider_model: form.provider_model.trim() || null,
      provider_key: form.provider_key.trim() || null,
      status: form.status,
    }
    setSaving(true)
    try {
      if (edit) {
        await tgApi.updateAiMember(group.id, edit.id, body)
        toast.success('已保存')
      } else {
        let ok = 0
        const failed: string[] = []
        for (const id of form.account_ids) {
          try {
            await tgApi.addAiMember(group.id, { ...body, account_id: Number(id) })
            ok++
          } catch (e) {
            const acc = accounts.find((a) => a.id === Number(id))
            failed.push(`${acc ? accLabel(acc) : id}: ${errMsg(e, '失败')}`)
          }
        }
        if (failed.length) toast.warning(`成功 ${ok} 个,失败 ${failed.length} 个:${failed.join(';')}`)
        else toast.success(`已添加 ${ok} 个成员`)
      }
      setOpen(false)
      reload()
    } catch (e) {
      toast.error(errMsg(e, '保存失败'))
    } finally {
      setSaving(false)
    }
  }

  const saveTemplate = async () => {
    if (!form.persona.trim()) {
      toast.error('先写人设')
      return
    }
    const name = prompt('模板名称', form.role_name || '人设模板')
    if (!name) return
    try {
      const p = await tgApi.createAiPersona({
        tenant_id: group.tenant_id,
        project_id: group.project_id,
        name,
        role_name: form.role_name.trim() || null,
        persona: form.persona.trim(),
        talkativeness: num(form.talkativeness, 30),
      })
      setPersonas((prev) => [...prev, p])
      toast.success('已存为模板,其他群可直接套用')
    } catch (e) {
      toast.error(errMsg(e, '保存模板失败'))
    }
  }

  const toggle = async (m: AiMember) => {
    const next = m.status === 'active' ? 'paused' : 'active'
    const setStatus = (status: string) =>
      setMembers((rows) => rows.map((r) => (r.id === m.id ? { ...r, status } : r)))
    setStatus(next)
    try {
      await tgApi.updateAiMember(group.id, m.id, { status: next })
      reload()
    } catch (e) {
      setStatus(m.status)
      toast.error(errMsg(e, '操作失败'))
    }
  }
  const remove = async (m: AiMember) => {
    if (!confirm(`把 ${m.account_label} 移出本群任务?`)) return
    try {
      await tgApi.deleteAiMember(group.id, m.id)
      reload()
    } catch (e) {
      toast.error(errMsg(e, '删除失败'))
    }
  }

  const free = accounts.filter(
    (a) =>
      a.tenant_id === group.tenant_id &&
      a.project_id === group.project_id &&
      !members.some((m) => m.account_id === a.id),
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">活跃度 0 = 只在被 @ 或被回复时说话;100 = 每条都想接(仍受并发区间限制)</p>
        <Button size="sm" onClick={openNew}>
          <Plus className="mr-1 h-4 w-4" />
          添加成员
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>账号</TableHead>
                  <TableHead>角色</TableHead>
                  <TableHead>人设</TableHead>
                  <TableHead>活跃度</TableHead>
                  <TableHead>延迟</TableHead>
                  <TableHead>模型</TableHead>
                  <TableHead>状态</TableHead>
                  <TableHead className="text-right">操作</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {members.map((m) => (
                  <TableRow key={m.id}>
                    <TableCell className="whitespace-nowrap">
                      {m.account_label}
                      {!m.account_running && <div className="text-[11px] text-destructive">账号未运行</div>}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">{m.role_name || '-'}</TableCell>
                    <TableCell className="max-w-[260px] truncate text-xs text-muted-foreground" title={m.persona || ''}>
                      {m.persona || '-'}
                    </TableCell>
                    <TableCell>{m.talkativeness}%</TableCell>
                    <TableCell>{m.reply_delay_s}s</TableCell>
                    <TableCell className="text-xs">{m.provider_model || '跟随群'}</TableCell>
                    <TableCell>
                      <button type="button" className="flex items-center gap-2 text-xs" onClick={() => void toggle(m)}>
                        <Switch checked={m.status === 'active'} className="pointer-events-none" />
                        {m.status === 'active' ? '发言' : '暂停'}
                      </button>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-right">
                      <Button variant="ghost" size="sm" onClick={() => openEdit(m)}>
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => void remove(m)}>
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {members.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={8} className="py-8 text-center text-sm text-muted-foreground">
                      还没有成员,点「添加成员」选账号
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{edit ? `编辑成员 ${edit.account_label}` : '添加成员'}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            {!edit && (
              <div className="sm:col-span-2">
                <Field label="账号(可多选,共用下方人设)" hint={group.chat_ref ? '添加时会自动用链接进群' : undefined}>
                  <div className="max-h-44 overflow-y-auto rounded-md border p-1">
                  {free.map((a) => {
                    const id = String(a.id)
                    const checked = form.account_ids.includes(id)
                    return (
                      <label
                        key={a.id}
                        className="flex cursor-pointer items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-accent"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() =>
                            setForm({
                              ...form,
                              account_ids: checked
                                ? form.account_ids.filter((x) => x !== id)
                                : [...form.account_ids, id],
                            })
                          }
                        />
                        {accLabel(a)}
                      </label>
                    )
                  })}
                  {!free.length && (
                    <p className="px-2 py-1.5 text-sm text-muted-foreground">可选账号都在群里了</p>
                  )}
                  </div>
                </Field>
                {form.account_ids.length > 0 && (
                  <p className="mt-1 text-xs text-muted-foreground">已选 {form.account_ids.length} 个账号</p>
                )}
              </div>
            )}
            {personas.length > 0 && (
              <Field label="套用人设模板">
                <Select
                  value=""
                  onValueChange={(v) => {
                    const p = personas.find((x) => String(x.id) === v)
                    if (p) setForm({ ...form, role_name: p.role_name || form.role_name, persona: p.persona, talkativeness: String(p.talkativeness) })
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="选择模板" />
                  </SelectTrigger>
                  <SelectContent>
                    {personas.map((p) => (
                      <SelectItem key={p.id} value={String(p.id)}>
                        {p.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}
            <Field label="角色名" hint="群里其他 AI 成员会知道这个名字">
              <Input value={form.role_name} onChange={(e) => setForm({ ...form, role_name: e.target.value })} placeholder="老王" />
            </Field>
            <Field label="活跃度 0-100">
              <Input value={form.talkativeness} onChange={(e) => setForm({ ...form, talkativeness: e.target.value })} />
            </Field>
            <div className="sm:col-span-2">
              <Field label="人设(性格、说话风格、示例语句)">
                <Textarea
                  rows={6}
                  value={form.persona}
                  onChange={(e) => setForm({ ...form, persona: e.target.value })}
                  placeholder={'30 岁币圈老韭菜,说话简短带点东北口音,爱用"整""老铁"\n示例:这波稳了老铁 / 我先观望一下'}
                />
              </Field>
            </div>
            <Field label="发言延迟(秒,±30% 随机)">
              <Input value={form.reply_delay_s} onChange={(e) => setForm({ ...form, reply_delay_s: e.target.value })} />
            </Field>
            <Field label="单独模型(空 = 跟随群)">
              <Input value={form.provider_model} onChange={(e) => setForm({ ...form, provider_model: e.target.value })} />
            </Field>
            <Field label="单独 API Key(空 = 跟随群)" hint={edit?.has_provider_key ? '已单独保存,留空不更换' : undefined}>
              <Input type="password" value={form.provider_key} onChange={(e) => setForm({ ...form, provider_key: e.target.value })} />
            </Field>
          </div>
          <div className="flex justify-between gap-2">
            <Button variant="outline" onClick={() => void saveTemplate()}>
              存为人设模板
            </Button>
            <div className="flex gap-2">
              <Button variant="outline" onClick={() => setOpen(false)}>
                取消
              </Button>
              <Button onClick={() => void save()} disabled={saving}>
                {saving ? '保存中…' : '保存'}
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function ChatTab({ group, members }: { group: AiGroup; members: AiMember[] }) {
  const [msgs, setMsgs] = useState<AiGroupMessage[]>([])
  const load = async () => {
    try {
      setMsgs(await tgApi.aiGroupMessages(group.id))
    } catch {
      toast.error('加载失败')
    }
  }
  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 5000)
    return () => clearInterval(t)
  }, [group.id])
  void members
  return (
    <Card>
      <CardContent className="max-h-[65vh] space-y-2 overflow-y-auto p-4">
        {msgs.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">还没收到群消息(成员账号运行中才会上报)</p>}
        {msgs.map((m) => (
          <div key={m.mid} className={`flex ${m.ours ? 'justify-end' : ''}`}>
            <div className={`max-w-[75%] rounded-lg px-3 py-2 text-sm ${m.ours ? 'bg-primary/15' : 'bg-muted'}`}>
              <div className="mb-0.5 text-[11px] text-muted-foreground">
                {m.sender}
                {m.ours && ' · 我方'} · {fmtTs(m.ts)}
              </div>
              <div className="whitespace-pre-wrap break-words">{m.text}</div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function RunsTab({ group }: { group: AiGroup }) {
  const [runs, setRuns] = useState<AiGroupRun[]>([])
  const load = async () => {
    try {
      setRuns(await tgApi.aiGroupRuns(group.id))
    } catch {
      toast.error('加载失败')
    }
  }
  useEffect(() => {
    void load()
  }, [group.id])
  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => void load()}>
          <RefreshCw className="mr-1 h-4 w-4" />
          刷新
        </Button>
      </div>
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>时间</TableHead>
                  <TableHead>类型</TableHead>
                  <TableHead>成员</TableHead>
                  <TableHead>触发</TableHead>
                  <TableHead>生成内容</TableHead>
                  <TableHead>状态</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {runs.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell className="whitespace-nowrap text-xs">{fmtTs(r.created_time)}</TableCell>
                    <TableCell className="text-xs">{MODE[r.mode] || r.mode}</TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      {r.role_name || '-'}
                      <div className="text-muted-foreground">{r.account_label}</div>
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate text-xs text-muted-foreground" title={r.trigger_text}>
                      {r.trigger_sender ? `${r.trigger_sender}:` : ''}
                      {r.trigger_text || '-'}
                    </TableCell>
                    <TableCell className="max-w-[260px] truncate text-xs" title={r.content || ''}>
                      {r.content || '-'}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs">
                      <Badge variant={r.status === 'failed' ? 'destructive' : 'secondary'}>{RUN_STATUS[r.status] || r.status}</Badge>
                      {r.candidate_status && <span className="ml-1">{CAND_STATUS[r.candidate_status] || r.candidate_status}</span>}
                      {r.last_error && <div className="text-destructive">{gateReason(r.last_error)}</div>}
                    </TableCell>
                  </TableRow>
                ))}
                {runs.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="py-8 text-center text-sm text-muted-foreground">
                      暂无发言记录
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function ScriptsTab({ group, members }: { group: AiGroup; members: AiMember[] }) {
  const [scripts, setScripts] = useState<AiScript[]>([])
  const [edit, setEdit] = useState<AiScript | null>(null)
  const [open, setOpen] = useState(false)
  const [name, setName] = useState('')
  const [interval, setIntervalS] = useState('30')
  const [rewrite, setRewrite] = useState(false)
  const [lines, setLines] = useState<{ member_id: string; text: string }[]>([])

  const load = async () => {
    try {
      setScripts(await tgApi.aiScripts(group.id))
    } catch {
      toast.error('加载失败')
    }
  }
  useEffect(() => {
    void load()
    const t = setInterval(() => void load(), 8000)
    return () => clearInterval(t)
  }, [group.id])

  const memberName = (id: number) => {
    const m = members.find((x) => x.id === id)
    return m ? m.role_name || m.account_label : `#${id}`
  }

  const openEdit = (s: AiScript | null) => {
    setEdit(s)
    setName(s?.name || '')
    setIntervalS(String(s?.interval_s ?? 30))
    setRewrite(s?.rewrite ?? false)
    setLines(s ? s.lines.map((l) => ({ member_id: String(l.member_id), text: l.text })) : [{ member_id: members[0] ? String(members[0].id) : '', text: '' }])
    setOpen(true)
  }

  const save = async () => {
    const body = {
      name: name.trim() || '剧本',
      interval_s: num(interval, 30),
      rewrite,
      lines: lines.filter((l) => l.member_id && l.text.trim()).map((l) => ({ member_id: Number(l.member_id), text: l.text.trim() })),
    }
    if (!body.lines.length) {
      toast.error('至少一句台词')
      return
    }
    try {
      if (edit) await tgApi.updateAiScript(group.id, edit.id, body)
      else await tgApi.createAiScript(group.id, body)
      setOpen(false)
      void load()
    } catch (e) {
      toast.error(errMsg(e, '保存失败'))
    }
  }

  const act = async (fn: () => Promise<unknown>, ok: string) => {
    try {
      await fn()
      toast.success(ok)
      void load()
    } catch (e) {
      toast.error(errMsg(e, '操作失败'))
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm text-muted-foreground">剧本按顺序由指定成员发出,每句都走审批/发送队列;开启改写时 AI 会按角色人设润色台词</p>
        <Button size="sm" onClick={() => openEdit(null)} disabled={!members.length}>
          <Plus className="mr-1 h-4 w-4" />
          新建剧本
        </Button>
      </div>
      {scripts.map((s) => (
        <Card key={s.id}>
          <CardContent className="space-y-2 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span className="font-medium">{s.name}</span>
                <Badge variant={s.status === 'running' ? 'default' : 'secondary'}>
                  {s.status === 'running' ? `播放中 ${s.cursor}/${s.lines.length}` : s.status === 'done' ? '已播完' : '未播放'}
                </Badge>
                <span className="text-xs text-muted-foreground">
                  间隔 {s.interval_s}s{s.rewrite ? ' · AI 改写' : ''}
                </span>
              </div>
              <div className="flex gap-1">
                {s.status === 'running' ? (
                  <Button size="sm" variant="outline" onClick={() => void act(() => tgApi.stopAiScript(group.id, s.id), '已停止')}>
                    <Square className="mr-1 h-4 w-4" />
                    停止
                  </Button>
                ) : (
                  <Button size="sm" onClick={() => void act(() => tgApi.startAiScript(group.id, s.id), '开始播放')} disabled={group.status !== 'active'}>
                    <Play className="mr-1 h-4 w-4" />
                    播放
                  </Button>
                )}
                <Button size="sm" variant="ghost" onClick={() => openEdit(s)} disabled={s.status === 'running'}>
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => confirm('删除剧本?') && void act(() => tgApi.deleteAiScript(group.id, s.id), '已删除')}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
            <ol className="space-y-0.5 text-xs text-muted-foreground">
              {s.lines.map((l, i) => (
                <li key={i} className={s.status === 'running' && i === s.cursor ? 'text-foreground' : ''}>
                  {i + 1}. <span className="font-medium">{memberName(l.member_id)}</span>:{l.text}
                </li>
              ))}
            </ol>
          </CardContent>
        </Card>
      ))}
      {scripts.length === 0 && <p className="py-6 text-center text-sm text-muted-foreground">暂无剧本</p>}

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{edit ? '编辑剧本' : '新建剧本'}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3 sm:grid-cols-3">
            <Field label="名称">
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="每句间隔(秒)">
              <Input value={interval} onChange={(e) => setIntervalS(e.target.value)} />
            </Field>
            <div className="flex items-end gap-2 pb-2">
              <Switch checked={rewrite} onCheckedChange={setRewrite} />
              <span className="text-sm">AI 按人设改写</span>
            </div>
          </div>
          <div className="space-y-2">
            {lines.map((l, i) => (
              <div key={i} className="flex gap-2">
                <Select value={l.member_id} onValueChange={(v) => setLines(lines.map((x, j) => (j === i ? { ...x, member_id: v } : x)))}>
                  <SelectTrigger className="w-36 shrink-0">
                    <SelectValue placeholder="成员" />
                  </SelectTrigger>
                  <SelectContent>
                    {members.map((m) => (
                      <SelectItem key={m.id} value={String(m.id)}>
                        {m.role_name || m.account_label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Input value={l.text} onChange={(e) => setLines(lines.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)))} placeholder="台词" />
                <Button variant="ghost" size="sm" onClick={() => setLines(lines.filter((_, j) => j !== i))}>
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            ))}
            <Button variant="outline" size="sm" onClick={() => setLines([...lines, { member_id: lines.at(-1)?.member_id || '', text: '' }])}>
              <Plus className="mr-1 h-4 w-4" />
              加一句
            </Button>
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>
              取消
            </Button>
            <Button onClick={() => void save()}>保存</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function PrivateReplyDialog({
  open,
  onOpenChange,
  accounts,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  accounts: TgAccount[]
}) {
  const [rows, setRows] = useState<AiPrivateReply[]>([])
  const [accountId, setAccountId] = useState('')
  const [enabled, setEnabled] = useState(true)
  const [text, setText] = useState('')
  const [cooldown, setCooldown] = useState('60')
  const [forward, setForward] = useState('')

  useEffect(() => {
    if (open) tgApi.aiPrivateReplies().then(setRows).catch(() => toast.error('加载失败'))
  }, [open])

  const pick = (v: string) => {
    setAccountId(v)
    const r = rows.find((x) => String(x.account_id) === v)
    setEnabled(r?.enabled ?? true)
    setText(r?.reply_text || '')
    setCooldown(String(r?.reply_cooldown_min ?? 60))
    setForward(r?.forward_chat_id ? String(r.forward_chat_id) : '')
  }

  const save = async () => {
    if (!accountId) return
    try {
      const r = await tgApi.saveAiPrivateReply(Number(accountId), {
        enabled,
        reply_text: text.trim() || null,
        reply_cooldown_min: num(cooldown, 60),
        forward_chat_id: forward.trim() ? Number(forward) : null,
      })
      setRows((prev) => [...prev.filter((x) => x.account_id !== r.account_id), r])
      toast.success('已保存')
    } catch (e) {
      toast.error(errMsg(e, '保存失败'))
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>私信自动回复 / 转发</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="账号">
            <Select value={accountId} onValueChange={pick}>
              <SelectTrigger>
                <SelectValue placeholder="选择账号" />
              </SelectTrigger>
              <SelectContent>
                {accounts.map((a) => (
                  <SelectItem key={a.id} value={String(a.id)}>
                    {accLabel(a)}
                    {rows.some((r) => r.account_id === a.id && r.enabled) ? '(已开启)' : ''}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </Field>
          {accountId && (
            <>
              <div className="flex items-center gap-2">
                <Switch checked={enabled} onCheckedChange={setEnabled} />
                <span className="text-sm">开启</span>
              </div>
              <Field label="自动回复话术(空 = 不回复)">
                <Textarea rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="您好,稍等马上回复您" />
              </Field>
              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="同一人回复冷却(分钟)">
                  <Input value={cooldown} onChange={(e) => setCooldown(e.target.value)} />
                </Field>
                <Field label="转发到(业务号/群 数字 ID,空 = 不转发)">
                  <Input value={forward} onChange={(e) => setForward(e.target.value)} />
                </Field>
              </div>
              <div className="flex justify-end">
                <Button onClick={() => void save()}>保存</Button>
              </div>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}
