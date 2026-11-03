import { useEffect, useState } from 'react'
import { Copy, Pencil, Plus, RefreshCw, Trash2, Zap } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type AiGatewayToken, type AiProvider } from '@/lib/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'

const EMPTY_FORM = {
  name: '',
  base_url: '',
  provider_model: '',
  provider_key: '',
  extra_body: '',
  remark: '',
}
const EMPTY_GATEWAY_FORM = { name: '', ai_provider_id: '', remark: '' }

export default function AiProvidersPage() {
  const [rows, setRows] = useState<AiProvider[]>([])
  const [gatewayTokens, setGatewayTokens] = useState<AiGatewayToken[]>([])
  const [scope, setScope] = useState<{ tenant_id: number; project_id: number } | null>(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [testing, setTesting] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [edit, setEdit] = useState<AiProvider | null>(null)
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [gatewayOpen, setGatewayOpen] = useState(false)
  const [gatewayEdit, setGatewayEdit] = useState<AiGatewayToken | null>(null)
  const [gatewayForm, setGatewayForm] = useState({ ...EMPTY_GATEWAY_FORM })
  const [gatewayBusy, setGatewayBusy] = useState(false)
  const [revealedToken, setRevealedToken] = useState('')
  const [revealOpen, setRevealOpen] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const ws = scope ?? (await tgApi.ensureWorkspace())
      if (!scope) setScope(ws)
      const [providers, tokens] = await Promise.all([
        tgApi.aiProviders({ tenant_id: ws.tenant_id, project_id: ws.project_id }),
        tgApi.aiGatewayTokens({ tenant_id: ws.tenant_id, project_id: ws.project_id }),
      ])
      setRows(providers)
      setGatewayTokens(tokens)
    } catch (e: any) {
      toast.error(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function openCreate() {
    setEdit(null)
    setForm({ ...EMPTY_FORM })
    setOpen(true)
  }

  function openEdit(p: AiProvider) {
    setEdit(p)
    setForm({
      name: p.name, base_url: p.base_url, provider_model: p.provider_model || '',
      provider_key: '',
      extra_body: p.extra_body ? JSON.stringify(p.extra_body, null, 2) : '',
      remark: p.remark || '',
    })
    setOpen(true)
  }

  function parseExtraBody(raw: string): Record<string, unknown> | null | undefined {
    if (!raw.trim()) return null
    let parsed: unknown
    try {
      parsed = JSON.parse(raw)
    } catch {
      toast.error('附加请求参数必须是合法 JSON')
      return undefined
    }
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      toast.error('附加请求参数必须是 JSON 对象')
      return undefined
    }
    return parsed as Record<string, unknown>
  }

  function closeThinking() {
    let extra: Record<string, unknown> = {}
    const raw = form.extra_body.trim()
    if (raw) {
      try {
        const parsed: unknown = JSON.parse(raw)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
          toast.error('附加请求参数必须是 JSON 对象')
          return
        }
        extra = parsed as Record<string, unknown>
      } catch {
        if (!window.confirm('当前附加参数不是有效 JSON，是否覆盖为关闭思考参数？')) return
      }
    }
    setForm({
      ...form,
      extra_body: JSON.stringify({ ...extra, reasoning_effort: 'none' }, null, 2),
    })
  }

  async function save() {
    if (!form.name.trim() || !form.base_url.trim()) {
      toast.error('名称和 base_url 必填')
      return
    }
    const extraBody = parseExtraBody(form.extra_body)
    if (extraBody === undefined) return
    setBusy(true)
    try {
      if (edit) {
        const body: any = {
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          remark: form.remark || null,
          extra_body: extraBody,
        }
        body.provider_model = form.provider_model.trim() || null
        if (form.provider_key.trim()) body.provider_key = form.provider_key.trim()
        await tgApi.updateAiProvider(edit.id, body)
        toast.success('已保存')
      } else {
        if (!form.provider_model.trim() || !form.provider_key.trim()) {
          toast.error('新建时模型名和 API Key 必填')
          return
        }
        await tgApi.createAiProvider({
          tenant_id: scope!.tenant_id,
          project_id: scope!.project_id,
          name: form.name.trim(),
          base_url: form.base_url.trim(),
          provider_model: form.provider_model.trim(),
          provider_key: form.provider_key.trim(),
          extra_body: extraBody,
          remark: form.remark || null,
        })
        toast.success('已创建')
      }
      setOpen(false)
      await load()
    } catch (e: any) {
      toast.error(e?.message || '保存失败')
    } finally {
      setBusy(false)
    }
  }

  async function remove(p: AiProvider) {
    if (!confirm(`确定删除配置「${p.name}」?引用它的规则会回落到目标群 AI 配置。`)) return
    try {
      await tgApi.deleteAiProvider(p.id)
      toast.success('已删除')
      await load()
    } catch (e: any) {
      toast.error(e?.message || '删除失败')
    }
  }

  async function test(p: AiProvider) {
    setTesting(p.id)
    try {
      const r = await tgApi.testAiProvider(p.id)
      if (r.ok) toast.success(`${p.name}:连通正常${r.output ? ` · ${r.output.slice(0, 40)}` : ''}`)
      else toast.error(`${p.name}:调用失败 ${r.error || ''}`)
    } catch (e: any) {
      toast.error(e?.message || '测试失败')
    } finally {
      setTesting(null)
    }
  }

  function openCreateGatewayToken() {
    setGatewayEdit(null)
    setGatewayForm({
      ...EMPTY_GATEWAY_FORM,
      ai_provider_id: rows[0] ? String(rows[0].id) : '',
    })
    setGatewayOpen(true)
  }

  function openEditGatewayToken(token: AiGatewayToken) {
    setGatewayEdit(token)
    setGatewayForm({
      name: token.name,
      ai_provider_id: String(token.ai_provider_id),
      remark: token.remark || '',
    })
    setGatewayOpen(true)
  }

  async function saveGatewayToken() {
    const providerId = Number(gatewayForm.ai_provider_id)
    if (!gatewayForm.name.trim() || !providerId) {
      toast.error('名称和绑定配置必填')
      return
    }
    setGatewayBusy(true)
    try {
      if (gatewayEdit) {
        await tgApi.updateAiGatewayToken(gatewayEdit.id, {
          name: gatewayForm.name.trim(),
          ai_provider_id: providerId,
          remark: gatewayForm.remark || null,
        })
        toast.success('令牌已保存')
      } else {
        const created = await tgApi.createAiGatewayToken({
          tenant_id: scope!.tenant_id,
          project_id: scope!.project_id,
          name: gatewayForm.name.trim(),
          ai_provider_id: providerId,
          remark: gatewayForm.remark || null,
        })
        setRevealedToken(created.token)
        setRevealOpen(true)
        toast.success('令牌已创建，请立即复制保存')
      }
      setGatewayOpen(false)
      await load()
    } catch (e: any) {
      toast.error(e?.message || '保存令牌失败')
    } finally {
      setGatewayBusy(false)
    }
  }

  async function toggleGatewayToken(token: AiGatewayToken) {
    try {
      await tgApi.updateAiGatewayToken(token.id, {
        status: token.status === 'active' ? 'disabled' : 'active',
      })
      toast.success(token.status === 'active' ? '令牌已停用' : '令牌已启用')
      await load()
    } catch (e: any) {
      toast.error(e?.message || '更新令牌状态失败')
    }
  }

  async function removeGatewayToken(token: AiGatewayToken) {
    if (!confirm(`确定删除外部调用令牌「${token.name}」？`)) return
    try {
      await tgApi.deleteAiGatewayToken(token.id)
      toast.success('令牌已删除')
      await load()
    } catch (e: any) {
      toast.error(e?.message || '删除令牌失败')
    }
  }

  async function copyRevealedToken() {
    try {
      await navigator.clipboard.writeText(revealedToken)
      toast.success('已复制令牌')
    } catch {
      toast.error('复制失败，请手动复制')
    }
  }

  return (
    <div className="space-y-6">
      <section className="space-y-4">
        <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">AI 设置</h1>
          <p className="text-sm text-muted-foreground">
            统一的模型配置池(OpenAI 兼容接口)。炒群、群搬运、频道搬运都从这里引用同一套 base_url / key / model。
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={load} disabled={loading}>
            <RefreshCw className={loading ? 'animate-spin' : ''} size={16} />
          </Button>
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button size="sm" onClick={openCreate}>
                <Plus size={16} className="mr-1" /> 新增配置
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>{edit ? `编辑配置 · ${edit.name}` : '新增 AI 配置'}</DialogTitle>
              </DialogHeader>
              <div className="space-y-3 py-2">
                <div className="flex flex-col gap-1.5">
                  <Label>名称</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 DeepSeek 中转" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>Base URL</Label>
                  <Input value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://api.openai.com 或中转地址" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>模型名</Label>
                  <Input value={form.provider_model} onChange={(e) => setForm({ ...form, provider_model: e.target.value })} placeholder="如 gpt-4o-mini / deepseek-chat" />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>API Key{edit ? '(留空不更换)' : ''}</Label>
                  <Input type="password" value={form.provider_key} onChange={(e) => setForm({ ...form, provider_key: e.target.value })} placeholder={edit?.has_provider_key ? '已配置 · 留空不变' : 'sk-...'} />
                </div>
                <div className="flex flex-col gap-1.5">
                  <div className="flex items-center justify-between">
                    <Label>附加请求参数（JSON，选填）</Label>
                    <Button type="button" variant="outline" size="sm" onClick={closeThinking}>
                      关闭思考
                    </Button>
                  </div>
                  <Textarea
                    rows={4}
                    value={form.extra_body}
                    onChange={(e) => setForm({ ...form, extra_body: e.target.value })}
                    placeholder={'例如：{"reasoning_effort":"none"}'}
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted-foreground">
                    会合并进每次请求体，例如关闭思考 {'{"reasoning_effort":"none"}'}；不同中转写法可能不同（如 Qwen 用 enable_thinking:false）
                  </p>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>备注</Label>
                  <Textarea rows={2} value={form.remark} onChange={(e) => setForm({ ...form, remark: e.target.value })} />
                </div>
              </div>
              <DialogFooter>
                <Button variant="outline" onClick={() => setOpen(false)}>取消</Button>
                <Button onClick={save} disabled={busy}>{busy ? '保存中...' : '保存'}</Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
        </div>

        {rows.length === 0 && !loading ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            还没有配置。点右上角「新增配置」添加一个 OpenAI 兼容接口,然后在克隆/搬运规则里选它。
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-3">
          {rows.map((p) => (
            <Card key={p.id}>
              <CardContent className="flex items-center justify-between gap-3 py-4">
                <div className="min-w-0 space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-medium">{p.name}</span>
                    <Badge variant={p.status === 'active' ? 'default' : 'secondary'}>
                      {p.status === 'active' ? '启用' : p.status}
                    </Badge>
                    {p.has_provider_key ? <Badge variant="outline">已配 Key</Badge> : <Badge variant="destructive">缺 Key</Badge>}
                    {p.extra_body?.reasoning_effort === 'none' ? <Badge variant="outline">已关闭思考</Badge> : null}
                  </div>
                  <div className="truncate text-xs text-muted-foreground">
                    {p.base_url} · {p.provider_model || '未设模型'}{p.remark ? ` · ${p.remark}` : ''}
                  </div>
                </div>
                <div className="flex shrink-0 gap-2">
                  <Button variant="outline" size="sm" onClick={() => test(p)} disabled={testing === p.id}>
                    <Zap size={14} className="mr-1" />{testing === p.id ? '测试中...' : '测试'}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => openEdit(p)}>
                    <Pencil size={14} />
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => remove(p)}>
                    <Trash2 size={14} />
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
      </section>

      <section className="space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">外部项目调用（AI 网关）</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              绑定配置变更后会立即对外部项目生效，无需重启。令牌仅在创建时显示一次，请妥善保存。
            </p>
          </div>
          <Button size="sm" onClick={openCreateGatewayToken} disabled={rows.length === 0}>
            <Plus size={16} className="mr-1" /> 新建令牌
          </Button>
        </div>

        {gatewayTokens.length === 0 ? (
          <Card>
            <CardContent className="py-8 text-center text-sm text-muted-foreground">
              暂无外部调用令牌。请先创建 AI 配置，再为外部项目创建网关令牌。
            </CardContent>
          </Card>
        ) : (
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[920px] text-sm">
              <thead className="bg-muted/50 text-left">
                <tr>
                  <th className="px-3 py-2 font-medium">名称</th>
                  <th className="px-3 py-2 font-medium">令牌前缀</th>
                  <th className="px-3 py-2 font-medium">绑定配置</th>
                  <th className="px-3 py-2 font-medium">状态</th>
                  <th className="px-3 py-2 font-medium">调用次数</th>
                  <th className="px-3 py-2 font-medium">最后调用</th>
                  <th className="px-3 py-2 font-medium">操作</th>
                </tr>
              </thead>
              <tbody>
                {gatewayTokens.map((token) => (
                  <tr key={token.id} className="border-t">
                    <td className="px-3 py-2 font-medium">{token.name}</td>
                    <td className="px-3 py-2 font-mono text-xs">{token.token_prefix}…</td>
                    <td className="px-3 py-2">{token.provider_name || '配置已删除'}</td>
                    <td className="px-3 py-2">
                      <Badge variant={token.status === 'active' ? 'default' : 'secondary'}>
                        {token.status === 'active' ? '启用' : '停用'}
                      </Badge>
                    </td>
                    <td className="px-3 py-2">{token.call_count}</td>
                    <td className="px-3 py-2 text-xs text-muted-foreground">
                      {token.last_used_time ? new Date(token.last_used_time).toLocaleString() : '从未调用'}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex gap-1">
                        <Button variant="outline" size="sm" onClick={() => openEditGatewayToken(token)}>
                          <Pencil size={14} />
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => void toggleGatewayToken(token)}>
                          {token.status === 'active' ? '停用' : '启用'}
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => void removeGatewayToken(token)}>
                          <Trash2 size={14} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <Dialog open={gatewayOpen} onOpenChange={setGatewayOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{gatewayEdit ? `编辑外部令牌 · ${gatewayEdit.name}` : '新建外部调用令牌'}</DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <div className="flex flex-col gap-1.5">
              <Label>名称</Label>
              <Input
                value={gatewayForm.name}
                onChange={(e) => setGatewayForm({ ...gatewayForm, name: e.target.value })}
                placeholder="如 comment_bot"
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>绑定 AI 配置</Label>
              <select
                className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                value={gatewayForm.ai_provider_id}
                onChange={(e) => setGatewayForm({ ...gatewayForm, ai_provider_id: e.target.value })}
              >
                <option value="">请选择配置</option>
                {rows.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name} · {provider.provider_model || '未设置模型'}
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label>备注</Label>
              <Textarea
                rows={2}
                value={gatewayForm.remark}
                onChange={(e) => setGatewayForm({ ...gatewayForm, remark: e.target.value })}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setGatewayOpen(false)}>取消</Button>
            <Button onClick={saveGatewayToken} disabled={gatewayBusy || rows.length === 0}>
              {gatewayBusy ? '保存中...' : '保存'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={revealOpen}
        onOpenChange={(open) => {
          setRevealOpen(open)
          if (!open) setRevealedToken('')
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>AI 网关令牌已创建</DialogTitle>
          </DialogHeader>
          <p className="text-sm text-muted-foreground">
            令牌只显示这一次，请立即复制保存。以后无法再次查看完整令牌。
          </p>
          <div className="flex gap-2">
            <Input value={revealedToken} readOnly className="font-mono text-xs" />
            <Button variant="outline" onClick={copyRevealedToken} aria-label="复制令牌">
              <Copy size={16} />
            </Button>
          </div>
          <div className="space-y-1 rounded-md bg-muted/50 p-3 text-sm">
            <p>Base URL：<code>https://ggyzn1.top/ai-gw/v1</code></p>
            <p>API Key：使用此令牌。</p>
            <p>Model：可填写任意值，网关会替换为绑定配置中的模型。</p>
          </div>
          <DialogFooter>
            <Button onClick={() => {
              setRevealOpen(false)
              setRevealedToken('')
            }}>完成</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
