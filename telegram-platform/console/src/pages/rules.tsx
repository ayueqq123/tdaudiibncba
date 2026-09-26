import { useEffect, useState } from 'react'
import { ArrowRight, History, Pencil, Play, Plus, RefreshCw, Square, Trash2 } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type CloneRule, type CloneTarget, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

const MEDIA_KINDS: [string, string][] = [
  ['text', '文字'], ['photo', '图片'], ['video', '视频'], ['gif', 'GIF'], ['voice', '语音'],
  ['audio', '音频'], ['document', '文件'], ['sticker', '贴纸'], ['poll', '投票'], ['contact', '联系人'], ['location', '位置'],
]
const KIND_LABEL: Record<string, string> = Object.fromEntries(MEDIA_KINDS)

const EMPTY_FORM = {
  account_id: '', name: '', mode: 'copy',
  sync_edit: true, sync_delete: true,
  source_chat_id: '', target_chat_id: '',
  sender_user_ids: '', media_kinds: [] as string[], remark: '',
}

function filterSummary(t: CloneTarget): string {
  const f = t.filters
  if (!f) return '全群全部消息'
  const parts: string[] = []
  if (f.sender_user_ids?.length) parts.push(`只搬 ${f.sender_user_ids.length} 个发言人`)
  if (f.media_kinds?.length) parts.push(`只搬 ${f.media_kinds.map((k: string) => KIND_LABEL[k] || k).join('/')}`)
  return parts.join(' · ') || '全群全部消息'
}

