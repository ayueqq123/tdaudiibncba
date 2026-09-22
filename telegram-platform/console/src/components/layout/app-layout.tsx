import { NavLink, Outlet, useNavigate } from 'react-router-dom'
import {
  Send,
  LogOut,
  LayoutDashboard,
  Users,
  FolderKanban,
  Radio,
  Layers,
  GitBranch,
  Truck,
  ShieldCheck,
  Terminal,
} from 'lucide-react'
import { fetchLogout } from '@/lib/api'
import { cn } from '@/lib/utils'
import { useAuth } from '@/lib/auth'
import { ThemeToggle } from '@/components/theme-toggle'

const GROUPS = [
  {
    label: '消息 Clone',
    items: [
      { to: '/', icon: LayoutDashboard, label: '总览', end: true },
      { to: '/accounts', icon: Radio, label: 'TG 账号' },
      { to: '/imports', icon: Layers, label: 'Session 导入' },
      { to: '/rules', icon: GitBranch, label: 'Clone 规则' },
      { to: '/deliveries', icon: Truck, label: '投递任务' },
    ],
  },
  {
    label: '炒群 AI',
    items: [{ to: '/approvals', icon: ShieldCheck, label: 'AI 回复审批' }],
  },
  {
    label: '设置',
    items: [
      { to: '/users', icon: Users, label: '用户(租户)' },
      { to: '/projects', icon: FolderKanban, label: '项目' },
      { to: '/commands', icon: Terminal, label: '运行时命令' },
    ],
  },
]

export default function AppLayout() {
  const { user, logout } = useAuth()
  const nav = useNavigate()
  async function doLogout() {
    try {
      await fetchLogout()
    } catch {
      /* ignore */
    }
    logout()
    nav('/login')
  }

  return (
    <div className="flex h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r bg-sidebar text-sidebar-foreground">
        <div className="flex h-14 items-center gap-2 border-b px-4">
          <Send className="h-5 w-5 text-primary" />
          <span className="font-semibold">TG 自动化平台</span>
        </div>
        <nav className="flex-1 overflow-y-auto p-2">
          {GROUPS.map((g) => (
            <div key={g.label} className="mb-2">
              <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">{g.label}</div>
              {g.items.map((it) => (
                <NavLink
                  key={it.to}
                  to={it.to}
                  end={it.end}
                  className={({ isActive }) =>
                    cn(
                      'flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors',
                      isActive ? 'bg-sidebar-accent text-primary font-medium' : 'text-sidebar-foreground/80 hover:bg-sidebar-accent/60'
                    )
                  }
                >
                  <it.icon className="h-4 w-4" />
                  {it.label}
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center justify-between border-b px-4">
          <div className="text-sm text-muted-foreground">多账号 Userbot · 消息 Clone · 炒群 AI</div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <span className="text-sm">{user?.nickname || user?.username}</span>
            <button onClick={doLogout} className="cursor-pointer rounded-md p-2 hover:bg-accent" title="退出登录">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="min-w-0 flex-1 overflow-y-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  )
}
