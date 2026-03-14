#!/usr/bin/env bash
# claude-code-usage-bar — install script
# Usage: curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/claude-code-usage-bar/main/install.sh | bash

set -euo pipefail

REPO="https://raw.githubusercontent.com/YOUR_USERNAME/claude-code-usage-bar/main"
INSTALL_DIR="$HOME/.claude/menubar"
PLIST="$HOME/Library/LaunchAgents/com.claude.usage-bar.plist"

echo "── Claude Code Usage Bar ─────────────────────"

# ── 1. Python check ──────────────────────────────
PYTHON=$(command -v python3 || true)
if [ -z "$PYTHON" ]; then
  echo "✗  python3 not found. Install via: brew install python"
  exit 1
fi
echo "✓  Python: $PYTHON ($($PYTHON --version))"

# ── 2. pip deps ───────────────────────────────────
echo "   Installing Python dependencies…"
"$PYTHON" -m pip install --quiet --upgrade rumps pyobjc keyring
echo "✓  Dependencies installed"

# ── 3. Script ─────────────────────────────────────
mkdir -p "$INSTALL_DIR"
curl -fsSL "$REPO/claude_usage_bar.py" -o "$INSTALL_DIR/claude_usage_bar.py"
chmod +x "$INSTALL_DIR/claude_usage_bar.py"
echo "✓  Script installed to $INSTALL_DIR/claude_usage_bar.py"

# ── 4. LaunchAgent ────────────────────────────────
curl -fsSL "$REPO/com.claude.usage-bar.plist" -o /tmp/claude-usage-bar-template.plist
sed \
  -e "s|PYTHON_PATH|$PYTHON|g" \
  -e "s|SCRIPT_PATH|$INSTALL_DIR/claude_usage_bar.py|g" \
  /tmp/claude-usage-bar-template.plist > "$PLIST"
rm /tmp/claude-usage-bar-template.plist
echo "✓  LaunchAgent installed to $PLIST"

# ── 5. Start ──────────────────────────────────────
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "✓  App started"

echo ""
echo "────────────────────────────────────────────────"
echo "  Claude Code Usage Bar is running in your menu bar!"
echo ""
echo "  To enable live plan limits (optional):"
echo "  Click the icon → Setup Live Data…"
echo "────────────────────────────────────────────────"
