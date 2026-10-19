import type { CloneRule } from '@/lib/api'

export interface CloneUsage {
  ruleId: number
  ruleName: string
  role: 'listen' | 'pool'
  targets: { ref: string; joined: boolean }[]
}

const activeTargets = (r: CloneRule) => (r.targets || []).filter((t) => t.status === 'active' || !t.status)

/** 账号 → 它所在的克隆规则(监听号/发送号池)及每个目标群的进群情况 */
export function buildCloneUsage(rules: CloneRule[]): Map<number, CloneUsage[]> {
  const out = new Map<number, CloneUsage[]>()
  const add = (id: number, u: CloneUsage) => out.set(id, [...(out.get(id) || []), u])
  for (const r of rules) {
    const targets = activeTargets(r)
    const ref = (t: (typeof targets)[number]) => t.target_chat_ref || String(t.target_chat_id)
    add(r.account_id, { ruleId: r.id, ruleName: r.name, role: 'listen', targets: [] })
    for (const id of r.sender_account_ids || []) {
      if (id === r.account_id) continue
      add(id, {
        ruleId: r.id,
        ruleName: r.name,
        role: 'pool',
        targets: targets.map((t) => ({ ref: ref(t), joined: (t.joined_account_ids || []).includes(id) })),
      })
    }
  }
  return out
}

export const usageShort = (u: CloneUsage) => {
  if (u.role === 'listen') return `${u.ruleName}·监听`
  const joined = u.targets.filter((t) => t.joined).length
  return `${u.ruleName}·${u.targets.length ? `进群 ${joined}/${u.targets.length}` : '号池'}`
}

export const usageDetail = (list: CloneUsage[]) =>
  list
    .map((u) =>
      u.role === 'listen'
        ? `规则「${u.ruleName}」: 监听号`
        : `规则「${u.ruleName}」: 发送号池\n${u.targets.map((t) => `  ${t.ref}: ${t.joined ? '已进群' : '未进群'}`).join('\n')}`,
    )
    .join('\n')
