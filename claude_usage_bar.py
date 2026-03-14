#!/usr/bin/env python3
"""Claude Code usage menu bar app.

Live plan limits : https://claude.ai/api/organizations/{org}/usage
                   (session %, weekly %, reset times)
                   Auth via Chrome sessionKey cookie (browser_cookie3).

Local stats      : ~/.claude/projects/**/*.jsonl
                   (turns, tokens, sessions — no auth needed)

Gauge            : weekly utilisation from live API (capped 100%).
Icon             : saved to /tmp/claude_gauge.png  →  self.icon
"""

import calendar
import json
import os
import threading
import time
import urllib.request
import urllib.error
from datetime import datetime, timedelta, timezone

import rumps
from AppKit import (NSBezierPath, NSBitmapImageRep, NSColor, NSImage,
                    NSMutableParagraphStyle, NSAttributedString,
                    NSParagraphStyleAttributeName, NSTextTab)
from Foundation import NSMakeSize

# ── constants ─────────────────────────────────────────────────────────────────
PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
CONFIG_FILE  = os.path.expanduser("~/.claude/menubar/config.json")
ICON_PATH    = "/tmp/claude_gauge.png"
ICON_SIZE    = 16
MAX_MODELS   = 6
CLAUDE_API   = "https://claude.ai/api"
MENU_W_PTS   = 320   # content-area right-tab stop in points (menu ~340 pt wide)

MODEL_PRICING = {
    "claude-haiku-4-5":  {"in": 0.80,  "out": 4.00,  "cr": 0.08},
    "claude-haiku-3-5":  {"in": 0.80,  "out": 4.00,  "cr": 0.08},
    "claude-sonnet-4-6": {"in": 3.00,  "out": 15.00, "cr": 0.30},
    "claude-sonnet-4-5": {"in": 3.00,  "out": 15.00, "cr": 0.30},
    "claude-sonnet-3-7": {"in": 3.00,  "out": 15.00, "cr": 0.30},
    "claude-sonnet-3-5": {"in": 3.00,  "out": 15.00, "cr": 0.30},
    "claude-opus-4-6":   {"in": 15.00, "out": 75.00, "cr": 1.50},
    "claude-opus-4-5":   {"in": 15.00, "out": 75.00, "cr": 1.50},
}
DEFAULT_PRICE = {"in": 3.00, "out": 15.00, "cr": 0.30}

DEFAULT_CONFIG = {
    "monthly_budget_usd":       100.0,
    "refresh_interval_seconds": 60,
    "claude_org_id":            "",    # auto-discovered on first run
    "admin_api_key":            "",
}


# ── config ────────────────────────────────────────────────────────────────────
def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE) as f:
            data = json.load(f)
        return {**DEFAULT_CONFIG, **data}
    return DEFAULT_CONFIG.copy()


def save_config(cfg: dict):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


# ── session key from Chrome ───────────────────────────────────────────────────
_session_key_cache: dict = {"key": None, "fetched": 0.0}
_SESSION_KEY_TTL = 3600   # re-read from Chrome every hour


def _get_session_key() -> str | None:
    """Return sessionKey in priority order:
    1. Manual key stored in config  (no Keychain needed)
    2. Chrome cookie via browser_cookie3  (triggers Keychain prompt)
    """
    now = time.time()
    if _session_key_cache["key"] and now - _session_key_cache["fetched"] < _SESSION_KEY_TTL:
        return _session_key_cache["key"]

    # 1. Manual key from config
    cfg = load_config()
    manual = cfg.get("session_key", "").strip()
    if manual:
        _session_key_cache["key"]     = manual
        _session_key_cache["fetched"] = now
        return manual

    # 2. Auto-read from Chrome (needs Keychain)
    try:
        import browser_cookie3
        cj = browser_cookie3.chrome(domain_name=".claude.ai")
        for cookie in cj:
            if cookie.name == "sessionKey":
                _session_key_cache["key"]     = cookie.value
                _session_key_cache["fetched"] = now
                return cookie.value
    except Exception:
        pass
    return None


