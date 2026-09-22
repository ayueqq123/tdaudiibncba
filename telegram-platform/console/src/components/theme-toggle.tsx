import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { applyTheme, isDark } from '@/lib/theme'
import { Button } from '@/components/ui/button'

export function ThemeToggle() {
  const [dark, setDark] = useState(isDark())
  return (
    <Button
      variant="ghost"
      size="icon"
      title={dark ? '切换亮色' : '切换暗色'}
      onClick={() => {
        const d = !dark
        setDark(d)
        applyTheme(d)
      }}
    >
      {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
    </Button>
  )
}
