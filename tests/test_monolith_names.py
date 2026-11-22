"""Модульный монолит (docs/MONOLITH-PLAN.md п.5): после переноса кода по модулям старые имена живы.

Списки сняты с ``main`` до первого переноса ``Panel`` по примесям (22.11, ``31efc72``): публичные имена модуля
``webapp`` и атрибуты класса ``Panel``. Новые имена добавлять сюда не нужно — тест ловит только пропажу старых.
"""

from gas_pult import webapp

MODULE = (
    "ADMIN_OK", "AUDIO_EXT", "AUTH_WITH", "Api", "BRIDGE_MAX", "BRIEF", "BUDGET_PATHS", "BUSY",
    "BaseHTTPRequestHandler", "BinaryIO", "CALLBACK", "CDP", "CONFIRM", "CONFIRM_API", "CONNECTORS",
    "CONNECTORS_URL", "CONTEXT", "COUNTRY_FREE", "ClassVar", "Config", "DANGER", "DEMO_GET", "DEMO_POST",
    "DESKTOP_PORT", "DESKTOP_URL", "DESK_COOKIE", "DESK_PASSES", "DESK_TICKETS", "DESK_TTL", "DIALOG", "DONE_PAGE",
    "EFFORTS", "EL_PAUSE", "EMAIL_LOGIN", "EMAIL_OWN", "FEEDBACK", "FOCUS_GET", "FOCUS_NO_W", "FOCUS_POST",
    "FOCUS_PROJ_GET", "FOCUS_PROJ_POST", "FULL", "GZIP_LEVEL", "GZIP_MIN", "GZIP_TYPES", "HEAD_CHARS", "HELP_OPEN",
    "INVITE_OWN", "INVITE_PATH", "KEYS", "LINK_OPEN", "LOOPBACK", "MAX_AGE", "MAX_BODY", "MEETING_GET",
    "MEETING_POST", "MEMBER_ONLY", "MODEL_LINE", "Mcp", "NOINDEX", "NOTIFY_DONE", "NeedForce", "OFFER_404",
    "OFFER_PATH", "OIDC_OWN", "OIDC_PAGE", "OIDC_PATH", "ORIGIN_OK", "OWNER_ONLY", "OWNER_PRESETS", "OpenRouter",
    "PANEL_KEYS", "PART_NAME", "PART_PATH", "PASSKEY_LOGIN", "PASSKEY_OWN", "PERSONA", "PRESETS", "PROMPTS",
    "PUSH_OWN", "Panel", "Path", "People", "Pult", "REPOS", "ROBOTS", "SELFTEST", "SENT", "SHELL_WINDOW", "SLINK",
    "SLINK_HEADER", "SLINK_NO", "SPACE_OK", "SPACE_RUN", "STAFF_ROLES", "STREAM_IDLE", "STREAM_MAX_S", "STT_EMPTY",
    "STT_JOB", "STT_JOB_TIMEOUT", "STT_KEEP_DAYS", "STT_STREAM", "STT_TIMEOUT", "SW_JS", "TAIL", "TEMP_SKIP",
    "TERM", "TERMS_FREE", "TICKET_TTL", "TITLES", "TOUR", "TTY", "TUNNEL_URL", "TelegramError",
    "ThreadingHTTPServer", "Tmux", "URL_TAIL", "USES", "WINDOWS_TTL", "ago", "allowed", "annotations", "approvals",
    "asr", "balance", "base64", "billing_api", "brand", "bridge", "bridge_install", "bridge_local_token", "brief",
    "calkeys", "catalog", "chat_trash", "chatlog", "chatmcp", "contextlib", "country", "ctxsnap", "date",
    "datetime", "desk_cookie", "desk_pass", "desk_ticket", "deskmobile", "desktabs", "desktop_tab", "desktop_up",
    "drafts", "drive_inbox", "effort_flag", "effort_ok", "emailcode", "escape", "execute", "extract", "fallback",
    "features", "feedback", "find_auth", "focus", "funnel", "gzip", "gzips", "handler", "harness", "has_telegram",
    "hashlib", "head_of", "helper", "hmac", "humanize", "in_space", "invites", "io", "is_guest", "json",
    "link_pref_set", "link_prefs", "logins", "meetings", "messengers_panel", "models", "modules", "morning_brief",
    "notifylevel", "notifyroute", "offer_report", "offers", "oidc", "onboarding", "os", "passkeys", "personas",
    "pi_journal", "projects", "providers", "qr", "re", "recparts", "repos", "resources", "router", "scenarios",
    "secrets", "selftest", "serve", "server_tz", "set_menu", "setup", "share", "shell_window", "shlex", "shutil",
    "socket", "space_budget", "space_files", "space_mcp", "space_projects", "space_sessions", "spaces", "speech",
    "spend", "starters", "stat", "steps", "subprocess", "sweep_temp", "sys", "tasks", "tenants", "terms", "termwin",
    "testers", "threading", "time", "timedelta", "tmux", "transcripts", "tunnel", "upload_log", "urllib", "usage",
    "utc_now", "uuid", "verify", "voice", "webauth", "webpush", "wsock"
)

