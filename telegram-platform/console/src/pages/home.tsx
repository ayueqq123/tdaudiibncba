import { useEffect, useState } from 'react'
import { tgApi } from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export default function HomePage() {
  const [s, setS] = useState({ accounts: 0, running: 0, deliveries: 0, succeeded: 0, pending: 0, commands: 0 })

  useEffect(() => {
    Promise.all([tgApi.accounts(), tgApi.deliveries(), tgApi.approvals({ status: 'pending' }), tgApi.commands()])
      .then(([acc, del, appr, cmd]) => {
        setS({
          accounts: acc.length,
          running: acc.filter((a) => a.desired_status === 'running').length,
          deliveries: del.length,
          succeeded: del.filter((d) => d.status === 'succeeded').length,
          pending: appr.length,
          commands: cmd.length,
        })
      })
      .catch(() => {})
  }, [])

  const cards = [
    { title: 'TG 账号', v: `${s.running}/${s.accounts}`, sub: '运行中 / 总数' },
    { title: '投递任务', v: `${s.succeeded}/${s.deliveries}`, sub: '成功 / 总数' },
    { title: '待审批', v: String(s.pending), sub: 'AI 回复候选' },
    { title: '运行时命令', v: String(s.commands), sub: '累计下发' },
  ]

  return (
    <div>
      <Card className="mb-4">
        <CardHeader>
          <CardTitle>TG 自动化运营平台</CardTitle>
          <p className="text-sm text-muted-foreground">多账号 Userbot · 消息 Clone · 炒群 AI · 审批工作台</p>
        </CardHeader>
      </Card>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {cards.map((c) => (
          <Card key={c.title}>
            <CardHeader className="pb-1">
              <p className="text-sm text-muted-foreground">{c.title}</p>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{c.v}</div>
              <div className="text-xs text-muted-foreground">{c.sub}</div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
