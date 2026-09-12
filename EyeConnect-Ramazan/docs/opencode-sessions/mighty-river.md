# Добавление Playwright MCP в проект

- **Session**: `ses_f74871b10ffeZxAmbKf7nWIkUo` (mighty-river)
- **Model**: muse-spark-1.3-contributor-free
- **Directory**: `C:/Users/nisno/OneDrive/Pictures/Ramazan`
- **Created**: 1789046351087
- **Tokens**: input=17825, output=1140, reasoning=1156, cache_read=119018

---

## User

добавь в этот проект playwright mcp

## Assistant

Готово. Добавил Playwright MCP в `C:\Users\nisno\OneDrive\Pictures\Ramazan\opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp"],
      "enabled": true
    }
  }
}
```

Проверки:
- `npx -y @playwright/mcp --help` — запускается корректно
- Chromium для Playwright уже установлен в `%LOCALAPPDATA%\ms-playwright` — дополнительно ничего ставить не нужно

Перезапусти opencode, чтобы конфиг подхватился — сессия на лету его не перечитывает.
