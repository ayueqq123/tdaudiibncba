import { useEffect, useState } from 'react'
import { ArrowRight, History, Plus, RefreshCw, Rocket, Trash2 } from 'lucide-react'
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

const EMPTY_FORM = { account_id: '', name: '', mode: 'copy', sync_edit: true, sync_delete: true, enabled: true, remark: '' }
const EMPTY_TF = { source_chat_id: '', source_topic_id: '', target_chat_id: '', target_topic_id: '', sender_user_ids: '', media_kinds: [] as string[], remark: '' }

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

  const [open, setOpen] = useState(false)
  const [editRule, setEditRule] = useState<CloneRule | null>(null)
  const [form, setForm] = useState<any>({ ...EMPTY_FORM })

  const [targetOpen, setTargetOpen] = useState(false)
  const [targetRule, setTargetRule] = useState<CloneRule | null>(null)
  const [tf, setTf] = useState<any>({ ...EMPTY_TF })

  const [verOpen, setVerOpen] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [verRule, setVerRule] = useState<CloneRule | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [r, a] = await Promise.all([tgApi.rules(), tgApi.accounts()])
      setAccounts(a)
      const detailed = await Promise.all(r.map((x) => tgApi.rule(x.id).catch(() => x)))
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

  async function doSave() {
    const acc = accounts.find((a) => a.id === +form.account_id)
    if ((!editRule && !acc) || !form.name) {
      toast.warning('账号/名称必填')
      return
    }
    try {
      if (editRule) {
        await tgApi.updateRule(editRule.id, {
          name: form.name,
          mode: form.mode,
          sync_edit: form.sync_edit,
          sync_delete: form.sync_delete,
          enabled: form.enabled,
          remark: form.remark || null,
        })
        toast.success('已保存,记得重新"发布"才会生效')
      } else {
        await tgApi.createRule({
          ...form,
          tenant_id: acc!.tenant_id,
          project_id: acc!.project_id,
          account_id: acc!.id,
        })
        toast.success('规则已创建,加完搬运路线后点"发布"生效')
      }
      setOpen(false)
      setEditRule(null)
      setForm({ ...EMPTY_FORM })
      load()
    } catch (e: any) {
      toast.error(e?.detail || '保存失败')
    }
  }

  async function doAddTarget() {
    if (!targetRule || !tf.source_chat_id || !tf.target_chat_id) {
      toast.warning('源群/目标群 ID 必填')
      return
    }
    try {
      const senders = tf.sender_user_ids
        .split(/[,\s]+/)
        .map((s: string) => s.trim())
        .filter(Boolean)
        .map(Number)
      if (senders.some((n: number) => !Number.isInteger(n) || n <= 0)) {
        toast.warning('发言人 ID 必须是正整数')
        return
      }
      const filters: any = {}
      if (senders.length) filters.sender_user_ids = senders
      if (tf.media_kinds.length) filters.media_kinds = tf.media_kinds
      await tgApi.addTarget(targetRule.id, {
        source_chat_id: +tf.source_chat_id,
        source_topic_id: tf.source_topic_id ? +tf.source_topic_id : null,
        target_chat_id: +tf.target_chat_id,
        target_topic_id: tf.target_topic_id ? +tf.target_topic_id : null,
        filters: Object.keys(filters).length ? filters : null,
        remark: tf.remark || null,
      })
      toast.success('路线已添加,点"发布"后生效')
      setTargetOpen(false)
      load()
    } catch (e: any) {
      toast.error(e?.detail || '添加失败')
    }
  }

  async function doPublish(r: CloneRule) {
    try {
      await tgApi.publishRule(r.id, r.current_version)
      try {
        await tgApi.issueCommand(r.account_id, { type: 'ReloadConfig' })
        toast.success('已发布并下发到账号')
      } catch {
        toast.success('已发布(账号刷新失败,可到账号页再试)')
      }
      load()
    } catch (e: any) {
      toast.error(e?.detail || '发布失败')
    }
  }

  async function doToggle(r: CloneRule, v: boolean) {
    try {
      await tgApi.updateRule(r.id, {
        name: r.name,
        mode: r.mode,
        sync_edit: r.sync_edit ?? true,
        sync_delete: r.sync_delete ?? true,
        enabled: v,
        remark: r.remark,
      })
      toast.success(v ? '已启用(发布/重发布后生效)' : '已停用(发布/重发布后生效)')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '操作失败')
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
    if (!confirm(`确定移除这条搬运路线(${t.source_chat_id} → ${t.target_chat_id})?`)) return
    try {
      await tgApi.retireTarget(r.id, t.id)
      toast.success('已移除,重新发布后生效')
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

  const accLabel = (id: number) => accounts.find((a) => a.id === id)?.phone || `#${id}`

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Clone 规则</h2>
          <p className="text-xs text-muted-foreground">每条规则=一个账号把「源群」的消息搬到「目标群」;改完点"发布"才会下发给账号执行</p>
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
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{editRule ? `编辑规则「${editRule.name}」` : '新建 Clone 规则'}</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                {!editRule && (
                  <div className="flex flex-col gap-1.5">
                    <Label>执行账号(用哪个号搬运)</Label>
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
                )}
                <div className="flex flex-col gap-1.5">
                  <Label>规则名称</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如:资源群搬运" />
                </div>
                <div className="flex items-center justify-between">
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
                  <div className="flex items-center gap-2">
                    <Label>启用</Label>
                    <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
                  </div>
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
                  <Label>备注</Label>
                  <Input value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={doSave}>{editRule ? '保存' : '创建'}</Button>
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
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{r.name}</span>
                    <Badge variant="outline">{accLabel(r.account_id)}</Badge>
                    <Badge variant={r.mode === 'copy' ? 'default' : 'warning'}>
                      {r.mode === 'copy' ? '复制重发' : '官方转发'}
                    </Badge>
                    {r.current_version > 0 ? (
                      <Badge variant="secondary">已发布 v{r.current_version}</Badge>
                    ) : (
                      <Badge variant="warning">未发布</Badge>
                    )}
                    {!r.enabled && <Badge variant="destructive">已停用</Badge>}
                  </div>
                  <div className="mt-1 text-xs text-muted-foreground">
                    {r.sync_edit === false ? '不同步编辑' : '同步编辑'} · {r.sync_delete === false ? '不同步删除' : '同步删除'}
                    {r.remark ? ` · ${r.remark}` : ''}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1.5">
                  <Switch checked={r.enabled} onCheckedChange={(v) => doToggle(r, v)} />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setEditRule(r)
                      setForm({
                        account_id: String(r.account_id),
                        name: r.name,
                        mode: r.mode,
                        sync_edit: r.sync_edit ?? true,
                        sync_delete: r.sync_delete ?? true,
                        enabled: r.enabled,
                        remark: r.remark || '',
                      })
                      setOpen(true)
                    }}
                  >
                    编辑
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setTargetRule(r)
                      setTf({ ...EMPTY_TF })
                      setTargetOpen(true)
                    }}
                  >
                    加路线
                  </Button>
                  <Button size="sm" onClick={() => doPublish(r)} title="把当前配置下发给账号,立即生效">
                    <Rocket className="h-4 w-4" /> 发布生效
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => openVersions(r)} title="发布历史">
                    <History className="h-4 w-4" />
                  </Button>
                  <Button size="sm" variant="destructive" onClick={() => doDeleteRule(r)} title="删除规则">
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="mt-3 flex flex-col gap-1.5">
                {(r.targets || []).map((t) => (
                  <div key={t.id} className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-1.5 text-sm">
                    <span className="font-mono text-xs">{t.source_chat_id}{t.source_topic_id ? `#${t.source_topic_id}` : ''}</span>
                    <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="font-mono text-xs">{t.target_chat_id}{t.target_topic_id ? `#${t.target_topic_id}` : ''}</span>
                    <span className="text-xs text-muted-foreground">{filterSummary(t)}</span>
                    {t.status !== 'active' && <Badge variant="warning">{t.status}</Badge>}
                    <Button size="sm" variant="ghost" className="ml-auto h-6 px-2" onClick={() => doRetireTarget(r, t)}>
                      <Trash2 className="h-3.5 w-3.5" />
                    </Button>
                  </div>
                ))}
                {!(r.targets || []).length && (
                  <div className="text-xs text-muted-foreground">还没有搬运路线,点"加路线"指定从哪个群搬到哪个群</div>
                )}
              </div>
            </CardContent>
          </Card>
        ))}
        {!rows.length && (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              还没有规则。点右上"新建规则",选账号→加路线(源群→目标群)→发布,就开始搬了
            </CardContent>
          </Card>
        )}
      </div>

      <Dialog open={targetOpen} onOpenChange={setTargetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>给「{targetRule?.name}」加一条搬运路线</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>源群 ID(从这个群搬出,-100 开头)</Label>
              <Input value={tf.source_chat_id} onChange={(e) => setTf({ ...tf, source_chat_id: e.target.value })} placeholder="-100xxxxxxxxxx" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>目标群 ID(搬到这里,-100 开头)</Label>
              <Input value={tf.target_chat_id} onChange={(e) => setTf({ ...tf, target_chat_id: e.target.value })} placeholder="-100xxxxxxxxxx" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1.5">
                <Label>源群话题 ID(可选)</Label>
                <Input value={tf.source_topic_id} onChange={(e) => setTf({ ...tf, source_topic_id: e.target.value })} />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label>目标话题 ID(可选)</Label>
                <Input value={tf.target_topic_id} onChange={(e) => setTf({ ...tf, target_topic_id: e.target.value })} />
              </div>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>只搬这些人的消息(可选)</Label>
              <Input
                value={tf.sender_user_ids}
                onChange={(e) => setTf({ ...tf, sender_user_ids: e.target.value })}
                placeholder="发言人 ID,逗号分隔;留空=搬全群"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>只搬这些类型(不勾=全部类型)</Label>
              <div className="grid grid-cols-3 gap-2">
                {MEDIA_KINDS.map(([k, label]) => (
                  <label key={k} className="flex items-center gap-1.5 text-sm">
                    <input
                      type="checkbox"
                      checked={tf.media_kinds.includes(k)}
                      onChange={(e) =>
                        setTf({
                          ...tf,
                          media_kinds: e.target.checked
                            ? [...tf.media_kinds, k]
                            : tf.media_kinds.filter((x: string) => x !== k),
                        })
                      }
                    />
                    {label}
                  </label>
                ))}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTargetOpen(false)}>
              取消
            </Button>
            <Button onClick={doAddTarget}>添加</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={verOpen} onOpenChange={setVerOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>「{verRule?.name}」发布历史</DialogTitle>
          </DialogHeader>
          <div className="max-h-96 overflow-y-auto rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>版本</TableHead>
                  <TableHead>发布时间</TableHead>
                  <TableHead>快照</TableHead>
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
