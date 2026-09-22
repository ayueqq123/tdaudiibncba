const KEY = 'TGP_THEME'

export function isDark() {
  return document.documentElement.classList.contains('dark')
}

export function applyTheme(dark: boolean) {
  document.documentElement.classList.toggle('dark', dark)
  localStorage.setItem(KEY, dark ? 'dark' : 'light')
}

// 默认亮色;用户切换过则记住选择
export function initTheme() {
  applyTheme(localStorage.getItem(KEY) === 'dark')
}
