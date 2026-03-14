#!/bin/bash
# qa.sh — sanity checks for claude-code-usage-bar
set -euo pipefail
PASS=0; FAIL=0

ok()   { echo "  ✅ $1"; ((PASS++)) || true; }
fail() { echo "  ❌ $1"; ((FAIL++)) || true; }
hdr()  { echo ""; echo "▸ $1"; }

# ── 1. Python version ──────────────────────────────────────────────────────
hdr "Python version"
PY=$(python3 --version 2>&1 | awk '{print $2}')
MAJOR=$(echo "$PY" | cut -d. -f1)
MINOR=$(echo "$PY" | cut -d. -f2)
if [[ "$MAJOR" -ge 3 && "$MINOR" -ge 10 ]]; then
  ok "Python $PY (≥ 3.10)"
else
  fail "Python $PY is < 3.10 — app may crash on older syntax"
fi

# ── 2. Required packages ───────────────────────────────────────────────────
hdr "Python packages"
for pkg in rumps pyobjc browser_cookie3; do
  if python3 -c "import $pkg" 2>/dev/null; then
    ok "$pkg installed"
  else
    fail "$pkg NOT installed"
  fi
done

# ── 3. Config file ─────────────────────────────────────────────────────────
hdr "Config file"
CFG="$HOME/.claude/menubar/config.json"
if [[ -f "$CFG" ]]; then
  ok "config.json exists"
  ORG=$(python3 -c "import json; d=json.load(open('$CFG')); print(d.get('claude_org_id',''))" 2>/dev/null)
  SK=$(python3  -c "import json; d=json.load(open('$CFG')); print(d.get('session_key',''))"   2>/dev/null)
  [[ -n "$ORG" ]] && ok "org_id set: $ORG" || fail "claude_org_id is empty"
  [[ -n "$SK"  ]] && ok "session_key set (len=${#SK})" || fail "session_key is empty — live data won't work"
else
  fail "config.json not found at $CFG"
fi

# ── 4. JSONL data ──────────────────────────────────────────────────────────
hdr "Local JSONL data"
COUNT=$(find ~/.claude/projects -name "*.jsonl" 2>/dev/null | wc -l | tr -d ' ')
if [[ "$COUNT" -gt 0 ]]; then
  ok "$COUNT JSONL files found"
else
  fail "No JSONL files in ~/.claude/projects — no local stats will show"
fi

# ── 5. Live API test ───────────────────────────────────────────────────────
hdr "Live API"
if [[ -n "$ORG" && -n "$SK" ]]; then
  HTTP=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Cookie: sessionKey=$SK" \
    -H "Accept: application/json" \
    "https://claude.ai/api/organizations/$ORG/usage" 2>/dev/null)
  if [[ "$HTTP" == "200" ]]; then
    ok "claude.ai API returned 200 ✓"
  elif [[ "$HTTP" == "401" || "$HTTP" == "403" ]]; then
    fail "API returned $HTTP — session key is expired, get a fresh one from Chrome DevTools"
  else
    fail "API returned HTTP $HTTP"
  fi
else
  echo "  ⏭  skipped (no org_id or session_key)"
fi

# ── 6. LaunchAgent ─────────────────────────────────────────────────────────
hdr "LaunchAgent"
PLIST="$HOME/Library/LaunchAgents/com.claude.usage-bar.plist"
if [[ -f "$PLIST" ]]; then
  ok "plist exists"
  if launchctl list 2>/dev/null | grep -q "com.claude.usage-bar"; then
    ok "LaunchAgent is loaded"
  else
    fail "LaunchAgent is NOT loaded — run: launchctl bootstrap gui/\$(id -u) $PLIST"
  fi
else
  fail "plist not found — run install.sh first"
fi

# ── 7. Process running ─────────────────────────────────────────────────────
hdr "Process"
if pgrep -qf claude_usage_bar.py; then
  ok "claude_usage_bar.py is running"
else
  fail "claude_usage_bar.py is NOT running"
fi

# ── Summary ────────────────────────────────────────────────────────────────
echo ""
echo "──────────────────────────────"
echo "  Passed: $PASS   Failed: $FAIL"
echo "──────────────────────────────"
[[ "$FAIL" -eq 0 ]] && echo "  🎉 All checks passed!" || echo "  ⚠️  Fix the issues above"
echo ""