PANEL = (
    "ABOUT_MAX", "BRANCH_TTL", "CHATS_PAGE", "CHAT_MCP", "CLAUDE_MISSING", "DEMO_ANSWERED", "DEMO_GAP", "DEMO_KEYS",
    "FILES_MAX", "FIRST_PROJECT", "FOCUS_BASE", "INSTR_MAX", "MEDIA", "MEDIA_MAX", "MEM_WAIT", "OWNER_HERE",
    "PROJECT_SYNC", "SEARCH_FILES", "SEARCH_SECS", "SPACE_HIDE", "TEMP_AGE", "TRASH_EVERY", "_keep_dir", "_open_in",
    "_q_tell", "_start_queue", "_stt_file", "_stt_run", "about_text", "activity", "admin_may", "agent_of", "anketa",
    "anketa_answers", "anketa_submit", "balance_watch", "bot_username", "bot_where", "branch_of", "bridge_allowed",
    "bridge_dev_ok", "bridge_space", "bridge_space_allowed", "brief_act", "brief_get", "brief_refresh", "brief_set",
    "budget_add", "budget_watch", "busy_sid", "call_help", "chat_delete", "chat_file", "chat_mcp", "chat_restore",
    "chat_title", "chat_trash_list", "check", "check_budget", "choose_voice", "claude_homes", "clear_stopped",
    "close", "close_ex", "command", "command_log", "command_mark", "command_run", "command_term", "commands",
    "confirm_done", "confirm_start", "cost_limits", "cost_of", "cost_summary", "countries", "country_info",
    "default_model", "demo_answer", "device_link", "done", "effort", "el_ok", "el_voice_name", "el_voices",
    "fallback_info", "fallback_note", "feedback_add", "first_message", "focus_bridge", "focus_meta", "focus_new",
    "focus_owns", "focus_rec", "focus_roots", "focus_send", "focus_sessions", "focus_space", "focus_token",
    "follow_sid", "forget_person", "forget_window", "help_ask", "help_guest", "invite_check", "invite_enter",
    "invite_guard", "invite_info", "invite_miss", "invite_qr", "is_owner", "keep_days", "keep_model", "key",
    "key_label", "login_check", "login_methods", "login_start", "login_window", "mark_by", "mcp_finish",
    "mcp_login", "media", "meeting_audio", "meeting_card", "meeting_dir", "meeting_list", "meeting_public",
    "meeting_share", "meeting_view", "mem_gate", "message", "meta", "model", "model_of", "module_create",
    "module_delete", "module_ids", "module_spaces", "modules_list", "money_of", "my_claude", "need_claude", "new",
    "new_folder", "new_in_space", "notify_info", "notify_set", "offer_bot", "offer_country_ok", "offer_login",
    "offer_telegram", "offer_wizard", "open_in", "open_sids", "openrouter_done", "openrouter_info", "owner_join",
    "owner_space_fix", "owner_space_projects", "people_list", "personal", "pi_row", "pin", "pin_key", "pinned_of",
    "pool_home", "prefs", "preview", "project", "project_chat", "project_chats", "project_data", "project_files",
    "project_history", "project_info", "project_new", "project_of", "project_public", "project_resume",
    "project_session", "project_update", "projects_list", "rec_finish", "remove_key", "repo_add", "repo_list",
    "repo_remove", "restart", "revive", "route", "run", "schedule_of", "sections_of", "seen_ip", "select", "send",
    "session_window", "sessions", "set_access", "set_cost_limits", "set_country", "set_fallback", "set_key",
    "set_models", "set_providers", "set_role", "set_schedule", "set_title", "set_ui", "setup_status", "share_file",
    "share_list", "share_notify", "share_receive", "sid_owner", "slash", "sp_windows", "space_budget",
    "space_claude_check", "space_close", "space_delete", "space_draft_set", "space_drafts", "space_fields",
    "space_info", "space_list", "space_project_chats", "space_project_history", "space_project_info",
    "space_project_new", "space_project_open", "space_project_resume", "space_project_session",
    "space_projects_list", "space_restore", "space_resume", "space_task", "space_welcome", "space_windows",
    "starters_for", "stt", "stt_job", "stt_job_get", "stt_retry", "stt_stream", "task_chat", "task_list",
    "task_run", "team_info", "tell_owners", "temp_tick", "term_open", "term_run", "trash_tick", "triage", "tts",
    "tts_text", "tts_warm", "tty_kind", "tty_window", "ui", "upload", "voice", "voice_cards", "voice_fallback",
    "voice_preview", "voice_settings", "window", "window_journal"
)


def test_webapp_names_kept():
    gone = [n for n in MODULE if not hasattr(webapp, n)]
    assert not gone, "пропали имена webapp.* — реэкспортируйте их: " + ", ".join(gone)


def test_panel_attrs_kept():
    gone = [n for n in PANEL if not hasattr(webapp.Panel, n)]
    assert not gone, "пропали атрибуты webapp.Panel — подключите примесь: " + ", ".join(gone)


def test_panel_parts_are_mixins():
    """Части ``Panel`` — примеси из пакета ``gas_pult.panel``; свой ``__init__`` у них не появляется."""
    parts = [c for c in webapp.Panel.__mro__ if c.__module__.startswith("gas_pult.panel.")]
    assert {c.__name__ for c in parts} >= {"ClientsPart", "VoicePart"}
    assert all("__init__" not in vars(c) for c in parts)
