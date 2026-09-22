import { useEffect, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type CloneRule, type TgAccount } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function RulesPage() {
  const [rows, setRows] = useState<CloneRule[]>([])
  const [accounts, setAccounts] = useState<TgAccount[]>([])
  const [loading, setLoading] = useState(false)

  const [open, setOpen] = useState(false)
  const [form, setForm] = useState<any>({ account_id: '', name: '', mode: 'copy', enabled: true, remark: '' })

  const [targetOpen, setTargetOpen] = useState(false)
  const [targetRule, setTargetRule] = useState<CloneRule | null>(null)
  const [tf, setTf] = useState<any>({ source_chat_id: '', source_topic_id: '', target_chat_id: '', target_topic_id: '', sender_user_ids: '', remark: '' })

  const [verOpen, setVerOpen] = useState(false)
  const [versions, setVersions] = useState<any[]>([])
  const [verRule, setVerRule] = useState<CloneRule | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [r, a] = await Promise.all([tgApi.rules(), tgApi.accounts()])
      setRows(r)
      setAccounts(a)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function doCreate() {
    const acc = accounts.find((a) => a.id === +form.account_id)
    if (!acc || !form.name) {
      toast.warning('账号/名称必填')
      return
    }
    try {
      await tgApi.createRule({
        ...form,
        tenant_id: acc.tenant_id,
        project_id: acc.project_id,
        account_id: acc.id,
      })
      toast.success('规则已创建,添加目标后点"发布"生效')
      setOpen(false)
      setForm({ account_id: '', name: '', mode: 'copy', enabled: true, remark: '' })
      load()
    } catch (e: any) {
      toast.error(e?.detail || '创建失败')
    }
  }

  async function doAddTarget() {
    if (!targetRule || !tf.source_chat_id || !tf.target_chat_id) {
      toast.warning('源/目标 chat_id 必填')
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
      await tgApi.addTarget(targetRule.id, {
        source_chat_id: +tf.source_chat_id,
        source_topic_id: tf.source_topic_id ? +tf.source_topic_id : null,
        target_chat_id: +tf.target_chat_id,
        target_topic_id: tf.target_topic_id ? +tf.target_topic_id : null,
        filters: senders.length ? { sender_user_ids: senders } : null,
        remark: tf.remark || null,
      })
      toast.success('目标已添加')
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
        toast.success('已发布并刷新到 worker')
      } catch {
        toast.success('已发布(请稍后手动到账号页刷新规则)')
      }
      load()
    } catch (e: any) {
      toast.error(e?.detail || '发布失败')
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
        <h2 className="text-lg font-semibold">Clone 规则</h2>
        <div className="flex gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> 新建规则
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>新建 Clone 规则</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
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
                <div className="flex flex-col gap-1.5">
                  <Label>规则名称</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如:资源群搬运" />
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Label>模式</Label>
                    <Select value={form.mode} onValueChange={(v) => setForm({ ...form, mode: v })}>
                      <SelectTrigger className="w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="copy">copy(重发)</SelectItem>
                        <SelectItem value="forward">forward(转发)</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-center gap-2">
                    <Label>启用</Label>
                    <Switch checked={form.enabled} onCheckedChange={(v) => setForm({ ...form, enabled: v })} />
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
                <Button onClick={doCreate}>创建</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
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
              <TableHead>名称</TableHead>
              <TableHead>账号</TableHead>
              <TableHead>模式</TableHead>
              <TableHead>启用</TableHead>
              <TableHead>版本</TableHead>
              <TableHead className="w-64">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell>{r.name}</TableCell>
                <TableCell>{accLabel(r.account_id)}</TableCell>
                <TableCell>
                  <Badge variant={r.mode === 'copy' ? 'default' : 'warning'}>{r.mode}</Badge>
                </TableCell>
                <TableCell>{r.enabled ? '是' : '否'}</TableCell>
                <TableCell>v{r.current_version}</TableCell>
                <TableCell>
                  <div className="flex gap-1.5">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => {
                        setTargetRule(r)
                        setTf({ source_chat_id: '', source_topic_id: '', target_chat_id: '', target_topic_id: '', sender_user_ids: '', remark: '' })
                        setTargetOpen(true)
                      }}
                    >
                      加目标
                    </Button>
                    <Button size="sm" onClick={() => doPublish(r)}>
                      发布
                    </Button>
                    <Button size="sm" variant="outline" onClick={() => openVersions(r)}>
                      版本
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={7} className="py-8 text-center text-muted-foreground">
                  暂无规则,点右上"新建规则"创建
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <Dialog open={targetOpen} onOpenChange={setTargetOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>为规则「{targetRule?.name}」添加搬运目标</DialogTitle>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label>源群 chat_id(从哪里搬)</Label>
              <Input value={tf.source_chat_id} onChange={(e) => setTf({ ...tf, source_chat_id: e.target.value })} placeholder="-100xxxxxxxxxx" />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>源话题 topic_id(可选)</Label>
              <Input value={tf.source_topic_id} onChange={(e) => setTf({ ...tf, source_topic_id: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>目标群 chat_id(搬到哪里)</Label>
              <Input value={tf.target_chat_id} onChange={(e) => setTf({ ...tf, target_chat_id: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>目标话题 topic_id(可选)</Label>
              <Input value={tf.target_topic_id} onChange={(e) => setTf({ ...tf, target_topic_id: e.target.value })} />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>只克隆这些发言人 ID(可选,逗号分隔)</Label>
              <Input
                value={tf.sender_user_ids}
                onChange={(e) => setTf({ ...tf, sender_user_ids: e.target.value })}
                placeholder="留空=搬全群;填后只搬这些用户的发言"
              />
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
            <DialogTitle>规则「{verRule?.name}」发布历史</DialogTitle>
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
