#!/usr/bin/env python3
from __future__ import annotations  # allows str | None on Python 3.9
"""claude-code-usage-bar — macOS menu bar app for Claude Code usage.

Data sources
  • ~/.claude/projects/**/*.jsonl  — local message/token stats (no auth)
  • https://claude.ai/api/...       — live session/weekly plan limits
                                      (one-time Keychain setup, optional)

https://github.com/YOUR_USERNAME/claude-code-usage-bar
"""

import calendar
import json
import os
import subprocess
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import rumps
from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSImage,
                    NSMutableParagraphStyle, NSAttributedString,
                    NSParagraphStyleAttributeName, NSTextTab)
from Foundation import NSMakeSize

# ── constants ─────────────────────────────────────────────────────────────────
PROJECTS_DIR     = os.path.expanduser("~/.claude/projects")
CONFIG_FILE      = os.path.expanduser("~/.claude/menubar/config.json")
ICON_PATH        = "/tmp/claude_gauge.png"
ICON_SIZE        = 16
MAX_MODELS       = 6
CLAUDE_API       = "https://claude.ai/api"
MENU_W_PTS       = 320    # right-tab stop in points
KEYCHAIN_SERVICE = "claude-code-usage-bar"
KEYCHAIN_ACCOUNT = "session_key"

DEFAULT_CONFIG = {
    "monthly_budget_usd":       100.0,
    "refresh_interval_seconds": 60,
    "claude_org_id":            "",
}


# ── config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return {**DEFAULT_CONFIG, **data}
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    # Never persist session_key to disk — it lives in Keychain only
    safe = {k: v for k, v in cfg.items() if k != "session_key"}
    with open(CONFIG_FILE, "w") as f:
        json.dump(safe, f, indent=2)


# ── Keychain (macOS) ──────────────────────────────────────────────────────────
def _keychain_read() -> str | None:
    """Read session key from macOS Keychain — silent, no prompt."""
    try:
        import keyring
        val = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
        return val if val else None
    except Exception:
        return None


def _keychain_write(key: str):
    """Save session key to macOS Keychain."""
    import keyring
    keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, key)


def _keychain_delete():
    """Remove session key from macOS Keychain (used by uninstall)."""
    try:
        import keyring
        keyring.delete_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception:
        pass


# ── session key ───────────────────────────────────────────────────────────────
_sk_cache: dict = {"key": None, "ts": 0.0}
_SK_TTL = 3600


def _get_session_key() -> str | None:
    """Return session key: Keychain → config.json fallback."""
    now = time.time()
    if _sk_cache["key"] and now - _sk_cache["ts"] < _SK_TTL:
        return _sk_cache["key"]

    # 1. macOS Keychain (preferred — secure, no prompts after first save)
    key = _keychain_read()

    # 2. Legacy: config.json plain-text field (backward compat)
    if not key:
        cfg = load_config()
        key = cfg.get("session_key", "").strip() or None

    if key:
        _sk_cache["key"] = key
        _sk_cache["ts"]  = now
    return key


def _setup_live_dialog() -> bool:
    """
    Open claude.ai in browser + show step-by-step macOS dialog.
    Returns True if a key was saved successfully.
    """
    # Open claude.ai first so it's ready when user switches to browser
    subprocess.run(["open", "https://claude.ai"], check=False)

    instructions = (
        "To enable live plan limits, copy your session key:\\n\\n"
        "1. Switch to your browser (claude.ai is now open)\\n"
        "2. Press ⌥⌘I to open DevTools\\n"
        "3. Click the Application tab\\n"
        "4. Open Cookies → https://claude.ai\\n"
        "5. Find the row named sessionKey\\n"
        "6. Double-click its Value and copy it\\n"
        "7. Paste it below ↓"
    )
    script = f'''
    set k to text returned of (display dialog "{instructions}" ¬
        default answer "" with title "Setup Live Data" ¬
        buttons {{"Cancel", "Save"}} default button "Save")
    return k
    '''
    r = subprocess.run(["osascript", "-e", script],
                       capture_output=True, text=True)
    key = r.stdout.strip()
    if r.returncode == 0 and key:
        _keychain_write(key)
        _sk_cache["key"] = key
        _sk_cache["ts"]  = time.time()
        return True
    return False


