# Claude Code Usage Bar

A lightweight macOS menu bar app that shows your [Claude Code](https://claude.ai/code) usage stats — messages, models, and live plan limits.

![screenshot placeholder](screenshot.png)

---

## Install

```bash
brew tap YOUR_USERNAME/claude-code-usage-bar
brew install claude-code-usage-bar
brew services start claude-code-usage-bar
```

The icon appears in your menu bar within a few seconds.

**Or, one-line install without Homebrew:**
```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/claude-code-usage-bar/main/install.sh | bash
```

---

## What you'll see

```
Plan: Pro
──────────────────────────────────────
Plan limits
  Current session     ████████░░  88%
    resets in 32m
  Weekly limits       ███░░░░░░░  32%
    resets Sat 6 AM
──────────────────────────────────────
  Models this month:
  sonnet-4-6          ████████░░  85%   2,953 msgs
  haiku-4-5           ██░░░░░░░░  14%     495 msgs
──────────────────────────────────────
Claude Code March 2026
  This month: 3,490 messages
  Today: 47 messages · 2 sessions
  Last 7 days: 3,248 messages
  Lifetime: 7,862 messages
──────────────────────────────────────
Refresh Now
Quit
```

**Icon ring** — fills clockwise as your current session fills up:
- 🟢 Green (0–60%)
- 🟡 Yellow (61–85%)
- 🔴 Red (86–100%)
- ⚪ Solid disc (100%+)

---

## Optional: Live Plan Limits

The Plan limits section (Current session %, Weekly %) requires a one-time setup:

1. Click the icon in your menu bar
2. Click **"Setup Live Data…"**
3. Follow the 5-step dialog (opens claude.ai, you copy one value from DevTools)
4. Done — never asked again

Your session key is stored in **macOS Keychain** (encrypted, app-access only). It's never written to any file, log, or sent anywhere except `https://claude.ai`.

When your session eventually expires (weeks–months), the menu will show **"Reconnect…"** and you repeat the 2-minute flow.

---

## Data sources

| What | Where | Auth |
|------|-------|------|
| Message counts, models | `~/.claude/projects/**/*.jsonl` | None — local files |
| Current session %, weekly % | `https://claude.ai/api/…/usage` | sessionKey (Keychain) |

No data is sent to any third party. The app is fully open source.

---

## Requirements

- macOS 12 Monterey or later
- [Claude Code CLI](https://docs.anthropic.com/claude-code) installed (provides the `.jsonl` files)
- Python 3.10+

---

## Uninstall

```bash
brew services stop claude-code-usage-bar
brew uninstall claude-code-usage-bar
brew untap YOUR_USERNAME/claude-code-usage-bar
```

Or if installed via install.sh:
```bash
bash <(curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/claude-code-usage-bar/main/uninstall.sh)
```

---

## FAQ

**Why does "Today" show hundreds of messages?**
Each Claude Code tool call (file read, bash command, etc.) generates one assistant message. A single task with 20 tool calls = 20 messages. This is normal for agentic sessions.

**Is my data private?**
Yes. The app only reads local files and optionally queries your own claude.ai session. Nothing is sent to third parties.

**Can I change my plan type?**
Edit `~/.claude/menubar/config.json` and set `monthly_budget_usd` to `20` (Pro), `100` (Max), or `200` (Max 5×).

---

## License

MIT