def _claude_get(path: str, session_key: str) -> dict | None:
    """GET https://claude.ai/api/{path} authenticated with sessionKey cookie."""
    req = urllib.request.Request(
        f"{CLAUDE_API}/{path}",
        headers={
            "Cookie":     f"sessionKey={session_key}",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
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
    """Find the user's primary org UUID from /api/bootstrap/…/app_start
    by scanning the bootstrap endpoint (which needs the org id — chicken/egg).
    Fall back to /api/organizations to get it."""
    data = _claude_get("organizations", session_key)
    if isinstance(data, list) and data:
        return data[0].get("uuid")
    return None


# ── live usage from claude.ai API ─────────────────────────────────────────────
_live_cache: dict = {}
_live_lock  = threading.Lock()


def _refresh_live_usage(org_id: str):
    """Background thread: poll claude.ai usage API every 60 s."""
    fail_count = 0
    while True:
        sk = _get_session_key()
        if not sk:
            with _live_lock:
                _live_cache["_ok"]    = False
                _live_cache["_error"] = "no_key"
            time.sleep(60)
            continue
        if org_id:
            data = _claude_get(f"organizations/{org_id}/usage", sk)
            if data:
                fail_count = 0
                with _live_lock:
                    _live_cache.update(data)
                    _live_cache["_ok"]    = True
                    _live_cache["_error"] = None
                    _live_cache["_ts"]    = time.time()
            else:
                fail_count += 1
                if fail_count >= 2:
                    with _live_lock:
                        _live_cache["_ok"]    = False
                        _live_cache["_error"] = "expired"
        time.sleep(60)


def get_live_usage() -> dict:
    with _live_lock:
        return dict(_live_cache)


# ── time helpers ──────────────────────────────────────────────────────────────
def _time_until(iso: str) -> str:
    """'2026-03-14T14:00:00+00:00' → 'in 1 hr 45 min' or 'Resets Sat 6 AM'"""
    try:
        dt  = datetime.fromisoformat(iso)
        now = datetime.now(timezone.utc)
        diff = dt - now
        secs = int(diff.total_seconds())
        if secs <= 0:
            return "resetting…"
        h, rem = divmod(secs, 3600)
        m       = rem // 60
        if h >= 24:
            return dt.astimezone().strftime("resets %a %-I %p")
        if h > 0:
            return f"resets in {h}h {m:02d}m"
        return f"resets in {m}m"
    except Exception:
        return ""


# ── helpers ───────────────────────────────────────────────────────────────────
def tokens_to_usd(model, inp, out, cr, cc):
    key = next((k for k in MODEL_PRICING if model.startswith(k)), None)
    p   = MODEL_PRICING.get(key, DEFAULT_PRICE)
    return (inp * p["in"] + out * p["out"] + cr * p["cr"] + cc * p["in"] * 0.25) / 1_000_000


def short_model(name): return name.replace("claude-", "")

def fmt_num(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000:     return f"{n/1_000:.1f}k"
    return str(n)

def make_bar(pct, width=14):
    filled = min(width, round(pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def _attr_right(left: str, right: str) -> NSAttributedString:
    """Attributed string: left text tab-separated from right-aligned right text."""
    para = NSMutableParagraphStyle.alloc().init()
    tab  = NSTextTab.alloc().initWithTextAlignment_location_options_(2, MENU_W_PTS, {})
    para.setTabStops_([tab])
    return NSAttributedString.alloc().initWithString_attributes_(
        f"{left}\t{right}", {NSParagraphStyleAttributeName: para}
    )


# ── JSONL parser with mtime-based cache ───────────────────────────────────────
_jsonl_cache: dict = {}
_jsonl_cache_key: tuple = ()   # (file_count, total_mtime) → cheap staleness check

def _jsonl_cache_signature() -> tuple:
    """Return (file_count, sum_of_mtimes) for all JSONL files — cheap O(n files) check."""
    total_mtime = 0.0
    count = 0
    for root, _, files in os.walk(PROJECTS_DIR):
        for fname in files:
            if fname.endswith(".jsonl"):
                try:
                    total_mtime += os.path.getmtime(os.path.join(root, fname))
                    count += 1
                except OSError:
                    pass
    return (count, total_mtime)

def _parse_jsonl() -> dict:
    global _jsonl_cache, _jsonl_cache_key
    sig = _jsonl_cache_signature()
    now = datetime.now()
    # Re-use cache if files haven't changed AND we're still in the same day
    cache_day = _jsonl_cache.get("_date", "")
    if sig == _jsonl_cache_key and cache_day == now.strftime("%Y-%m-%d") and _jsonl_cache:
        return _jsonl_cache

    month_prefix = now.strftime("%Y-%m")
    today_str    = now.strftime("%Y-%m-%d")
    week_ago     = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    month_turns = today_turns = week_turns = total_turns = 0
    month_usd   = total_usd  = 0.0
    month_tok_in = month_tok_out = 0
    models_month: dict = {}
    sessions_today: set = set()

    for root, _, files in os.walk(PROJECTS_DIR):
        for fname in files:
            if not fname.endswith(".jsonl"): continue
            try:
                with open(os.path.join(root, fname), encoding="utf-8", errors="ignore") as f:
                    for raw in f:
                        raw = raw.strip()
                        if not raw: continue
                        try: entry = json.loads(raw)
                        except: continue
                        if entry.get("type") != "assistant": continue
                        ts  = entry.get("timestamp", "")[:10]
                        sid = entry.get("sessionId", "")
                        if not ts: continue
                        msg   = entry.get("message", {})
                        usage = msg.get("usage", {})
                        model = msg.get("model", "")
                        inp = usage.get("input_tokens", 0)
                        out = usage.get("output_tokens", 0)
                        cr  = usage.get("cache_read_input_tokens", 0)
                        cc  = usage.get("cache_creation_input_tokens", 0)
                        usd = tokens_to_usd(model, inp, out, cr, cc)
                        total_turns += 1
                        total_usd   += usd
                        if ts.startswith(month_prefix):
                            month_turns  += 1
                            month_usd    += usd
                            month_tok_in += inp + cr + cc
                            month_tok_out+= out
                            sname = short_model(model.split("-20")[0]) if model and not model.startswith("<") else None
                            if sname:
                                rec = models_month.setdefault(sname, {"turns": 0, "tok_in": 0, "tok_out": 0})
                                rec["turns"]  += 1
                                rec["tok_in"] += inp + cr + cc
                                rec["tok_out"]+= out
                        if ts == today_str:
                            today_turns += 1
                            if sid: sessions_today.add(sid)
                        if ts >= week_ago:
                            week_turns += 1
            except (OSError, PermissionError): continue

    result = {
        "month_turns": month_turns, "today_turns": today_turns,
        "week_turns":  week_turns,  "total_turns": total_turns,
        "month_usd":   round(month_usd, 2), "total_usd": round(total_usd, 2),
        "month_tok_in": month_tok_in, "month_tok_out": month_tok_out,
        "sessions_today": len(sessions_today),
        "models_month": dict(sorted(models_month.items(), key=lambda x: -x[1]["turns"])),
        "_date": now.strftime("%Y-%m-%d"),
    }
    _jsonl_cache = result
    _jsonl_cache_key = sig
    return result


# ── gauge icon ────────────────────────────────────────────────────────────────
def _draw_gauge(pct: int) -> NSImage:
    size = ICON_SIZE
    img  = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    img.lockFocus()
    cx, cy = size/2, size/2
    r, stroke = size/2 - 2, 2.0          # 1 px thinner than before
    if pct >= 100:
        disc = NSBezierPath.bezierPathWithOvalInRect_(((cx-r, cy-r), (r*2, r*2)))
        NSColor.whiteColor().setFill()
        disc.fill()
    else:
        bg = NSBezierPath.bezierPath()
        bg.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_((cx,cy), r, 0, 360)
        NSColor.colorWithWhite_alpha_(0.5, 1.0).setStroke()
        bg.setLineWidth_(stroke)
        bg.setLineCapStyle_(1)            # round cap
        bg.stroke()
        if pct > 0:
            color = (
                NSColor.colorWithRed_green_blue_alpha_(1.0, 0.25, 0.25, 1.0) if pct >= 86
                else NSColor.colorWithRed_green_blue_alpha_(1.0, 0.78, 0.15, 1.0) if pct >= 61
                else NSColor.colorWithRed_green_blue_alpha_(0.2, 0.85, 0.4, 1.0)
            )
            arc = NSBezierPath.bezierPath()
            arc.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_clockwise_(
                (cx,cy), r, 90.0, 90.0 - pct/100*360, True)
            color.setStroke()
            arc.setLineWidth_(stroke)
            arc.setLineCapStyle_(1)       # round cap on both ends
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


# ── no-op callback (makes items appear enabled, not grayed out) ───────────────
def _noop(_): pass


# ── app ───────────────────────────────────────────────────────────────────────
class ClaudeUsageApp(rumps.App):
    def __init__(self):
        super().__init__("●", icon=None, quit_button=None)
        self.config    = load_config()
        self._last_pct = -1

        # ── Live plan limits (from claude.ai API) ──────────
        self.live_header   = rumps.MenuItem("Plan limits", callback=_noop)
        self.session_item  = rumps.MenuItem("  Session   —", callback=_noop)
        self.session_bar   = rumps.MenuItem("", callback=_noop)
        self.weekly_item   = rumps.MenuItem("  Weekly    —", callback=_noop)
        self.weekly_bar    = rumps.MenuItem("", callback=_noop)
        self.live_note     = rumps.MenuItem("", callback=_noop)

        # ── Local JSONL stats ──────────────────────────────
        self.local_header  = rumps.MenuItem("Claude Code usage", callback=_noop)
        self.month_item    = rumps.MenuItem("", callback=_noop)
        self.today_item    = rumps.MenuItem("", callback=_noop)
        self.week_item     = rumps.MenuItem("", callback=_noop)
        self.total_item    = rumps.MenuItem("", callback=_noop)
        self.tokens_item   = rumps.MenuItem("", callback=_noop)

        # ── Models ─────────────────────────────────────────
        self.models_hdr   = rumps.MenuItem("  Models this month:", callback=_noop)
        self.model_slots  = [rumps.MenuItem("", callback=_noop) for _ in range(MAX_MODELS)]

        # ── Plan ───────────────────────────────────────────
        self.plan_item    = rumps.MenuItem("", callback=_noop)

        self.refresh_item = rumps.MenuItem("Refresh Now", callback=self.manual_refresh)
        self.quit_item    = rumps.MenuItem("Quit", callback=rumps.quit_application)

        self.menu = [
            self.plan_item,           # Plan: Pro — top of menu
            self.live_header,
            self.session_item,
            self.session_bar,
            self.weekly_item,
            self.weekly_bar,
            self.live_note,
            None,
            self.models_hdr,
            *self.model_slots,
            None,
            self.local_header,
            self.month_item,
            self.today_item,
            self.week_item,
            self.total_item,
            self.tokens_item,
            None,
            self.refresh_item,
            self.quit_item,
        ]

        # Start background live-usage poller after org_id is resolved
        threading.Thread(target=self._init_live_poller, daemon=True).start()

        # Local stats timer — single timer, no 1-second hammer
        interval = max(30, self.config.get("refresh_interval_seconds", 60))
        self._timer = rumps.Timer(self.refresh, interval)
        self._timer.start()
        # Run once immediately in background so menu populates right away
        threading.Thread(target=lambda: self.refresh(None), daemon=True).start()

    def _init_live_poller(self):
        """Resolve org_id on first run, then start polling loop."""
        cfg = self.config
        org_id = cfg.get("claude_org_id", "")
        if not org_id:
            sk = _get_session_key()
            if sk:
                org_id = _discover_org_id(sk) or ""
                if org_id:
                    cfg["claude_org_id"] = org_id
                    save_config(cfg)
        if org_id:
            # Do one immediate fetch, then hand off to background loop
            sk = _get_session_key()
            if sk:
                data = _claude_get(f"organizations/{org_id}/usage", sk)
                if data:
                    with _live_lock:
                        _live_cache.update(data)
                        _live_cache["_ok"] = True
                        _live_cache["_ts"] = time.time()
            threading.Thread(target=_refresh_live_usage, args=(org_id,), daemon=True).start()

    # ── refresh ───────────────────────────────────────────────────────────────
    def refresh(self, _):
        cfg    = self.config
        budget = cfg["monthly_budget_usd"]
        stats  = _parse_jsonl()
        live   = get_live_usage()
        now    = datetime.now()

        # ── gauge: current-session utilisation if live available, else monthly turns ──
        if live.get("_ok") and live.get("five_hour"):
            pct = min(100, live["five_hour"]["utilization"])
        else:
            ref = _ref_turns(budget)
            pct = min(100, round(stats["month_turns"] / ref * 100)) if ref else 0

        if pct != self._last_pct:
            try:
                self.icon  = update_icon_file(pct)
                self.title = ""
                self._last_pct = pct
            except Exception:
                self.title = "●"

        # ── live plan limits section ──────────────────────
        # Layout per row:
        #   session_item : "Current session          61%"  (% right-aligned)
        #   session_bar  : "  ████████░░  resets in 1h 09m"  (bar + reset below)
        W = 42   # approximate total char width of the popover
        def _row(label, pct_val):
            pct_str = f"{pct_val}%"
            pad = max(1, W - len(label) - len(pct_str))
            return f"{label}{' ' * pad}{pct_str}"

        if live.get("_ok"):
            fh = live.get("five_hour") or {}
            sd = live.get("seven_day") or {}
            eu = live.get("extra_usage") or {}

            sess_pct = int(round(fh.get("utilization", 0) or 0))
            week_pct = int(round(sd.get("utilization", 0) or 0))
            sess_rst = _time_until(fh["resets_at"]) if fh.get("resets_at") else ""
            week_rst = _time_until(sd["resets_at"]) if sd.get("resets_at") else ""

            self.live_header.title  = "Plan limits"
            self.session_item._menuitem.setAttributedTitle_(
                _attr_right("Current session", f"{make_bar(sess_pct, 10)}  {sess_pct}%"))
            self.session_bar.title  = f"  {sess_rst}" if sess_rst else ""
            self.weekly_item._menuitem.setAttributedTitle_(
                _attr_right("Weekly limits", f"{make_bar(week_pct, 10)}  {week_pct}%"))
            self.weekly_bar.title   = f"  {week_rst}" if week_rst else ""

            if eu.get("is_enabled"):
                spent  = eu.get("used_credits", 0) / 100
                limit  = eu.get("monthly_limit", 0) / 100
                eu_pct = eu.get("utilization") or 0
                self.live_note.title = f"Extra   ${spent:.2f} / ${limit:.0f}   {eu_pct}%"
            else:
                self.live_note.title = ""
        else:
            error = live.get("_error")
            if error == "expired":
                status = "⚠️ session expired — update key"
            elif error == "no_key":
                status = "no session key set"
            else:
                status = "connecting…"
            self.live_header.title  = f"Plan limits   ({status})"
            self.session_item.title = "Current session  —"
            self.session_bar.title  = ""
            self.weekly_item.title  = "Weekly limits    —"
            self.weekly_bar.title   = ""
            self.live_note.title    = ""

        # ── local stats ───────────────────────────────────
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        daily_budget  = budget / days_in_month
        sess = stats["sessions_today"]

        self.local_header.title = f"Claude Code {now.strftime('%B %Y')}"
        self.month_item.title  = f"  This month: {stats['month_turns']:,} messages"
        self.today_item.title  = (
            f"  Today: {stats['today_turns']:,} messages"
            f"  · {sess} session{'s' if sess != 1 else ''}"
        )
        self.week_item.title   = f"  Last 7 days: {stats['week_turns']:,} messages"
        self.total_item.title  = f"  Lifetime: {stats['total_turns']:,} messages"
        self.tokens_item.title = (
            f"  Tokens/mo: {fmt_num(stats['month_tok_in'])} in"
            f"  · {fmt_num(stats['month_tok_out'])} out"
        )

        # ── models ────────────────────────────────────────
        models  = stats["models_month"]
        total_t = stats["month_turns"] or 1
        for i, slot in enumerate(self.model_slots):
            if i < len(models):
                name, d = list(models.items())[i]
                pct_m   = round(d["turns"] / total_t * 100)
                slot._menuitem.setAttributedTitle_(
                    _attr_right(f"  {name}", f"{make_bar(pct_m, 8)}  {d['turns']:,} msgs  {pct_m}%"))
                slot._menuitem.setHidden_(False)
            else:
                slot._menuitem.setHidden_(True)

        # ── plan ──────────────────────────────────────────
        plan_name = _plan_name(budget)
        self.plan_item.title = f"Plan: {plan_name}"

    def manual_refresh(self, _):
        self._last_pct = -1
        # Clear cache so live poller re-fetches immediately
        with _live_lock:
            _live_cache.clear()
        threading.Thread(target=self._init_live_poller, daemon=True).start()
        self.refresh(None)


# ── utilities ─────────────────────────────────────────────────────────────────
PLAN_REF_TURNS = {20: 1_500, 100: 8_000, 200: 40_000}

def _ref_turns(budget):
    for price in sorted(PLAN_REF_TURNS, reverse=True):
        if budget >= price: return PLAN_REF_TURNS[price]
    return PLAN_REF_TURNS[20]

def _plan_name(budget):
    if budget >= 200: return "Max 5×"
    if budget >= 100: return "Max"
    if budget >= 20:  return "Pro"
    return f"${budget:.0f}"


if __name__ == "__main__":
    ClaudeUsageApp().run()