# ── claude.ai API ──────────────────────────────────────────────────────────────
def _claude_get(path: str, session_key: str) -> dict | None:
    req = urllib.request.Request(
        f"{CLAUDE_API}/{path}",
        headers={
            "Cookie":     f"sessionKey={session_key}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
            "Accept":     "application/json",
            "Referer":    "https://claude.ai/",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def _discover_org_id(session_key: str) -> str | None:
    data = _claude_get("organizations", session_key)
    if isinstance(data, list) and data:
        return data[0].get("uuid")
    return None


# ── live usage cache ──────────────────────────────────────────────────────────
_live_cache: dict = {}
_live_lock  = threading.Lock()


def _refresh_live_usage(org_id: str):
    """Background thread: poll claude.ai usage every 60 s."""
    while True:
        sk = _get_session_key()
        if sk and org_id:
            data = _claude_get(f"organizations/{org_id}/usage", sk)
            if data:
                with _live_lock:
                    _live_cache.update(data)
                    _live_cache["_ok"] = True
                    _live_cache["_ts"] = time.time()
            elif data is None:          # network / auth error
                with _live_lock:
                    _live_cache["_ok"] = False
        time.sleep(60)


def get_live_usage() -> dict:
    with _live_lock:
        return dict(_live_cache)


# ── time helper ───────────────────────────────────────────────────────────────
def _time_until(iso: str) -> str:
    try:
        dt   = datetime.fromisoformat(iso)
        now  = datetime.now(timezone.utc)
        secs = int((dt - now).total_seconds())
        if secs <= 0: return "resetting…"
        h, rem = divmod(secs, 3600)
        m = rem // 60
        if h >= 24: return dt.astimezone().strftime("resets %a %-I %p")
        if h > 0:   return f"resets in {h}h {m:02d}m"
        return f"resets in {m}m"
    except Exception:
        return ""


# ── helpers ───────────────────────────────────────────────────────────────────
def short_model(name): return name.replace("claude-", "")

def fmt_num(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)

def make_bar(pct, width=14):
    filled = min(width, round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)

def _attr_right(left: str, right: str) -> NSAttributedString:
    """Attributed string with right-aligned tab stop for the right text."""
    para = NSMutableParagraphStyle.alloc().init()
    tab  = NSTextTab.alloc().initWithTextAlignment_location_options_(2, MENU_W_PTS, {})
    para.setTabStops_([tab])
    return NSAttributedString.alloc().initWithString_attributes_(
        f"{left}\t{right}", {NSParagraphStyleAttributeName: para}
    )


# ── JSONL parser ──────────────────────────────────────────────────────────────
MODEL_PRICING = {
    "claude-haiku":  {"in": 0.80,  "out": 4.00,  "cr": 0.08},
    "claude-sonnet": {"in": 3.00,  "out": 15.00, "cr": 0.30},
    "claude-opus":   {"in": 15.00, "out": 75.00, "cr": 1.50},
}

def _tokens_to_usd(model, inp, out, cr, cc):
    key = next((k for k in MODEL_PRICING if model.startswith(k)), None)
    p   = MODEL_PRICING.get(key, MODEL_PRICING["claude-sonnet"])
    return (inp * p["in"] + out * p["out"] + cr * p["cr"] + cc * p["in"] * 0.25) / 1_000_000


def _parse_jsonl() -> dict:
    now          = datetime.now()
    month_prefix = now.strftime("%Y-%m")
    today_str    = now.strftime("%Y-%m-%d")
    week_ago     = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    month_msgs = today_msgs = week_msgs = total_msgs = 0
    sessions_today: set = set()
    models_month: dict  = {}

    for root, _, files in os.walk(PROJECTS_DIR):
        for fname in files:
            if not fname.endswith(".jsonl"): continue
            try:
                with open(os.path.join(root, fname),
                          encoding="utf-8", errors="ignore") as f:
                    for raw in f:
                        raw = raw.strip()
                        if not raw: continue
                        try:    entry = json.loads(raw)
                        except: continue
                        if entry.get("type") != "assistant": continue
                        ts  = entry.get("timestamp", "")[:10]
                        sid = entry.get("sessionId", "")
                        if not ts: continue
                        msg   = entry.get("message", {})
                        model = msg.get("model", "")
                        total_msgs += 1
                        if ts.startswith(month_prefix):
                            month_msgs += 1
                            sname = short_model(model.split("-20")[0]) \
                                    if model and not model.startswith("<") else None
                            if sname:
                                rec = models_month.setdefault(
                                    sname, {"msgs": 0})
                                rec["msgs"] += 1
                        if ts == today_str:
                            today_msgs += 1
                            if sid: sessions_today.add(sid)
                        if ts >= week_ago:
                            week_msgs += 1
            except (OSError, PermissionError):
                continue

    return {
        "month_msgs":     month_msgs,
        "today_msgs":     today_msgs,
        "week_msgs":      week_msgs,
        "total_msgs":     total_msgs,
        "sessions_today": len(sessions_today),
        "models_month":   dict(sorted(
            models_month.items(), key=lambda x: -x[1]["msgs"])),
    }


# ── gauge icon ────────────────────────────────────────────────────────────────
def _draw_gauge(pct: int) -> NSImage:
    size = ICON_SIZE
    img  = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    cx, cy      = size / 2, size / 2
    r, stroke   = size / 2 - 2, 2.0
    if pct >= 100:
        disc = NSBezierPath.bezierPathWithOvalInRect_(
            ((cx - r, cy - r), (r * 2, r * 2)))
        NSColor.whiteColor().setFill()
        disc.fill()
    else:
        bg = NSBezierPath.bezierPath()
        bg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            (cx, cy), r, 0, 360)
        NSColor.colorWithWhite_alpha_(0.5, 1.0).setStroke()
        bg.setLineWidth_(stroke)
        bg.setLineCapStyle_(1)
        bg.stroke()
        if pct > 0:
            color = (
                NSColor.colorWithRed_green_blue_alpha_(1.0, 0.25, 0.25, 1.0) if pct >= 86
                else NSColor.colorWithRed_green_blue_alpha_(1.0, 0.78, 0.15, 1.0) if pct >= 61
                else NSColor.colorWithRed_green_blue_alpha_(0.2, 0.85, 0.4, 1.0)
            )
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (cx, cy), r, 90.0, 90.0 - pct / 100 * 360, True)
            color.setStroke()
            arc.setLineWidth_(stroke)
            arc.setLineCapStyle_(1)
            arc.stroke()
    img.unlockFocus()
    img.setTemplate_(True)
    return img


