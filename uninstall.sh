#!/usr/bin/env bash
# claude-code-usage-bar — uninstall script

set -euo pipefail

PLIST="$HOME/Library/LaunchAgents/com.claude.usage-bar.plist"
INSTALL_DIR="$HOME/.claude/menubar"

echo "── Uninstalling Claude Code Usage Bar ──────────"

# Stop and remove LaunchAgent
launchctl bootout "gui/$(id -u)" "$PLIST" 2>/dev/null || true
[ -f "$PLIST" ] && rm "$PLIST" && echo "✓  LaunchAgent removed"

# Kill any running process
pkill -f claude_usage_bar.py 2>/dev/null || true

# Remove session key from Keychain
python3 -c "
import keyring
try:
    keyring.delete_password('claude-code-usage-bar', 'session_key')
    print('✓  Session key removed from Keychain')
except Exception:
    pass
" 2>/dev/null || true

# Remove script and config
[ -f "$INSTALL_DIR/claude_usage_bar.py" ] && rm "$INSTALL_DIR/claude_usage_bar.py" && echo "✓  Script removed"
[ -f "$INSTALL_DIR/config.json"          ] && rm "$INSTALL_DIR/config.json"          && echo "✓  Config removed"

echo ""
echo "  Claude Code Usage Bar has been uninstalled."
