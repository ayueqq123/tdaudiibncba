import { useEffect, useState } from 'react'
import { Pencil, Play, Plus, RefreshCw, ShieldCheck, Square, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { hasGroup, tgApi, type AiProvider, type CloneRule, type CloneTarget, type TgAccount } from '@/lib/api'
import { buildCloneUsage, usageDetail, usageShort } from '@/lib/clone-usage'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

const EMPTY_FORM = {
  account_id: '', name: '', mode: 'copy',
  ai_rewrite: 'off', ad_block: 'off', ad_keywords: '', ai_provider_id: '', ai_prompt: '',
  watermark_mode: 'off', watermark_mask: '',
  sync_edit: true, sync_delete: true, delay_min_s: '0', delay_max_s: '0',
  routes: [{ source: '', target: '' }] as { source: string; target: string }[],
  remark: '',
  // 高级字段:编辑时原样保留,此页不展示
  sender_account_ids: [] as number[],
  target_filters: null as Record<string, any> | null,
}

const STATUS_LABEL: Record<string, string> = {
  auth_dead: '登录失效',
  revoked: '登录失效',
  reauth_required: '需重登',
  banned: '已禁言',
  frozen: '已冻结',
  error: '异常',
  disabled: '已禁用',
}
const DEAD_STATUS = new Set(Object.keys(STATUS_LABEL))
const senderStatusLabel = (status?: string) =>
  status === 'member' ? '已进频道' : status === 'muted' ? '被禁言' :
  status === 'banned' || status === 'kicked' ? '被踢/封禁' :
  status === 'not_member' ? '未进频道' : status === 'unauthorized' ? '登录失效' :
  status === 'frozen' ? '账号冻结' : status === 'join_failed' ? '进频道失败' :
  status === 'flood_wait' ? '限流稍后重试' : '检测失败'

const parseList = (s: string) => s.split(/[,\s，]+/).map((x) => x.trim()).filter(Boolean)

// 批量路线:每行一对「源 → 目标」,支持 → -> => 逗号 Tab 空格分隔;# 开头行为注释
function parseBatchRoutes(text: string): [string, string][] {
  const pairs: [string, string][] = []
  for (const raw of text.split('\n')) {
    const line = raw.trim()
    if (!line || line.startsWith('#')) continue
    let parts = line.split(/\s*(?:→|->|=>|,|，|\t)\s*/).filter(Boolean)
    if (parts.length < 2) parts = line.split(/\s+/).filter(Boolean)
    if (parts.length >= 2) pairs.push([parts[0], parts[1]])
  }
  return pairs
}

type BatchLine = { index: number; source: string; target: string; ok: boolean; reason: string | null }
const chatLabel = (ref: string | null | undefined, id: number) => (ref && ref !== String(id) ? `${ref}(${id})` : String(id))

export default function ChannelClonePage() {
  const [rows, setRows] = useState<CloneRule[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [providers, setProviders] = useState<AiProvider[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [open, setOpen] = useState(false)
  const [editRule, setEditRule] = useState<CloneRule | null>(null)
  const [form, setForm] = useState<any>({ ...EMPTY_FORM })

  const [checking, setChecking] = useState<number | null>(null)
  const [poolSearch, setPoolSearch] = useState('')
  const [poolFilter, setPoolFilter] = useState('all')
  const [randomN, setRandomN] = useState('')
  const [batchText, setBatchText] = useState('')
  const [batchReport, setBatchReport] = useState<BatchLine[] | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [r, a, g] = await Promise.all([
        tgApi.rules({ with_targets: true, kind: 'channel' }),
        tgApi.accounts(),
        tgApi.aiProviders().catch(() => []),
      ])
      setAccounts(a)
      setProviders(g)
      r.sort((x, y) => x.id - y.id)
      setRows(r)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function applyToWorker(ruleId: number, version: number, accountId: number) {
    const v = await tgApi.publishRule(ruleId, version)
    await tgApi.issueCommand(accountId, { type: 'ReloadConfig' })
    return v
  }

  const isRunning = (r: CloneRule) => r.enabled && r.current_version > 0
  const selectableAccounts = accounts.filter(
    (a) => hasGroup(a, 'channel') || a.id === Number(form.account_id) || (form.sender_account_ids || []).includes(a.id),
  )
  const otherUsage = buildCloneUsage(rows.filter((r) => r.id !== editRule?.id))
  const isFree = (id: number) => !otherUsage.get(id)?.length
  const accName = (a: TgAccount) => (a.username ? '@' + a.username : a.phone || String(a.telegram_user_id || a.id))
  const isDead = (a: TgAccount) => !!(a.observed_status && DEAD_STATUS.has(a.observed_status))
  // 监听号下拉:正常号排前面,死号带状态排在最后
  const listenerAccounts = [...selectableAccounts].sort((x, y) => Number(isDead(x)) - Number(isDead(y)))
  const accLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return a?.username ? '@' + a.username : a?.phone || String(a?.telegram_user_id || id)
  }
  const poolAccounts = selectableAccounts
    .filter((a) => {
      const q = poolSearch.trim().toLowerCase()
      if (q && ![a.username, a.phone, String(a.telegram_user_id || ''), String(a.id)].some((v) => (v || '').toLowerCase().includes(q))) return false
      if (poolFilter === 'free') return isFree(a.id)
      if (poolFilter === 'mine') return form.sender_account_ids.includes(a.id)
      if (poolFilter === 'other') return !isFree(a.id)
      return true
    })
    .map((a, i) => ({ a, i }))
    .sort((x, y) => Number(!isFree(x.a.id)) - Number(!isFree(y.a.id)) || Number(isDead(x.a)) - Number(isDead(y.a)) || x.i - y.i)
    .map((x) => x.a)
  function pickRandomFree() {
    const n = Number(randomN)
    if (!n || n < 1) return toast.error('填要勾几个')
    const pool = selectableAccounts.filter(
      (a) => isFree(a.id) && !form.sender_account_ids.includes(a.id) && a.id !== Number(form.account_id) && !isDead(a),
    )
    const picked = [...pool].sort(() => Math.random() - 0.5).slice(0, n).map((a) => a.id)
    if (!picked.length) return toast.error('没有空闲号了')
    setForm({ ...form, sender_account_ids: [...form.sender_account_ids, ...picked] })
    toast.success(picked.length < n ? `空闲号只有 ${picked.length} 个,已全部勾上` : `已勾 ${picked.length} 个空闲号`)
  }

  async function doCheck(r: CloneRule) {
    setChecking(r.id)
    try {
      const res = await tgApi.checkRule(r.id)
      const bad = res.filter((x: any) => !x.ok)
      const blocked = new Set<string>()
      let listenerBlocked = 0
      let listenerDead = false
      for (const route of res) {
        for (const [id, sender] of Object.entries<any>(route.senders || {})) {
          if (sender.can_post !== true) blocked.add(id)
        }
        if (route.listener_status === 'unauthorized') listenerDead = true
        if (route.listener_can_post === false) listenerBlocked++
      }
      const parts: string[] = []
      if (bad.length) parts.push(`${bad.length} 条路线失效:${bad[0].reason}`)
      if (blocked.size) parts.push(`${blocked.size} 个发送号没有目标频道发帖权限(要设为管理员)`)
      if (listenerBlocked) parts.push(`监听号在 ${listenerBlocked} 个目标频道没有发帖权限`)
      if (listenerDead) parts.push('监听号登录已失效,需重登')
      if (!parts.length) toast.success('路线正常,监听号和发送号都能发帖')
      else toast.warning(parts.join('；'))
      await load()
    } catch (e: any) {
      toast.error(e?.detail || '检测失败')
    } finally {
      setChecking(null)
    }
  }

  async function doSave() {
    const acc = accounts.find((a) => a.id === +form.account_id)
    if (!form.name) return toast.warning('名称必填')
    const needsAi = form.ai_rewrite !== 'off' || form.ad_block === 'ai'
    if (needsAi && (!form.ai_provider_id || form.ai_provider_id === 'auto')) {
      toast.error('开了 AI 改写/AI 判广告,请选择 AI 模型')
      return
    }
    const delayMin = Number(form.delay_min_s)
    const delayMax = Number(form.delay_max_s)
    if (!form.delay_min_s.trim() || !form.delay_max_s.trim() ||
      ![delayMin, delayMax].every((n) => Number.isInteger(n) && n >= 0 && n <= 3600) || delayMin > delayMax)
      return toast.warning('延时范围须为 0–3600 的整数,且最小值不能大于最大值')
    if (!editRule && !acc) return toast.warning('请选择监听账号')
    // 一条路线 = 一个源 → 一个目标;逐行与批量粘贴合并成同一批
    const formPairs: [string, string][] = []
    const seenPair = new Set<string>()
    for (const [i, r] of (form.routes as { source: string; target: string }[]).entries()) {
      const s = r.source.trim()
      const d = r.target.trim()
      if (!s && !d) continue
      if (!s || !d) return toast.warning(`路线第 ${i + 1} 行没填全,源和目标都要填`)
      const key = `${s}→${d}`
      if (!seenPair.has(key)) { seenPair.add(key); formPairs.push([s, d]) }
    }
    const batchPairs = parseBatchRoutes(batchText)
    if (!formPairs.length && !batchPairs.length)
      return toast.warning('至少填一条「源 → 目标」路线,或批量粘贴')
    if ([...formPairs, ...batchPairs].some(([s, d]) => s === d))
      return toast.warning('同一条路线的源频道和目标频道不能相同')
    if (form.watermark_mode === 'mask' && form.watermark_mask.trim() &&
      !form.watermark_mask.split(';').every((seg: string) => {
        const p = seg.trim().split(',').map(Number)
        return p.length === 4 && p.every((n: number) => Number.isFinite(n) && n >= 0 && n <= 1)
      }))
      return toast.warning('固定区域格式: x,y,w,h 各 0-1,多个区域用 ; 分隔')
    const toRef = (s: string) => (/^-?\d+$/.test(s.trim()) ? Number(s.trim()) : s.trim())
    const mkBody = (src: string | number, dst: string | number) => ({
      source_chat_id: toRef(String(src)),
      target_chat_id: toRef(String(dst)),
      filters: form.target_filters,
    })
    const ruleBody = {
      name: form.name,
      mode: form.mode,
      sync_edit: form.sync_edit,
      sync_delete: form.sync_delete,
      remark: form.remark || null,
      sender_account_ids: form.sender_account_ids,
      delay_min_s: delayMin,
      delay_max_s: delayMax,
      ai_rewrite: form.ai_rewrite,
      ad_block: form.ad_block,
      ad_keywords: parseList(form.ad_keywords),
      watermark_mode: form.watermark_mode,
      watermark_mask: form.watermark_mask || null,
      ai_provider_id: form.ai_provider_id && form.ai_provider_id !== 'auto' ? +form.ai_provider_id : null,
      ai_prompt: form.ai_prompt.trim() || null,
    }

    let reportShown = false
    setBusy(true)
    try {
      if (editRule) {
        await tgApi.updateRule(editRule.id, { ...ruleBody, enabled: editRule.enabled })
        const active = (editRule.targets || []).filter((t) => t.status === 'active' || !t.status)
        const desiredPairs = formPairs.map(([src, dst]) => ({ src, dst }))
        const pairKey = (src: string, dst: string) => JSON.stringify([src, dst])
        const covered = new Set<string>()
        const kept: CloneTarget[] = []
        const removed: CloneTarget[] = []
        for (const t of active) {
          const matches = desiredPairs.filter(
            ({ src, dst }) =>
              (src === t.source_chat_ref || src === String(t.source_chat_id)) &&
              (dst === t.target_chat_ref || dst === String(t.target_chat_id)),
          )
          if (matches.length) {
            kept.push(t)
            matches.forEach(({ src, dst }) => covered.add(pairKey(src, dst)))
          } else {
            removed.push(t)
          }
        }
        for (const t of removed) await tgApi.retireTarget(editRule.id, t.id)
        for (const t of kept) {
          await tgApi.updateTarget(editRule.id, t.id, mkBody(t.source_chat_ref || t.source_chat_id, t.target_chat_ref || t.target_chat_id))
        }
        const newPairs = desiredPairs.filter(({ src, dst }) => !covered.has(pairKey(src, dst)))
        const allNew = [...newPairs.map(({ src, dst }) => [src, dst] as [string, string]), ...batchPairs]
        if (allNew.length) {
          const rep = await tgApi.addTargetsBatch(editRule.id, allNew.map(([s, d]) => mkBody(s, d)))
          setBatchReport(rep.results)
          reportShown = true
          toast.success(`新路线:成功 ${rep.created} 条,失败 ${rep.failed} 条`)
        } else if (isRunning(editRule)) {
          await applyToWorker(editRule.id, editRule.current_version, editRule.account_id)
          toast.success('已保存并生效')
        } else {
          toast.success('已保存')
        }
      } else {
        const before = new Set(rows.map((x) => x.id))
        await tgApi.createRule({
          ...ruleBody,
          kind: 'channel',
          account_id: acc!.id,
          tenant_id: acc!.tenant_id,
          project_id: acc!.project_id,
          enabled: true,
        })
        const list = await tgApi.rules({ kind: 'channel' })
        const created = list.filter((x) => !before.has(x.id)).sort((a, b) => b.id - a.id)[0]
        if (!created) throw new Error('规则已创建但找不到,请刷新后手动补路线')
        const allNew = [...formPairs, ...batchPairs]
        const rep = await tgApi.addTargetsBatch(created.id, allNew.map(([s, d]) => mkBody(s, d)))
        setBatchReport(rep.results)
        reportShown = true
        toast.success(`规则已建好,路线:成功 ${rep.created} 条,失败 ${rep.failed} 条`)
      }
      if (reportShown) {
        // 有逐条报告时弹窗保持打开,清空粘贴框便于继续粘贴
        setBatchText('')
      } else {
        setBatchReport(null)
        setOpen(false)
        setEditRule(null)
        setForm({ ...EMPTY_FORM })
      }
      load()
    } catch (e: any) {
      toast.error(e?.detail || '保存失败')
    } finally {
      setBusy(false)
    }
  }

  function openEdit(r: CloneRule) {
    const active = (r.targets || []).filter((x) => x.status === 'active' || !x.status)
    // 按路线原样还原配对,不打散成两个独立列表
    const routes = active.map((x) => ({
      source: x.source_chat_ref || String(x.source_chat_id),
      target: x.target_chat_ref || String(x.target_chat_id),
    }))
    setEditRule(r)
    setForm({
      ...EMPTY_FORM,
      account_id: String(r.account_id),
      name: r.name,
      mode: r.mode,
      ai_rewrite: r.ai_rewrite || 'off',
      ad_block: r.ad_block || 'off',
      ad_keywords: (r.ad_keywords || []).join(','),
      watermark_mode: r.watermark_mode || 'off',
      watermark_mask: r.watermark_mask || '',
      ai_provider_id: r.ai_provider_id ? String(r.ai_provider_id) : '',
      ai_prompt: r.ai_prompt || '',
      sync_edit: r.sync_edit ?? true,
      sync_delete: r.sync_delete ?? true,
      remark: r.remark || '',
      routes: routes.length ? routes : [{ source: '', target: '' }],
      delay_min_s: String(r.delay_min_s ?? 0),
      delay_max_s: String(r.delay_max_s ?? 0),
      sender_account_ids: r.sender_account_ids || [],
      target_filters: active[0]?.filters || null,
    })
    setOpen(true)
  }

  async function toggleRun(r: CloneRule, enabled: boolean) {
    setRows((prev) => prev.map((x) => (x.id === r.id ? { ...x, enabled, current_version: Math.max(x.current_version, 1) } : x)))
    try {
      await tgApi.updateRule(r.id, {
        name: r.name, mode: r.mode,
        sync_edit: r.sync_edit ?? true, sync_delete: r.sync_delete ?? true,
        enabled, remark: r.remark,
      })
      await applyToWorker(r.id, r.current_version, r.account_id)
      toast.success(enabled ? '已下发,账号开始搬运' : '已停止搬运')
    } catch (e: any) {
      toast.error(e?.detail || (enabled ? '启动失败' : '停止失败'))
    } finally {
      load()
    }
  }

  async function doDeleteRule(r: CloneRule) {
    if (!confirm(`确定删除规则「${r.name}」?`)) return
    try {
      await tgApi.deleteRule(r.id)
      toast.success('已删除')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '删除失败')
    }
  }

  const routeText = (r: CloneRule) => {
    const active = (r.targets || []).filter((t) => t.status === 'active' || !t.status)
    const srcs = [...new Set(active.map((t) => chatLabel(t.source_chat_ref, t.source_chat_id)))]
    const dsts = [...new Set(active.map((t) => chatLabel(t.target_chat_ref, t.target_chat_id)))]
    return `${srcs.join('、') || '-'} → ${dsts.join('、') || '-'}`
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">频道搬运</h2>
          <p className="text-xs text-muted-foreground">监听号进源频道收消息,AI 改写 + 拦广告 + 去水印后发往你的频道</p>
        </div>
        <div className="flex gap-2">
          <Dialog
            open={open}
            onOpenChange={(v) => {
              setOpen(v)
              if (v && !editRule) {
                setForm({
                  ...EMPTY_FORM,
                  ai_provider_id: providers[0] ? String(providers[0].id) : '',
                })
              }
              if (!v) {
                setEditRule(null)
                setForm({ ...EMPTY_FORM })
                setBatchText('')
                setBatchReport(null)
              }
            }}
          >
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> 新建搬运
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
              <DialogHeader>
                <DialogTitle>{editRule ? `编辑「${editRule.name}」` : '新建频道搬运'}</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-4">
                {batchReport && (
                  <section className="rounded-md border p-3">
                    <h3 className="mb-1.5 text-sm font-semibold">
                      批量路线结果:成功 {batchReport.filter((r) => r.ok).length} / 共 {batchReport.length} 条
                    </h3>
                    <div className="max-h-56 overflow-y-auto text-xs">
                      {batchReport.map((r) => (
                        <div key={r.index} className="flex items-baseline gap-2 py-0.5">
                          <span className={r.ok ? 'text-green-600' : 'text-destructive'}>{r.ok ? '✓' : '✗'}</span>
                          <span className="min-w-0 flex-1 truncate" title={`${r.source} → ${r.target}`}>
                            {r.source} → {r.target}
                          </span>
                          {r.reason && <span className="shrink-0 text-destructive">{r.reason}</span>}
                        </div>
                      ))}
                    </div>
                    <Button size="sm" variant="outline" className="mt-2" onClick={() => setBatchReport(null)}>
                      收起结果
                    </Button>
                  </section>
                )}
                <section className="flex flex-col gap-3">
                  <h3 className="text-sm font-semibold">基本信息</h3>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <div className="flex flex-col gap-1.5">
                      <Label>规则名称</Label>
                      <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如:新闻频道搬运" />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>监听号(进源频道收消息){editRule ? '(建好后不可改)' : ''}</Label>
                      <Select value={form.account_id} onValueChange={(v) => setForm({ ...form, account_id: v })} disabled={!!editRule}>
                        <SelectTrigger>
                          <SelectValue placeholder="选择账号" />
                        </SelectTrigger>
                        <SelectContent>
                          {listenerAccounts.map((a) => {
                            const dead = isDead(a)
                            return (
                              <SelectItem key={a.id} value={String(a.id)}>
                                {accName(a)}
                                {a.username && a.phone ? ` · ${a.phone}` : ''}
                                {dead ? ` · ${STATUS_LABEL[a.observed_status] || a.observed_status}` : ''}
                                {(otherUsage.get(a.id) || []).length ? ' · 已在其他规则用' : ''}
                              </SelectItem>
                            )
                          })}
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    监听号要能看源频道;发送号池留空时它也负责发帖,就得是目标频道管理员
                  </p>
                </section>

                <section className="flex flex-col gap-3">
                  <div className="flex items-center justify-between">
                    <h3 className="text-sm font-semibold">发送号池(勾选多个号轮发;不勾 = 监听号自己发)</h3>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-6 px-2 text-xs"
                      onClick={() =>
                        setForm({
                          ...form,
                          sender_account_ids:
                            form.sender_account_ids.length === selectableAccounts.length
                              ? []
                              : selectableAccounts.map((a) => a.id),
                        })
                      }
                    >
                      {form.sender_account_ids.length === selectableAccounts.length && selectableAccounts.length > 0
                        ? '清空'
                        : '全选'}
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Input className="h-8 w-40" placeholder="搜 @用户名/手机号" value={poolSearch} onChange={(e) => setPoolSearch(e.target.value)} />
                    <Select value={poolFilter} onValueChange={setPoolFilter}>
                      <SelectTrigger className="h-8 w-36"><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">全部</SelectItem>
                        <SelectItem value="free">空闲</SelectItem>
                        <SelectItem value="mine">本规则已勾</SelectItem>
                        <SelectItem value="other">其他规则在用</SelectItem>
                      </SelectContent>
                    </Select>
                    <Input className="h-8 w-16" type="number" min={1} placeholder="N" value={randomN} onChange={(e) => setRandomN(e.target.value)} />
                    <Button type="button" variant="outline" size="sm" className="h-8" onClick={pickRandomFree}>随机勾 N 个空闲号</Button>
                    <span className="text-xs text-muted-foreground">
                      已勾 {form.sender_account_ids.length} · 空闲 {selectableAccounts.filter((a) => isFree(a.id)).length}
                    </span>
                  </div>
                  <div className="grid max-h-72 grid-cols-1 gap-1.5 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
                    {poolAccounts.map((a) => {
                      const on = form.sender_account_ids.includes(a.id)
                      const st = a.observed_status
                      const dead = st && DEAD_STATUS.has(st)
                      return (
                        <label key={a.id} className={`flex items-center gap-1.5 text-sm ${dead ? 'text-red-600' : ''}`} title={dead ? a.last_error || '' : ''}>
                          <input
                            type="checkbox"
                            checked={on}
                            onChange={(e) =>
                              setForm({
                                ...form,
                                sender_account_ids: e.target.checked
                                  ? [...form.sender_account_ids, a.id]
                                  : form.sender_account_ids.filter((x: number) => x !== a.id),
                              })
                            }
                          />
                          {accName(a)}
                          {dead && <Badge variant="destructive" className="px-1 py-0 text-[10px]">{STATUS_LABEL[st!] || st}</Badge>}
                          {(() => {
                            const others = otherUsage.get(a.id) || []
                            const otherBadge = others.length ? (
                              <span title={usageDetail(others)}>
                                <Badge variant="warning" className="px-1 py-0 text-[10px]">
                                  {usageShort(others[0])}{others.length > 1 ? ` +${others.length - 1}` : ''}
                                </Badge>
                              </span>
                            ) : null
                            const targets = (editRule?.targets || []).filter((t) => t.status === 'active' || !t.status)
                            if (!targets.length || !on) return otherBadge || <Badge variant="outline" className="px-1 py-0 text-[10px]">空闲</Badge>
                            const joined = targets.filter((t) => (t.joined_account_ids || []).includes(a.id)).length
                            const title = targets.map((t) => {
                              const entry = t.sender_status?.[String(a.id)]
                              const label = entry ? senderStatusLabel(entry.status) : (t.joined_account_ids || []).includes(a.id) ? '已进频道' : '未进频道'
                              const post = entry?.can_post === false ? '(无发帖权限,要设管理员)' : ''
                              return `${t.target_chat_ref || t.target_chat_id}: ${label}${post}${entry?.detail ? ` (${entry.detail})` : ''}`
                            }).join('\n')
                            const cantPost = targets.some((t) => t.sender_status?.[String(a.id)]?.can_post === false)
                            return <>
                              <span title={title}>
                                <Badge variant={cantPost ? 'destructive' : joined === targets.length ? 'success' : 'secondary'} className="px-1 py-0 text-[10px]">
                                  {cantPost ? '无发帖权限' : joined ? `已进 ${joined}/${targets.length}` : '未进频道'}
                                </Badge>
                              </span>
                              {otherBadge}
                            </>
                          })()}
                        </label>
                      )
                    })}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    只有监听号进源频道;发送号只需在目标频道,且<span className="text-foreground font-medium">必须先被设为目标频道管理员(频道 → 管理 → 管理员 → 添加管理员,勾选「发布消息」)</span>,不是管理员的号发不出去
                  </p>
                  <p className="text-xs text-muted-foreground">没进频道的号点"运行"会自动加入并检测发帖权限;点规则卡片「检测」可刷新状态。</p>
                </section>

                <section className="flex flex-col gap-3">
                  <h3 className="text-sm font-semibold">搬运路线</h3>
                  <p className="text-xs text-muted-foreground">
                    一条路线 = 一个源频道 → 一个目标频道;一对一就填一行,一个源搬去多个目标就多写几行。
                    目标频道要把发送号(或监听号)设为管理员并有「发布消息」权限
                  </p>
                  <div className="flex flex-col gap-1.5">
                    {form.routes.map((r: { source: string; target: string }, i: number) => (
                      <div key={i} className="flex items-center gap-1.5">
                        <Input
                          value={r.source}
                          onChange={(e) =>
                            setForm({ ...form, routes: form.routes.map((x: any, j: number) => (j === i ? { ...x, source: e.target.value } : x)) })
                          }
                          placeholder="源频道:-100 开头 ID 或 t.me/xx 链接"
                        />
                        <span className="shrink-0 text-muted-foreground">→</span>
                        <Input
                          value={r.target}
                          onChange={(e) =>
                            setForm({ ...form, routes: form.routes.map((x: any, j: number) => (j === i ? { ...x, target: e.target.value } : x)) })
                          }
                          placeholder="目标频道:-100 开头 ID 或 t.me/xx 链接"
                        />
                        {form.routes.length > 1 && (
                          <Button type="button" variant="ghost" size="sm" className="shrink-0 px-2"
                            onClick={() => setForm({ ...form, routes: form.routes.filter((_: any, j: number) => j !== i) })}>
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        )}
                      </div>
                    ))}
                    <Button type="button" variant="outline" size="sm" className="w-fit"
                      onClick={() => setForm({ ...form, routes: [...form.routes, { source: '', target: '' }] })}>
                      <Plus className="mr-1 h-3.5 w-3.5" /> 添加路线
                    </Button>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>批量粘贴路线(一百多条一次贴进来)</Label>
                    <Textarea
                      rows={4}
                      value={batchText}
                      onChange={(e) => setBatchText(e.target.value)}
                      placeholder={'每行一对「源 → 目标」,支持 → -> 逗号 Tab 空格分隔,例:\n@source_news → @my_channel\n-1001234567890 → t.me/target2'}
                    />
                    <p className="text-xs text-muted-foreground">
                      粘贴后上面的逐个源/目标可留空;同一源搬去多个目标就写多行。提交时自动进群+逐条检测,失败行会在上方列出来
                    </p>
                  </div>
                  <div className="flex flex-col justify-end gap-2">
                    <label className="flex items-center justify-between gap-2 text-sm">
                      源频道编辑 → 跟着改
                      <Switch checked={form.sync_edit} onCheckedChange={(v) => setForm({ ...form, sync_edit: v })} />
                    </label>
                    <label className="flex items-center justify-between gap-2 text-sm">
                      源频道删除 → 跟着删
                      <Switch checked={form.sync_delete} onCheckedChange={(v) => setForm({ ...form, sync_delete: v })} />
                    </label>
                  </div>
                </section>

                <section className="flex flex-col gap-3 rounded-md border p-3">
                  <h3 className="text-sm font-semibold">AI 改写 / 广告拦截 / 去水印</h3>
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                    <div className="flex flex-col gap-1.5">
                      <Label>AI 改写</Label>
                      <Select value={form.ai_rewrite} onValueChange={(v) => setForm({ ...form, ai_rewrite: v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="off">不改写</SelectItem>
                          <SelectItem value="light">轻微改写</SelectItem>
                          <SelectItem value="strong">较大改写</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>广告拦截</Label>
                      <Select value={form.ad_block} onValueChange={(v) => setForm({ ...form, ad_block: v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="off">不拦截</SelectItem>
                          <SelectItem value="keyword">关键词拦截</SelectItem>
                          <SelectItem value="ai">AI 智能判广告</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>去水印</Label>
                      <Select value={form.watermark_mode} onValueChange={(v) => setForm({ ...form, watermark_mode: v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          <SelectItem value="off">不去除</SelectItem>
                          <SelectItem value="auto">自动检测(边缘水印)</SelectItem>
                          <SelectItem value="mask">固定区域</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>
                  {form.ad_block === 'keyword' && (
                    <div className="flex flex-col gap-1.5">
                      <Label>广告关键词(逗号分隔)</Label>
                      <Input value={form.ad_keywords} onChange={(e) => setForm({ ...form, ad_keywords: e.target.value })}
                        placeholder="如 加V,兼职,招商,邀请码" />
                    </div>
                  )}
                  {form.watermark_mode === 'mask' && (
                    <div className="flex flex-col gap-1.5">
                      <Label>固定区域 x,y,w,h(0-1 比例)</Label>
                      <Input value={form.watermark_mask}
                        onChange={(e) => setForm({ ...form, watermark_mask: e.target.value })}
                        placeholder="如 0.7,0.85,0.3,0.15 (右下角);多个用 ; 分隔" />
                    </div>
                  )}
                  {(form.ai_rewrite !== 'off' || form.ad_block === 'ai') && (
                    <div className="flex flex-col gap-1.5">
                      <Label>AI 模型(改写 + 广告识别共用)</Label>
                      <Select value={form.ai_provider_id} onValueChange={(v) => setForm({ ...form, ai_provider_id: v })}>
                        <SelectTrigger><SelectValue /></SelectTrigger>
                        <SelectContent>
                          {providers.map((p) => (
                            <SelectItem key={p.id} value={String(p.id)}>
                              {p.name}{p.provider_model ? ` · ${p.provider_model}` : ''}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {!providers.length && <p className="text-[11px] text-muted-foreground">先到 设置 → AI 设置 添加模型</p>}
                    </div>
                  )}
                  {form.ai_rewrite !== 'off' && (
                    <div className="flex flex-col gap-1.5">
                      <Label>改写提示词(选填,留空用默认)</Label>
                      <Textarea value={form.ai_prompt}
                        onChange={(e) => setForm({ ...form, ai_prompt: e.target.value })}
                        rows={2}
                        placeholder='如:改成新闻播报口吻,去掉表情符号;不填则用内置"保持原意换说法"' />
                    </div>
                  )}
                </section>

                <section className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <div className="flex flex-col gap-1.5">
                    <Label>延时搬运(秒,随机区间;0=立即)</Label>
                    <div className="flex gap-2">
                      <Input type="number" min="0" max="3600" step="1" aria-label="最小延时秒数" value={form.delay_min_s} onChange={(e) => setForm({ ...form, delay_min_s: e.target.value })} />
                      <Input type="number" min="0" max="3600" step="1" aria-label="最大延时秒数" value={form.delay_max_s} onChange={(e) => setForm({ ...form, delay_max_s: e.target.value })} />
                    </div>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label>备注(可选)</Label>
                    <Input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
                  </div>
                </section>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
                <Button onClick={doSave} disabled={busy}>{editRule ? '保存' : '创建'}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
          <Button variant="outline" onClick={load} disabled={loading}>
            <RefreshCw className="h-4 w-4" /> 刷新
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-3">
        {rows.map((r) => (
          <Card key={r.id}>
            <CardContent className="p-3 sm:p-4">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.name}</span>
                    {isRunning(r) ? <Badge>运行中</Badge> : <Badge variant="secondary">未运行</Badge>}
                    <Badge variant="outline">号:{accLabel(r.account_id)}</Badge>
                    {(r.sender_account_ids || []).length > 0 && (
                      <Badge variant="outline">发送号 ×{(r.sender_account_ids || []).length}</Badge>
                    )}
                    {(() => {
                      const poolIds = r.sender_account_ids || []
                      const active = (r.targets || []).filter((t) => t.status === 'active' || !t.status)
                      const badRoute = active.filter((t) => t.health).length
                      const cantPost = poolIds.filter((id) =>
                        active.some((t) => t.sender_status?.[String(id)]?.can_post === false),
                      ).length
                      return <>
                        {badRoute > 0 && <Badge variant="destructive">{badRoute} 条路线失效</Badge>}
                        {cantPost > 0 && <Badge variant="destructive">{cantPost} 个号无发帖权限</Badge>}
                      </>
                    })()}
                    {r.ai_rewrite && r.ai_rewrite !== 'off' && <Badge variant="outline">AI改写</Badge>}
                    {r.ad_block && r.ad_block !== 'off' && (
                      <Badge variant="outline">{r.ad_block === 'ai' ? 'AI拦广告' : '关键词拦广告'}</Badge>
                    )}
                    {r.watermark_mode && r.watermark_mode !== 'off' && (
                      <Badge variant="outline">{r.watermark_mode === 'auto' ? '自动去水印' : '固定区去水印'}</Badge>
                    )}
                    {(r.delay_max_s || 0) > 0 && (
                      <Badge variant="outline">{r.delay_min_s === r.delay_max_s ? `延时 ${r.delay_min_s}s` : `延时 ${r.delay_min_s}–${r.delay_max_s}s`}</Badge>
                    )}
                  </div>
                  <div className="mt-1.5 truncate text-sm text-muted-foreground">{routeText(r)}</div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {isRunning(r) ? (
                    <Button size="sm" variant="outline" onClick={() => toggleRun(r, false)}>
                      <Square className="h-4 w-4" /> 停止
                    </Button>
                  ) : (
                    <Button size="sm" onClick={() => toggleRun(r, true)}>
                      <Play className="h-4 w-4" /> 运行
                    </Button>
                  )}
                  <Button size="sm" variant="outline" disabled={checking === r.id} onClick={() => doCheck(r)} title="检测监听号/发送号是否还在频道且有发帖权限">
                    <ShieldCheck className="h-4 w-4" /> {checking === r.id ? '检测中…' : '检测'}
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openEdit(r)}>
                    <Pencil className="h-4 w-4" /> 编辑
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => doDeleteRule(r)}>
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        ))}
        {!loading && rows.length === 0 && (
          <p className="py-12 text-center text-sm text-muted-foreground">还没有搬运规则,点右上角「新建搬运」</p>
        )}
      </div>
    </div>
  )
}