export default function RulesPage() {
  const [rows, setRows] = useState<CloneRule[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)

  const [open, setOpen] = useState(false)
  const [editRule, setEditRule] = useState<CloneRule | null>(null)
  const [form, setForm] = useState<any>({ ...EMPTY_FORM })

  const [verOpen, setVerOpen] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [verRule, setVerRule] = useState<CloneRule | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [r, a] = await Promise.all([tgApi.rules(), tgApi.accounts()])
      setAccounts(a)
      const detailed = await Promise.all(r.map((x) => tgApi.rule(x.id).catch(() => x)))
      detailed.sort((x, y) => x.id - y.id)
      setRows(detailed)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  // 把规则配置下发到执行账号并让其立即生效
  async function applyToWorker(ruleId: number, version: number, accountId: number) {
    const v = await tgApi.publishRule(ruleId, version)
    await tgApi.issueCommand(accountId, { type: 'ReloadConfig' })
    return v
  }

  const isRunning = (r: CloneRule) => r.enabled && r.current_version > 0

  async function doSave() {
    const acc = accounts.find((a) => a.id === +form.account_id)
    if (!form.name) return toast.warning('名称必填')
    if (!editRule && !acc) return toast.warning('请选择执行账号')
    if (!editRule && (!form.source_chat_id || !form.target_chat_id)) return toast.warning('源群/目标群 ID 必填')
    const senders = form.sender_user_ids
      .split(/[,\s]+/)
      .map((s: string) => s.trim())
      .filter(Boolean)
      .map(Number)
    if (senders.some((n: number) => !Number.isInteger(n) || n <= 0)) return toast.warning('发言人 ID 必须是正整数')

    setBusy(true)
    try {
      if (editRule) {
        await tgApi.updateRule(editRule.id, {
          name: form.name,
          mode: form.mode,
          sync_edit: form.sync_edit,
          sync_delete: form.sync_delete,
          enabled: editRule.enabled,
          remark: form.remark || null,
        })
        if (editRule.current_version > 0) {
          await applyToWorker(editRule.id, editRule.current_version, editRule.account_id)
          toast.success('已保存并生效')
        } else {
          toast.success('已保存')
        }
      } else {
        await tgApi.createRule({
          account_id: acc!.id,
          tenant_id: acc!.tenant_id,
          project_id: acc!.project_id,
          name: form.name,
          mode: form.mode,
          sync_edit: form.sync_edit,
          sync_delete: form.sync_delete,
          enabled: true,
          remark: form.remark || null,
        })
        const list = await tgApi.rules()
        const created = list.filter((x) => x.name === form.name).sort((a, b) => b.id - a.id)[0]
        const filters: any = {}
        if (senders.length) filters.sender_user_ids = senders
        if (form.media_kinds.length) filters.media_kinds = form.media_kinds
        const toRef = (s: string) => (/^-?\d+$/.test(s.trim()) ? Number(s.trim()) : s.trim())
        await tgApi.addTarget(created.id, {
          source_chat_id: toRef(form.source_chat_id),
          target_chat_id: toRef(form.target_chat_id),
          filters: Object.keys(filters).length ? filters : null,
        })
        toast.success('规则已建好,点"运行"开始搬运')
      }
      setOpen(false)
      setEditRule(null)
      setForm({ ...EMPTY_FORM })
      load()
    } catch (e: any) {
      toast.error(e?.detail || '保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function doRun(r: CloneRule) {
    setBusy(true)
    try {
      await tgApi.updateRule(r.id, {
        name: r.name, mode: r.mode,
        sync_edit: r.sync_edit ?? true, sync_delete: r.sync_delete ?? true,
        enabled: true, remark: r.remark,
      })
      await applyToWorker(r.id, r.current_version, r.account_id)
      toast.success('已下发,账号开始搬运')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '启动失败')
    } finally {
      setBusy(false)
    }
  }

  async function doStop(r: CloneRule) {
    setBusy(true)
    try {
      await tgApi.updateRule(r.id, {
        name: r.name, mode: r.mode,
        sync_edit: r.sync_edit ?? true, sync_delete: r.sync_delete ?? true,
        enabled: false, remark: r.remark,
      })
      await applyToWorker(r.id, r.current_version, r.account_id)
      toast.success('已停止搬运')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '停止失败')
    } finally {
      setBusy(false)
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

  async function doRetireTarget(r: CloneRule, t: CloneTarget) {
    if (!confirm(`移除路线 ${t.source_chat_id} → ${t.target_chat_id}?`)) return
    try {
      await tgApi.retireTarget(r.id, t.id)
      if (isRunning(r)) await applyToWorker(r.id, r.current_version, r.account_id)
      toast.success('路线已移除')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '移除失败')
    }
  }

  async function openVersions(r: CloneRule) {
    try {
      setVersions(await tgApi.ruleVersions(r.id))
      setVerRule(r)
      setVerOpen(true)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    }
  }

  const accLabel = (id: number) => {
    const a = accounts.find((x) => x.id === id)
    return `号:${a?.username ? '@' + a.username : a?.phone || a?.telegram_user_id || id}`
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">Clone 规则</h2>
          <p className="text-xs text-muted-foreground">一条规则=「哪个号」把「哪个群」搬到「哪个群」,点运行就开始</p>
        </div>
        <div className="flex gap-2">
          <Dialog
            open={open}
            onOpenChange={(v) => {
              setOpen(v)
              if (!v) {
                setEditRule(null)
                setForm({ ...EMPTY_FORM })
              }
            }}
          >
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> 新建规则
              </Button>
            </DialogTrigger>
            <DialogContent className="max-h-[90vh] overflow-y-auto">
              <DialogHeader>
                <DialogTitle>{editRule ? `编辑「${editRule.name}」` : '新建搬运规则'}</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                {!editRule && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <Label>用哪个号搬运</Label>
                      <Select value={form.account_id} onValueChange={(v) => setForm({ ...form, account_id: v })}>
                        <SelectTrigger>
                          <SelectValue placeholder="选择账号" />
                        </SelectTrigger>
                        <SelectContent>
                          {accounts.map((a) => (
                            <SelectItem key={a.id} value={String(a.id)}>
                              {a.phone || String(a.telegram_user_id || a.id)}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                      <div className="flex flex-col gap-1.5">
                        <Label>源群(ID 或链接)</Label>
                        <Input
                          value={form.source_chat_id}
                          onChange={(e) => setForm({ ...form, source_chat_id: e.target.value })}
                          placeholder="-100 开头 ID 或 t.me/xx 链接"
                        />
                      </div>
                      <div className="flex flex-col gap-1.5">
                        <Label>目标群(ID 或链接)</Label>
                        <Input
                          value={form.target_chat_id}
                          onChange={(e) => setForm({ ...form, target_chat_id: e.target.value })}
                          placeholder="-100 开头 ID 或 t.me/xx、t.me/+邀请链接"
                        />
                      </div>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>只搬这些人的消息(可选)</Label>
                      <Input
                        value={form.sender_user_ids}
                        onChange={(e) => setForm({ ...form, sender_user_ids: e.target.value })}
                        placeholder="发言人 ID 逗号分隔;留空=搬全群"
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label>只搬这些类型(不勾=全部)</Label>
                      <div className="grid grid-cols-3 gap-2 sm:grid-cols-4">
                        {MEDIA_KINDS.map(([k, label]) => (
                          <label key={k} className="flex items-center gap-1.5 text-sm">
                            <input
                              type="checkbox"
                              checked={form.media_kinds.includes(k)}
                              onChange={(e) =>
                                setForm({
                                  ...form,
                                  media_kinds: e.target.checked
                                    ? [...form.media_kinds, k]
                                    : form.media_kinds.filter((x: string) => x !== k),
                                })
                              }
                            />
                            {label}
                          </label>
                        ))}
                      </div>
                    </div>
                  </>
                )}
                <div className="flex flex-col gap-1.5">
                  <Label>规则名称</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如:资源群搬运" />
                </div>
                <div className="flex items-center gap-2">
                  <Label>搬运方式</Label>
                  <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                    <SelectTrigger className="w-44">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="copy">复制重发(看不出搬运)</SelectItem>
                      <SelectItem value="forward">官方转发(带来源)</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-center gap-6">
                  <div className="flex items-center gap-2">
                    <Label>源群编辑→跟着改</Label>
                    <Switch checked={form.sync_edit} onCheckedChange={(v) => setForm({ ...form, sync_edit: v })} />
                  </div>
                  <div className="flex items-center gap-2">
                    <Label>源群删除→跟着删</Label>
                    <Switch checked={form.sync_delete} onCheckedChange={(v) => setForm({ ...form, sync_delete: v })} />
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>备注(可选)</Label>
                  <Input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={doSave} disabled={busy}>
                  {editRule ? '保存' : '创建'}
                </Button>
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
                    {isRunning(r) ? (
                      <Badge>运行中</Badge>
                    ) : (
                      <Badge variant="secondary">未运行</Badge>
                    )}
                    <Badge variant="outline">{accLabel(r.account_id)}</Badge>
                    <Badge variant={r.mode === 'copy' ? 'default' : 'warning'}>
                      {r.mode === 'copy' ? '复制重发' : '官方转发'}
                    </Badge>
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {r.sync_edit === false ? '不同步编辑' : '同步编辑'} · {r.sync_delete === false ? '不同步删除' : '同步删除'}
                    {r.remark ? ` · ${r.remark}` : ''}
                  </div>
                </div>
                <div className="flex shrink-0 flex-wrap items-center gap-1.5">
                  {isRunning(r) ? (
                    <Button size="sm" variant="outline" onClick={() => doStop(r)} disabled={busy}>
                      <Square className="h-4 w-4" /> 停止
                    </Button>
                  ) : (
                    <Button size="sm" onClick={() => doRun(r)} disabled={busy}>
                      <Play className="h-4 w-4" /> 运行
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditRule(r)
                      setForm({
                        ...EMPTY_FORM,
                        account_id: String(r.account_id),
                        name: r.name,
                        mode: r.mode,
                        sync_edit: r.sync_edit ?? true,
                        sync_delete: r.sync_delete ?? true,
                        remark: r.remark || '',
                      })
                      setOpen(true)
                    }}
                  >
                    <Pencil className="h-4 w-4" /> 编辑
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openVersions(r)} title="历史版本">
                    <History className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => doDeleteRule(r)} title="删除规则">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex flex-col gap-1.5">
                {(r.targets || [])
                  .filter((t) => t.status === 'active' || !t.status)
                  .map((t) => (
                    <div key={t.id} className="flex flex-wrap items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-sm">
                      <span className="break-all font-mono text-xs">{t.source_chat_id}</span>
                      <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                      <span className="break-all font-mono text-xs">{t.target_chat_id}</span>
                      <span className="text-xs text-muted-foreground">{filterSummary(t)}</span>
                      {(r.targets || []).length > 1 && (
                        <Button size="sm" variant="ghost" className="ml-auto h-6 px-2" onClick={() => doRetireTarget(r, t)}>
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  ))}
                {!(r.targets || []).filter((t) => t.status === 'active' || !t.status).length && (
                  <div className="text-xs text-muted-foreground">还没有搬运路线</div>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
        {!rows.length && (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              还没有规则。点右上"新建规则":选账号 → 填源群/目标群 → 创建 → 运行,就开始搬了
            </CardContent>
          </Card>
        )}
      </div>

      <Dialog open={verOpen} onOpenChange={setVerOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>「{verRule?.name}」历史版本</DialogTitle>
          </DialogHeader>
          <div className="max-h-96 overflow-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>版本</TableHead>
                  <TableHead>生效时间</TableHead>
                  <TableHead>配置快照</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {versions.map((v: any) => (
                  <TableRow key={v.id}>
                    <TableCell>v{v.version}</TableCell>
                    <TableCell className="text-muted-foreground">{v.published_at?.slice(0, 19).replace('T', ' ')}</TableCell>
                    <TableCell className="max-w-md truncate font-mono text-xs">{JSON.stringify(v.snapshot)}</TableCell>
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
