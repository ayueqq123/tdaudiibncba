import { useEffect, useState } from 'react'
import { Plus, RefreshCw } from 'lucide-react'
import { toast } from 'sonner'
import { tgApi, type Project, type Tenant } from '@/lib/api'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export default function ProjectsPage() {
  const [rows, setRows] = useState<Project[]>([])
  const [tenants, setTenants] = useState<Tenant[]>([])
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)
  const [form, setForm] = useState({ tenant_id: '', name: '', remark: '' })

  async function load() {
    setLoading(true)
    try {
      const [p, t] = await Promise.all([tgApi.projects(), tgApi.tenants()])
      setRows(p)
      setTenants(t)
    } catch (e: any) {
      toast.error(e?.detail || '加载失败')
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => {
    load()
  }, [])

  async function save() {
    if (!form.tenant_id || !form.name) {
      toast.warning('用户/名称必填')
      return
    }
    try {
      await tgApi.createProject({ tenant_id: +form.tenant_id, name: form.name, status: 1, remark: form.remark || null })
      toast.success('已创建')
      setOpen(false)
      setForm({ tenant_id: '', name: '', remark: '' })
      load()
    } catch (e: any) {
      toast.error(e?.detail || '保存失败')
    }
  }

  async function del(r: Project) {
    if (!confirm(`确认删除项目「${r.name}」?`)) return
    try {
      await tgApi.deleteProject(r.id)
      toast.success('已删除')
      load()
    } catch (e: any) {
      toast.error(e?.detail || '删除失败')
    }
  }

  const tenantName = (id: number) => tenants.find((t) => t.id === id)?.name ?? `#${id}`

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h2 className="text-lg font-semibold">项目</h2>
        <div className="flex gap-2">
          <Dialog open={open} onOpenChange={setOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus className="h-4 w-4" /> 新建项目
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>新建项目</DialogTitle>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>所属用户(租户)</Label>
                  <Select value={form.tenant_id} onValueChange={(v) => setForm({ ...form, tenant_id: v })}>
                    <SelectTrigger>
                      <SelectValue placeholder="选择用户" />
                    </SelectTrigger>
                    <SelectContent>
                      {tenants.map((t) => (
                        <SelectItem key={t.id} value={String(t.id)}>
                          {t.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label>名称</Label>
                  <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
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
                <Button onClick={save}>创建</Button>
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
              <TableHead>所属用户</TableHead>
              <TableHead>备注</TableHead>
              <TableHead className="w-24">操作</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows.map((r) => (
              <TableRow key={r.id}>
                <TableCell>{r.id}</TableCell>
                <TableCell>{r.name}</TableCell>
                <TableCell>{tenantName(r.tenant_id)}</TableCell>
                <TableCell>{r.remark || '-'}</TableCell>
                <TableCell>
                  <Button size="sm" variant="outline" onClick={() => del(r)}>
                    删除
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {!rows.length && (
              <TableRow>
                <TableCell colSpan={5} className="py-8 text-center text-muted-foreground">
                  暂无项目
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}