def update_icon_file(pct: int) -> str:
    img  = _draw_gauge(pct)
    tiff = img.TIFFRepresentation()
    rep  = NSBitmapImageRep.imageRepWithData_(tiff)
    png  = rep.representationUsingType_properties_(4, None)
    png.writeToFile_atomically_(ICON_PATH, True)
    return ICON_PATH


def _noop(_): pass


# ── app ───────────────────────────────────────────────────────────────────────
class ClaudeUsageApp(rumps.App):
    def __init__(self):
        super().__init__("●", icon=None, quit_button=None)
        self.config    = load_config()
        self._last_pct = -1

        # ── Plan limits (live) ─────────────────────────────
        self.plan_item     = rumps.MenuItem("", callback=_noop)
        self.live_header   = rumps.MenuItem("Plan limits", callback=_noop)
        self.session_item  = rumps.MenuItem("  Current session  —", callback=_noop)
        self.session_bar   = rumps.MenuItem("", callback=_noop)
        self.weekly_item   = rumps.MenuItem("  Weekly limits    —", callback=_noop)
        self.weekly_bar    = rumps.MenuItem("", callback=_noop)
        self.live_note     = rumps.MenuItem("", callback=_noop)
        self.setup_item    = rumps.MenuItem("  Setup Live Data…",
                                            callback=self.run_setup)

        # ── Local stats ────────────────────────────────────
        self.local_header  = rumps.MenuItem("", callback=_noop)
        self.month_item    = rumps.MenuItem("", callback=_noop)
        self.today_item    = rumps.MenuItem("", callback=_noop)
        self.week_item     = rumps.MenuItem("", callback=_noop)
        self.total_item    = rumps.MenuItem("", callback=_noop)

        # ── Models ─────────────────────────────────────────
        self.models_hdr   = rumps.MenuItem("  Models this month:", callback=_noop)
        self.model_slots  = [rumps.MenuItem("", callback=_noop)
                             for _ in range(MAX_MODELS)]

        self.refresh_item = rumps.MenuItem("Refresh Now",
                                           callback=self.manual_refresh)
        self.quit_item    = rumps.MenuItem("Quit",
                                           callback=rumps.quit_application)

        self.menu = [
            self.plan_item,
            self.live_header,
            self.session_item,
            self.session_bar,
            self.weekly_item,
            self.weekly_bar,
            self.live_note,
            self.setup_item,
            None,
            self.models_hdr,
            *self.model_slots,
            None,
            self.local_header,
            self.month_item,
            self.today_item,
            self.week_item,
            self.total_item,
            None,
            self.refresh_item,
            self.quit_item,
        ]

        threading.Thread(target=self._init_live_poller, daemon=True).start()
        rumps.Timer(self.refresh, 1).start()
        self._timer = rumps.Timer(self.refresh,
                                  self.config["refresh_interval_seconds"])
        self._timer.start()

    # ── live poller ───────────────────────────────────────────────────────────
    def _init_live_poller(self):
        cfg    = self.config
        org_id = cfg.get("claude_org_id", "")
        if not org_id:
            sk = _get_session_key()
            if sk:
                org_id = _discover_org_id(sk) or ""
                if org_id:
                    cfg["claude_org_id"] = org_id
                    save_config(cfg)
        if org_id:
            sk = _get_session_key()
            if sk:
                data = _claude_get(f"organizations/{org_id}/usage", sk)
                if data:
                    with _live_lock:
                        _live_cache.update(data)
                        _live_cache["_ok"] = True
                        _live_cache["_ts"] = time.time()
            threading.Thread(target=_refresh_live_usage,
                             args=(org_id,), daemon=True).start()

    # ── setup ─────────────────────────────────────────────────────────────────
    def run_setup(self, _):
        ok = _setup_live_dialog()
        if ok:
            # bust cache and re-discover org
            _sk_cache["key"] = None
            self.config["claude_org_id"] = ""
            save_config(self.config)
            threading.Thread(target=self._init_live_poller, daemon=True).start()
            rumps.alert("Done", "Live data is now enabled. Stats will appear shortly.")
        # else: user cancelled — do nothing

    # ── refresh ───────────────────────────────────────────────────────────────
    def refresh(self, _):
        cfg    = self.config
        budget = cfg["monthly_budget_usd"]
        stats  = _parse_jsonl()
        live   = get_live_usage()
        now    = datetime.now()

        # gauge = current session % if live available, else local month ratio
        if live.get("_ok") and live.get("five_hour"):
            pct = min(100, int(round(live["five_hour"]["utilization"])))
        else:
            ref = _ref_msgs(budget)
            pct = min(100, round(stats["month_msgs"] / ref * 100)) if ref else 0

        if pct != self._last_pct:
            try:
                self.icon      = update_icon_file(pct)
                self.title     = ""
                self._last_pct = pct
            except Exception:
                self.title = "●"

        # ── plan limits ───────────────────────────────────
        has_key = bool(_get_session_key())

        if live.get("_ok"):
            fh = live.get("five_hour") or {}
            sd = live.get("seven_day") or {}
            eu = live.get("extra_usage") or {}

            sess_pct = int(round(fh.get("utilization", 0) or 0))
            week_pct = int(round(sd.get("utilization", 0) or 0))
            sess_rst = _time_until(fh["resets_at"]) if fh.get("resets_at") else ""
            week_rst = _time_until(sd["resets_at"]) if sd.get("resets_at") else ""

            self.live_header.title = "Plan limits"
            self.session_item._menuitem.setAttributedTitle_(
                _attr_right("Current session",
                            f"{make_bar(sess_pct, 10)}  {sess_pct}%"))
            self.session_bar.title  = f"  {sess_rst}" if sess_rst else ""
            self.weekly_item._menuitem.setAttributedTitle_(
                _attr_right("Weekly limits",
                            f"{make_bar(week_pct, 10)}  {week_pct}%"))
            self.weekly_bar.title = f"  {week_rst}" if week_rst else ""

            if eu.get("is_enabled"):
                spent  = eu.get("used_credits", 0) / 100
                limit  = eu.get("monthly_limit", 0) / 100
                eu_pct = int(round(eu.get("utilization") or 0))
                self.live_note.title = (
                    f"  Extra usage   ${spent:.2f} / ${limit:.0f}   {eu_pct}%")
            else:
                self.live_note.title = ""

            # hide setup item when live is working
            self.setup_item._menuitem.setHidden_(True)

        elif not has_key:
            self.live_header.title  = "Plan limits"
            self.session_item.title = "  Current session  —"
            self.session_bar.title  = ""
            self.weekly_item.title  = "  Weekly limits    —"
            self.weekly_bar.title   = ""
            self.live_note.title    = ""
            self.setup_item._menuitem.setHidden_(False)
            self.setup_item.title   = "  Setup Live Data…"

        else:
            # Has key but API not yet responding (connecting…)
            self.live_header.title  = "Plan limits   (connecting…)"
            self.session_item.title = "  Current session  —"
            self.session_bar.title  = ""
            self.weekly_item.title  = "  Weekly limits    —"
            self.weekly_bar.title   = ""
            self.live_note.title    = ""
            self.setup_item._menuitem.setHidden_(True)

        # ── plan label ────────────────────────────────────
        self.plan_item.title = f"Plan: {_plan_name(budget)}"

        # ── models ────────────────────────────────────────
        models  = stats["models_month"]
        total_m = stats["month_msgs"] or 1
        for i, slot in enumerate(self.model_slots):
            if i < len(models):
                name, d = list(models.items())[i]
                pct_m   = round(d["msgs"] / total_m * 100)
                slot._menuitem.setAttributedTitle_(
                    _attr_right(f"  {name}",
                                f"{make_bar(pct_m, 8)}  {d['msgs']:,} msgs  {pct_m}%"))
                slot._menuitem.setHidden_(False)
            else:
                slot._menuitem.setHidden_(True)

        # ── local stats ───────────────────────────────────
        sess = stats["sessions_today"]
        self.local_header.title = f"Claude Code {now.strftime('%B %Y')}"
        self.month_item.title   = f"  This month: {stats['month_msgs']:,} messages"
        self.today_item.title   = (
            f"  Today: {stats['today_msgs']:,} messages"
            f"  · {sess} session{'s' if sess != 1 else ''}"
        )
        self.week_item.title    = f"  Last 7 days: {stats['week_msgs']:,} messages"
        self.total_item.title   = f"  Lifetime: {stats['total_msgs']:,} messages"

    # ── manual refresh ────────────────────────────────────────────────────────
    def manual_refresh(self, _):
        self._last_pct = -1
        with _live_lock:
            _live_cache.clear()
        threading.Thread(target=self._init_live_poller, daemon=True).start()
        self.refresh(None)


# ── utilities ─────────────────────────────────────────────────────────────────
PLAN_REF_MSGS = {20: 1_500, 100: 8_000, 200: 40_000}

def _ref_msgs(budget):
    for price in sorted(PLAN_REF_MSGS, reverse=True):
        if budget >= price: return PLAN_REF_MSGS[price]
    return PLAN_REF_MSGS[20]

def _plan_name(budget):
    if budget >= 200: return "Max 5×"
    if budget >= 100: return "Max"
    if budget >= 20:  return "Pro"
    return f"${budget:.0f}"


if __name__ == "__main__":
    ClaudeUsageApp().run()
