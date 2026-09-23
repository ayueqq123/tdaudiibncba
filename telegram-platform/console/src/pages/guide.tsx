import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

const steps = [
  {
    title: '第一步:导入 TG 账号',
    body: [
      '到「Session 导入」页上传账号 zip 包(tdata / .session 打包),导入成功的号会出现在「TG 账号」页。',
      '在「TG 账号」页点「启动」,状态徽标变成「运行中」说明号已经连上 Telegram。',
      '点「同步群」可以把号加入的群列表拉下来,建规则时要用到群 ID。',
    ],
  },
  {
    title: '第二步:建 Clone 规则(消息搬运)',
    body: [
      '到「Clone 规则」页点「新建规则」:选账号,填源群 ID 和目标群 ID(-100 开头的那串数字)。',
      '按需选过滤:只搬指定发言人的消息、只搬图片/视频等类型、是否跟随源群的编辑和删除。',
      '建完点「运行」立即生效,不用再手动下发;点「停止」立即停搬。一个号可以同时跑多条规则。',
    ],
  },
  {
    title: '第三步:看搬运结果',
    body: [
      '「投递任务」页是每条被搬消息的流水:待发送/已送达/发送失败/等待重试。',
      '失败的任务可以重试或取消;「总览」页有各状态的汇总数字。',
    ],
  },
  {
    title: '第四步:炒群 AI(可选)',
    body: [
      '到「炒群配置」页新建绑定:选账号 + 填群 ID + 人设提示词 + 模型接口。',
      '模型接口走 OpenAI 兼容格式:填接口地址 + 模型名 + API Key(DeepSeek、豆包、官方 OpenAI 都能接),Key 加密保存不回显。',
      '发言策略三选一:每条消息都接话 / 仅被 @ 时回复 / 随机按概率接话。',
      '「发言延迟」让 AI 等几秒再回(实际等待 = 填的值 ±30%,更像真人);「上下文条数」控制喂给 AI 的最近群消息数。',
      '群里来消息 → AI 生成回复 → 进「AI 回复审批」页,点「通过」才会真的发到群里——不通过不发。',
    ],
  },
  {
    title: '多用户(给客户开账号)',
    body: [
      '「用户」页(仅管理员可见)给客户开登录账号:用户名 + 密码,创建后凭据可复制发给客户。',
      '每个用户登录后是独立空间,自己传号、自己建规则,互相完全看不见;你(admin)能看见全部。',
      '你可以随时停用、改密、删除任何账号;用户自己也能在顶栏「修改密码」。',
    ],
  },
  {
    title: '常见问题',
    body: [
      '规则改了没生效?运行中的规则改配置会自动重新下发,等几秒即可。',
      '群 ID 哪来?账号页「同步群」后在 TG 里看群链接/群信息,-100 开头的数字就是 chat_id。',
      '号高频发言有 TG 风控风险,建议炒群开延迟 + 随机概率,Clone 别往发言受限的群猛搬。',
    ],
  },
]

export default function GuidePage() {
  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-lg font-semibold">新手教程</h1>
        <p className="text-sm text-muted-foreground">
          这个平台做两件事:把 A 群的消息自动搬到 B 群(Clone),以及在群里用 AI 自动接话(炒群)。
        </p>
      </div>
      {steps.map((s) => (
        <Card key={s.title}>
          <CardHeader className="py-3">
            <CardTitle className="text-base">{s.title}</CardTitle>
          </CardHeader>
          <CardContent className="space-y-1.5 pb-4 text-sm text-muted-foreground">
            {s.body.map((line, i) => (
              <p key={i}>{line}</p>
            ))}
          </CardContent>
        </Card>
      ))}
    </div>
  )
}
