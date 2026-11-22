"""Модульный монолит (docs/MONOLITH-PLAN.md п.5): после переноса кода по модулям старые имена живы.

Списки сняты с ``main`` до первого переноса ``Panel`` по примесям (22.11, ``31efc72``): публичные имена модуля
``webapp`` и атрибуты класса ``Panel``. Новые имена добавлять сюда не нужно — тест ловит только пропажу старых.
``BOT_MODULE`` и ``PULT`` — то же для модуля ``bot`` и класса ``Pult``: сняты с ``main`` (``d9251fc``) до первого
переноса ``Pult`` по примесям (``botparts/voice.py``, 22.11).
Перед шагом 8 (``botparts/meetings|telegram|monitor``, 23.11) снимок ``bot``/``Pult`` дополнен именами с ``main``
(``988c10e``), появившимися после ``d9251fc``:
``AwaitsChoice``, ``alerts``, ``ERR_EVERY``, ``CI_EVERY``, ``fail_tick``, ``ci_tick``.
"""

from gas_pult import bot, webapp

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


BOT_MODULE = (
    "Api", "Auth", "AwaitsChoice", "BUSY", "COMMANDS", "ClassVar", "Commands", "Config", "DANGER", "DEFAULTS",
    "DEMO_GONE", "DEMO_RATE", "DIALOG", "Denied", "HINT", "Journal", "KEYS", "MENU", "MENU_PREFIXES", "NAME_OK",
    "NOISE", "NOTIFY", "NotReady", "PANEL", "PHONE_KB", "PROMPT", "PROMPTS", "Path", "People", "Pult", "QUESTION",
    "SPACE_RUN", "TAIL", "TESTER_HELLO", "TITLES", "TRIAGE_NOTE", "TelegramError", "TgConfirm", "TgLogins", "Tmux",
    "_clip", "activity", "ago", "alerts", "allowed", "annotations", "brand", "brief", "cached_property", "catalog",
    "chainfuse", "chatlog", "contextmanager", "country", "ctxsnap", "date", "datetime", "deliveries", "dialog_hash",
    "digest", "drive_inbox", "emailcode", "escalate_rows", "fail_key", "fallback", "fcntl", "features", "focus", "free",
    "funnel", "harness", "has_telegram", "hashlib", "html", "humanize", "in_space", "injection_guard", "invites",
    "is_guest", "json", "kb", "limitretry", "meetings", "models", "modules", "notifylevel", "notifyroute", "offers",
    "os", "people", "projects", "prompt_draft", "providers", "public", "qr", "re", "review_inbox", "secrets_guard",
    "selftest", "setup", "space_budget", "spaces", "speech", "store", "subprocess", "suppress", "tasks", "tenants",
    "terms", "termwin", "tester_start", "testers", "tglinks", "tgroutes", "threading", "time", "tmux_is_ours",
    "tmux_mod", "transcripts", "triage_text", "urllib", "usage", "uuid", "voice", "webpush"
)

PULT = (
    "AUTO_CLOSE_EVERY", "BURST", "CI_EVERY", "DRAFT_WAIT", "DRAFT_WITHIN", "ERR_EVERY", "ESCALATE", "FOLLOW_EVERY",
    "FOLLOW_MAX", "FUSE_EVERY", "FUSE_QUIET", "LABEL_TTL", "MT_KB", "NOTIFY_TTL", "PUSH_PLAIN", "QUIT_STEP",
    "QUIT_WAIT", "Q_ICON", "RECHECK", "TASK_ICON", "TRUST_EVERY", "_hub", "_meeting_audio", "active", "activity",
    "actor", "admitted", "after_pause", "after_run", "ask_notify_done", "ask_owner", "ask_phone", "auto_close_tick",
    "before_run", "bind", "brief_now", "broadcast", "budget_add", "budget_offer", "channels", "check_urgent",
    "choose_voice", "ci_tick", "claude_dir", "close", "command_list", "cost_decide", "cost_pause", "cost_paused",
    "cost_sessions", "cost_watch", "countries", "country_line", "country_update", "current_voice", "deliver",
    "demo_connect", "demo_of", "demo_rate", "demo_step", "digest_items", "digest_loop", "draft_watch", "el_voice_id",
    "ev", "fail_tick", "fallback_logged", "focus", "folder_window", "follow", "fuse_tick", "grant", "grant_space",
    "handle", "has_country", "hold", "home_of", "invited", "label", "last_line", "limit_wait", "link_done",
    "link_request", "login_request", "mail_one", "make_folder", "meeting_button", "meeting_done", "meeting_piece",
    "meeting_start", "menu_for", "menu_of", "module_create", "module_root", "module_text", "module_tick",
    "modules_loop", "monitor", "morning_tick", "need_active", "need_country", "need_terms", "new_folder", "notify",
    "notify_done_check", "offer_demo", "offer_granted", "offer_hints", "offer_space", "on_callback", "on_contact",
    "on_country", "on_demo", "on_digest", "on_message", "on_module", "on_review", "on_selftest", "on_setup", "on_terms",
    "on_voice", "open_rows", "open_session", "opened_by", "panel_url", "pause_until", "pi_answers", "pick_space",
    "pool_of", "product", "product_pick", "project_window", "projects", "push_enter", "push_one", "push_owners", "quit",
    "quit_ex", "react", "ready_for_text", "rebind_keys", "recheck", "recheck_safe", "remember", "rename",
    "reply_target", "retry_tick", "review_attachment", "run", "run_slash", "say", "screen_msg", "screen_state",
    "selftest_loop", "send", "send_answer", "send_brief", "send_digest", "send_features", "send_invite", "send_later",
    "send_screen", "send_testers", "set_state", "setup_code", "setup_kb", "setup_login", "setup_result", "setup_status",
    "short", "show_commands", "show_country", "show_dialog", "show_industry", "show_modules", "show_people",
    "show_settings", "show_setup", "show_summary", "show_switch", "show_tasks", "show_terms", "show_voice",
    "show_windows", "skipped", "slash", "source", "spaces", "stamps", "state", "still_unsent", "switch_off",
    "tell_country", "term_open", "tester_help", "tester_start", "to", "to_claude", "to_claude_live", "to_head",
    "triage", "trust_auto", "unsent", "via", "voice_preview", "voice_rows", "voice_text", "wait_ready", "web_sessions",
    "window_countries"
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


def test_pult_parts_are_mixins():
    """Части ``Pult`` — примеси из пакета ``gas_pult.botparts``; свой ``__init__`` у них не появляется."""
    parts = [c for c in bot.Pult.__mro__ if c.__module__.startswith("gas_pult.botparts.")]
    assert {c.__name__ for c in parts} >= {"VoicePart"}
    assert all("__init__" not in vars(c) for c in parts)


def test_bot_names_kept():
    gone = [n for n in BOT_MODULE if not hasattr(bot, n)]
    assert not gone, "пропали имена bot.* — реэкспортируйте их: " + ", ".join(gone)


def test_pult_attrs_kept():
    gone = [n for n in PULT if not hasattr(bot.Pult, n)]
    assert not gone, "пропали атрибуты bot.Pult — подключите примесь: " + ", ".join(gone)
