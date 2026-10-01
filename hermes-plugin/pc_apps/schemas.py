"""Allowlisted PC app/site opener + YouTube/WhatsApp/Classroom + calendar helpers."""
from __future__ import annotations

from typing import Any

OPEN_PC_APP: dict[str, Any] = {
    "name": "open_pc_app",
    "description": (
        "Open an allowlisted app/site on the PC Chrome. "
        "CRITICAL: app=movies or app=vidbox opens Vidbox (vidbox.cc) — NEVER YouTube. "
        "If the user says movies / movie / films / cinema / Vidbox, use app=movies (or vidbox). "
        "YouTube only when they say YouTube. "
        "Use this for the computer/PC by default. If the user says 'on my phone' / 'on the phone', "
        "use open_phone_app instead. "
        "Auto-starts debug Chrome if needed. For typing on YouTube use youtube_type_search. "
        "To search a movie title on Vidbox use vidbox_type_search (not youtube_type_search). "
        "For WhatsApp drafting use whatsapp_draft_to_recent (never sends). "
        "For ChatGPT: use chatgpt_draft then chatgpt_send (send waits for phone ALLOW). "
        "For Classroom due work use classroom_pull_dues. "
        "After the user opens a page manually, use look_at_browser to read it. "
        "For Google search in Chrome use chrome_google_search. "
        "ONLY open new research tabs with chrome_open_research_tabs when the user explicitly asks. "
        "To close tabs Jarvis opened use close_jarvis_tabs (never closes user-opened tabs)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": (
                    "Allowlisted app id. Use movies or vidbox for Vidbox.cc. "
                    "Other ids: notebooklm, gmail, chrome, youtube, whatsapp, classroom, chatgpt, google_slides, google_docs, google_sheets, google_drive, google_calendar, maps."
                ),
            },
        },
        "required": ["app"],
    },
}

LIST_BROWSER_TABS: dict[str, Any] = {
    "name": "list_browser_tabs",
    "description": (
        "List open http(s) tabs in the PC debug Chrome (titles, URLs, target_id, which is focused). "
        "Each tab shows jarvis_opened=true if Jarvis opened it (safe to close with close_jarvis_tabs). "
        "User-opened tabs show jarvis_opened=false and are never closed by Jarvis."
    ),
    "parameters": {"type": "object", "properties": {}},
}

LOOK_AT_BROWSER: dict[str, Any] = {
    "name": "look_at_browser",
    "description": (
        "Read the page the user currently has open in PC debug Chrome — without being a "
        "third-party app. Use when they ask you to look at Classroom/YouTube/the screen, "
        "help with on-page questions, explain a YouTube video, or describe what they opened. "
        "Returns visible text, optional screenshot_path (for vision_analyze), and for YouTube "
        "also title/description/transcript when captions exist. Does not navigate away."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "site": {
                "type": "string",
                "description": (
                    "Which tab: active (default, focused tab), notebooklm, gmail, youtube, classroom, whatsapp, "
                    "chatgpt, vidbox, movies, or google."
                ),
            },
            "screenshot": {
                "type": "boolean",
                "description": "Capture a PNG screenshot (default true). Pass path to vision_analyze if needed.",
            },
        },
    },
}

LIST_PC_APPS: dict[str, Any] = {
    "name": "list_pc_apps",
    "description": "List allowlisted PC apps/sites Jarvis may open.",
    "parameters": {"type": "object", "properties": {}},
}

YOUTUBE_TYPE_SEARCH: dict[str, Any] = {
    "name": "youtube_type_search",
    "description": (
        "Type into the YouTube search bar on the PC Chrome and run the search (results page only). "
        "ONLY when the user says YouTube / YT explicitly and wants search results, not a video. "
        "If they say choose/pick/play/open a video, use youtube_pick_video instead. "
        "NEVER use this for movies, movie, films, cinema, or Vidbox — those use vidbox_type_search."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to type into YouTube search.",
            },
            "pick": {
                "type": "boolean",
                "description": "If true, pick and play the best video (same as youtube_pick_video).",
            },
        },
        "required": ["query"],
    },
}

YOUTUBE_PICK_VIDEO: dict[str, Any] = {
    "name": "youtube_pick_video",
    "description": (
        "Search YouTube and OPEN the best-fitting video yourself. "
        "Use when the user says choose/pick/play/find/open a YouTube video about a topic. "
        "Do not ask which video — pick one. Only report failure if nothing is found. "
        "NEVER for movies/Vidbox."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "What the video should be about (e.g. 'bleach explained').",
            },
        },
        "required": ["query"],
    },
}

CLASSROOM_OPEN_CLASS: dict[str, Any] = {
    "name": "classroom_open_class",
    "description": (
        "Open a Google Classroom class by name with fuzzy matching "
        "(english 9s ≈ ENGLISH 9S). Do not ask which class if one is clearly closest."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "class_name": {
                "type": "string",
                "description": "Class name as the user said it.",
            },
        },
        "required": ["class_name"],
    },
}

CLASSROOM_FIND_MATERIAL: dict[str, Any] = {
    "name": "classroom_find_material",
    "description": (
        "Open a Classroom class (fuzzy name match) and open the best matching PDF/book/file. "
        "Example: class_name='english 9s', material='english book pdf'. "
        "If not found, return an error — tell the user briefly. Never submit work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "class_name": {"type": "string", "description": "Class name (fuzzy)."},
            "material": {
                "type": "string",
                "description": "What to find (e.g. english book pdf).",
            },
        },
        "required": ["material"],
    },
}

CLASSROOM_CHECK: dict[str, Any] = {
    "name": "classroom_check",
    "description": (
        "Check Google Classroom. "
        "mode='everything' or 'todo': To-do list only. "
        "mode='all_classes': visit each current class, skip old-named leftovers, "
        "recap this/last week work ordered most→least important by due date + difficulty. "
        "Never submit or turn in work."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "mode": {
                "type": "string",
                "description": "everything | todo | all_classes | solve",
            },
            "weeks": {
                "type": "integer",
                "description": "For all_classes: how many weeks back (default 2).",
            },
            "import_to_calendar": {
                "type": "boolean",
                "description": "Only if user explicitly asked to add to calendar.",
            },
            "max_assignments": {
                "type": "integer",
                "description": "For solve mode: how many assignment pages to open (0-5).",
            },
        },
    },
}

VIDBOX_TYPE_SEARCH: dict[str, Any] = {
    "name": "vidbox_type_search",
    "description": (
        "REQUIRED for anything about movies / movie / films / cinema / Vidbox / vidbox.cc. "
        "Opens Vidbox (NOT YouTube) and searches the title. "
        "Examples: 'open movies and search Spider-Man', 'search Inception on movies', "
        "'find Interstellar on Vidbox'. "
        "If they only say 'open movies' with no title, use open_pc_app app=movies instead. "
        "Never call youtube_type_search for these requests."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Movie or show title to search on Vidbox.",
            },
        },
        "required": ["query"],
    },
}

WHATSAPP_STATUS: dict[str, Any] = {
    "name": "whatsapp_status",
    "description": (
        "Check whether WhatsApp Web is logged in on the PC Chrome. "
        "If not logged in, tell the user to scan the QR code on the PC."
    ),
    "parameters": {"type": "object", "properties": {}},
}

WHATSAPP_DRAFT_TO_RECENT: dict[str, Any] = {
    "name": "whatsapp_draft_to_recent",
    "description": (
        "On WhatsApp Web (PC Chrome): open the Nth recent chat in the left list "
        "(1 = top/most recent) and TYPE a message draft. NEVER send — do not press "
        "Enter and do not click Send. Only works if WhatsApp is already logged in; "
        "otherwise returns an error asking the user to scan QR on the PC. "
        "Prefer whatsapp_draft_to_contact when they name a friend saved in Skills/Memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "chat_index": {
                "type": "integer",
                "description": "1-based index in the recent chats list (1 = first/most recent).",
            },
            "message": {
                "type": "string",
                "description": "Text to type into the message box (will NOT be sent).",
            },
        },
        "required": ["chat_index", "message"],
    },
}

WHATSAPP_DRAFT_TO_CONTACT: dict[str, Any] = {
    "name": "whatsapp_draft_to_contact",
    "description": (
        "Type a WhatsApp message to a friend who has a PHONE NUMBER saved in Skills/Memory. "
        "Example: contact=Hussain message=hi → types only (not sent). "
        "If send=true (user said 'and send'), drafts then waits for phone HUD ALLOW before sending. "
        "Refuses if the contact has no saved phone. Never invent numbers."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": "Friend name as saved in Skills / Memory.",
            },
            "message": {
                "type": "string",
                "description": "Exact message text to type.",
            },
            "send": {
                "type": "boolean",
                "description": "True only if user said to send (requires phone ALLOW).",
            },
            "wait_seconds": {
                "type": "number",
                "description": "How long to wait for phone ALLOW when send=true (default 120).",
            },
        },
        "required": ["contact", "message"],
    },
}

WHATSAPP_SEND: dict[str, Any] = {
    "name": "whatsapp_send",
    "description": (
        "Send the pending WhatsApp draft ONLY after the user taps ALLOW on the phone HUD. "
        "Never send without phone ALLOW. Call after whatsapp_draft_to_contact with send=true "
        "if still waiting, or when they confirm."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "wait_seconds": {
                "type": "number",
                "description": "How long to wait for phone ALLOW (default 120).",
            },
            "approval_id": {
                "type": "string",
                "description": "Optional pending approval id.",
            },
        },
    },
}

CLASSROOM_PULL_DUES: dict[str, Any] = {
    "name": "classroom_pull_dues",
    "description": (
        "Open Google Classroom in the user's already signed-in PC Chrome (not a third-party OAuth app), "
        "read To-do / due assignments, and optionally import dated items into the Jarvis calendar. "
        "NEVER click Turn in, Hand in, or Submit. "
        "If they only say look at my screen, use look_at_browser instead. "
        "If they say check everything, read the To-do list only. "
        "If they say check all classes, use classroom_check with mode=all_classes. "
        "Only import to calendar if they ask."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "import_to_calendar": {
                "type": "boolean",
                "description": "Only true if the user asked to add Classroom items to the calendar. Default false — never import unless asked.",
            },
        },
    },
}

CALENDAR_LIST: dict[str, Any] = {
    "name": "calendar_list",
    "description": (
        "List homework/due events and the weekly schedule on the Jarvis Calendar / Schedule HUD page."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CALENDAR_ADD: dict[str, Any] = {
    "name": "calendar_add",
    "description": (
        "Add a dated item to the Jarvis calendar. "
        "Use kind=holiday for school holidays/breaks from a year calendar photo (include end_date for multi-day breaks). "
        "Use kind=homework/due only when the user clearly gives an assignment due date. "
        "NEVER add homework from a yearly schedule or holiday list photo."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Event or holiday title."},
            "date": {"type": "string", "description": "Start/due date YYYY-MM-DD."},
            "end_date": {
                "type": "string",
                "description": "Optional last day YYYY-MM-DD for multi-day holidays/breaks.",
            },
            "time": {"type": "string", "description": "Optional time HH:MM."},
            "kind": {
                "type": "string",
                "description": "homework | due | holiday | other. Use holiday for breaks; default other unless user said homework.",
            },
            "class_name": {"type": "string", "description": "Optional class name."},
            "notes": {"type": "string"},
        },
        "required": ["title", "date"],
    },
}

CALENDAR_DELETE: dict[str, Any] = {
    "name": "calendar_delete",
    "description": "Delete a calendar event by id (from calendar_list).",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Event id from calendar_list."},
        },
        "required": ["id"],
    },
}

CALENDAR_SET_SCHEDULE: dict[str, Any] = {
    "name": "calendar_set_schedule",
    "description": (
        "Create or update the weekly schedule on the Jarvis Schedule tab. "
        "Use when the user asks to make a schedule / timetable with days and times. "
        "Default merge=true adds/updates without wiping the whole week; set merge=false to replace all."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "Schedule blocks.",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "day": {
                            "type": "string",
                            "description": "mon..sun or Monday..Sunday",
                        },
                        "start": {"type": "string", "description": "HH:MM"},
                        "end": {"type": "string", "description": "HH:MM"},
                        "notes": {"type": "string"},
                    },
                    "required": ["title", "day"],
                },
            },
            "merge": {
                "type": "boolean",
                "description": "true = add/keep existing (default); false = replace entire schedule.",
            },
            "title": {"type": "string", "description": "Single-block shortcut title."},
            "day": {"type": "string", "description": "Single-block shortcut day."},
            "start": {"type": "string"},
            "end": {"type": "string"},
            "notes": {"type": "string"},
        },
    },
}

CALENDAR_DELETE_SCHEDULE: dict[str, Any] = {
    "name": "calendar_delete_schedule",
    "description": "Delete one weekly schedule block by id (from calendar_list).",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Schedule item id."},
        },
        "required": ["id"],
    },
}

BRAIN_ADD_IDEA: dict[str, Any] = {
    "name": "brain_add_idea",
    "description": (
        "Add an idea, note, thought, or brainstorm into Jarvis's Second Brain notes graph. "
        "Each purpose has a distinct color code in the Second Brain HUD: "
        "work (Electric Blue #2979ff), study (Purple #b388ff), creative (Amber Gold #ffd600), "
        "personal (Emerald Green #00e676), urgent (Coral Red #ff1744), tech (Cyan #00e5ff), "
        "finance (Lime #76ff03), notes (Pink #ff4081), media (Warm Orange #ff9100)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Short title for the idea or note."},
            "description": {"type": "string", "description": "Detailed notes, bullet points, thoughts, or URLs."},
            "purpose": {
                "type": "string",
                "enum": ["work", "study", "creative", "personal", "urgent", "tech", "finance", "notes", "media"],
                "description": "Category/purpose determining the distinct color coding in the Second Brain HUD.",
            },
            "genre_id": {"type": "string", "description": "Optional specific genre ID if known."},
        },
        "required": ["title"],
    },
}

BRAIN_LIST_IDEAS: dict[str, Any] = {
    "name": "brain_list_ideas",
    "description": "List existing ideas and notes from the Second Brain with their purposes and color codes.",
    "parameters": {
        "type": "object",
        "properties": {
            "purpose": {
                "type": "string",
                "description": "Optional filter by purpose (e.g. work, study, creative, urgent).",
            },
        },
    },
}

BRAIN_ADD_GENRE: dict[str, Any] = {
    "name": "brain_add_genre",
    "description": "Add a new custom purpose/genre notebook to the Second Brain with a custom color.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Genre / category name."},
            "color": {"type": "string", "description": "Hex color code e.g. #2979ff."},
            "purpose": {"type": "string", "description": "Optional standard purpose mapping."},
        },
        "required": ["name"],
    },
}

DAILY_BRIEFING: dict[str, Any] = {
    "name": "daily_briefing",
    "description": (
        "Get today's comprehensive briefing: current day/date, today's schedule items, "
        "upcoming calendar dues, Second Brain urgent notes, and system readiness."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CONNECTOR_LIST: dict[str, Any] = {
    "name": "connector_list",
    "description": (
        "List apps/websites that are DATA-LINKED to Jarvis (Claude↔Obsidian style). "
        "Linked connectors can be read/searched WITHOUT opening their UI."
    ),
    "parameters": {"type": "object", "properties": {}},
}

CONNECTOR_QUERY: dict[str, Any] = {
    "name": "connector_query",
    "description": (
        "Search/read a LINKED connector's data without opening the app or website. "
        "Use for: Gmail inbox, Google Calendar events, Drive/Docs files, Obsidian notes, "
        "NotebookLM indexed notes, Second Brain ideas. Prefer this over open_pc_app when "
        "the user asks what is in / what's on / search my mail/notes/calendar."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": (
                    "Connector id: gmail, google_calendar, google_drive, google_docs, "
                    "obsidian, notebooklm, second_brain, classroom"
                ),
            },
            "query": {"type": "string", "description": "Search text (optional for calendar list)."},
        },
        "required": ["app"],
    },
}

CONNECTOR_READ: dict[str, Any] = {
    "name": "connector_read",
    "description": (
        "Read one item from a linked connector by id/path (Gmail message id, Drive file id, "
        "Obsidian note path, Second Brain idea id) — does not open the app UI."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {"type": "string"},
            "id": {"type": "string", "description": "Item id or vault-relative note path."},
        },
        "required": ["app", "id"],
    },
}

CONNECTOR_SYNC: dict[str, Any] = {
    "name": "connector_sync",
    "description": (
        "Refresh a synced connector index (NotebookLM, Classroom, Obsidian reindex) "
        "or health-check an API connector."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {"type": "string"},
        },
        "required": ["app"],
    },
}

CHROME_GOOGLE_SEARCH: dict[str, Any] = {
    "name": "chrome_google_search",
    "description": (
        "Search Google IN the user's visible PC Chrome tab (types in the search box). "
        "ONLY use when the user explicitly wants to search on their screen "
        "(e.g. 'search Google on my PC', 'type this in Chrome', 'open Google and search'). "
        "For 'find me…', 'look up…', 'research…', 'list businesses…' — use web_find instead "
        "and answer in chat without touching Chrome."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query to type into Google."},
            "on_user_screen": {
                "type": "boolean",
                "description": (
                    "Must be true. Confirms the user asked to search on their PC Chrome screen "
                    "(not a chat-only find/look-up)."
                ),
            },
        },
        "required": ["query", "on_user_screen"],
    },
}

WEB_FIND: dict[str, Any] = {
    "name": "web_find",
    "description": (
        "Headless web research for 'find me / look up / research / list / recommend' requests. "
        "Returns titles, URLs, and snippets as JSON. NEVER opens Chrome or any PC app. "
        "Use this when the user wants you to find businesses, brands, accounts, products, people, "
        "or facts and tell them the results in chat. "
        "After calling, summarize 5–10 best matches in chat (name + short why / follower hint if present). "
        "Do not open links on the PC unless they explicitly say open/show on my screen."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query (include follower range, niche, platform, location if given).",
            },
            "count": {
                "type": "integer",
                "description": "How many results to return (3–12, default 8).",
            },
        },
        "required": ["query"],
    },
}

BROWSE_WEBSITE: dict[str, Any] = {
    "name": "browse_website",
    "description": (
        "REQUIRED when the user gives a website link and wants you to look at / check / review / "
        "read that site (e.g. a friend's business site). Opens the URL in Jarvis Chrome, reads "
        "several pages on the SAME website only, and returns their text. "
        "Then answer using that info. Never submit forms, sign in, checkout, or pay. "
        "Different from web_find (search) and look_at_browser (current tab only)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full website URL, e.g. https://example.com",
            },
            "focus": {
                "type": "string",
                "description": "What the user asked you to do with the site (review, summarize, find pricing, etc.).",
            },
            "max_pages": {
                "type": "integer",
                "description": "How many pages to read (1–8, default 5).",
            },
        },
        "required": ["url"],
    },
}

MOVIE_RATINGS_LOOKUP: dict[str, Any] = {
    "name": "movie_ratings_lookup",
    "description": (
        "Look up IMDb / overall ratings for a movie or TV show, OR the last N episode ratings. "
        "ALWAYS call this for rating questions — the service IS configured (OMDb + TVMaze). "
        "Never say ratings are unavailable because a service is not configured. "
        "For 'last 6 episodes of One Piece and their ratings', set title='One Piece', "
        "recent_episodes=true, count=6. Do NOT open Vidbox/YouTube for rating questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Movie or TV show title (English title preferred).",
            },
            "year": {
                "type": "string",
                "description": "Optional release year to disambiguate.",
            },
            "prefer": {
                "type": "string",
                "description": "Optional: 'tv' if clearly a series, else omit.",
            },
            "recent_episodes": {
                "type": "boolean",
                "description": "If true, return the last N aired episodes with per-episode ratings.",
            },
            "count": {
                "type": "integer",
                "description": "How many recent episodes (1–20, default 6). Only with recent_episodes.",
            },
        },
        "required": ["title"],
    },
}

CHROME_TYPE_IN_PAGE: dict[str, Any] = {
    "name": "chrome_type_in_page",
    "description": (
        "Type text into the active field on the current PC Chrome tab (input, textarea, search box). "
        "Does NOT open new tabs. Set submit=true to press Enter / submit a form."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to type."},
            "submit": {
                "type": "boolean",
                "description": "If true, submit/search after typing (default false).",
            },
        },
        "required": ["text"],
    },
}

CHROME_NAVIGATE_ACTIVE_TAB: dict[str, Any] = {
    "name": "chrome_navigate_active_tab",
    "description": (
        "Go to a https URL in the CURRENT PC Chrome tab. "
        "ONLY when the user explicitly asked to open/go to a page on their screen. "
        "For find/research/list requests use web_find or web_search — never this tool."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full https:// URL."},
            "on_user_screen": {
                "type": "boolean",
                "description": "Must be true — confirms they asked to change their PC Chrome.",
            },
        },
        "required": ["url", "on_user_screen"],
    },
}

CHROME_OPEN_RESEARCH_TABS: dict[str, Any] = {
    "name": "chrome_open_research_tabs",
    "description": (
        "Open research tabs in PC Chrome ONLY when the user explicitly says to open tab(s)/Chrome. "
        "NEVER for plain 'find me / look up / research / list' — use web_find instead. "
        "Requires user_explicitly_asked_to_open_tabs=true AND user_quote_asking_to_open = their exact words "
        "(must include open+tab or open on my PC / in Chrome). "
        "tab_count MUST match exactly what they said; urls length MUST equal tab_count."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "user_explicitly_asked_to_open_tabs": {
                "type": "boolean",
                "description": "MUST be true only if the user clearly asked to open tab(s).",
            },
            "user_quote_asking_to_open": {
                "type": "string",
                "description": (
                    "Exact user words asking to open tabs/Chrome on PC "
                    "(e.g. 'open two tabs about X'). Required."
                ),
            },
            "tab_count": {
                "type": "integer",
                "description": "Exact number of tabs the user requested (1-5).",
            },
            "research_topic": {
                "type": "string",
                "description": "What the user is researching (for logging/context).",
            },
            "urls": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Exactly tab_count https URLs to open. "
                    "For tab_count=1 you may omit and pass research_topic instead (opens one Google search)."
                ),
            },
        },
        "required": ["user_explicitly_asked_to_open_tabs", "user_quote_asking_to_open", "tab_count"],
    },
}

CHATGPT_OPEN: dict[str, Any] = {
    "name": "chatgpt_open",
    "description": (
        "Open ChatGPT in PC debug Chrome in a NEW Jarvis-owned tab/session, or reuse the "
        "session Jarvis already opened. NEVER clicks previous chats in the sidebar. "
        "Does not type or send. Prefer chatgpt_draft when the user wants to write something."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "force_new": {
                "type": "boolean",
                "description": "If true, always start a brand-new ChatGPT chat (new tab + New chat).",
            },
        },
    },
}

CHATGPT_DRAFT: dict[str, Any] = {
    "name": "chatgpt_draft",
    "description": (
        "Type a message into ChatGPT on the PC (Jarvis-owned session only). "
        "Opens a new ChatGPT session if Jarvis does not already have one; otherwise continues "
        "in Jarvis's session. NEVER clicks old sidebar chats. NEVER presses Send/Enter. "
        "Pushes an ALLOW/DENY card to the phone HUD. After drafting, call chatgpt_send which "
        "waits for phone ALLOW before sending."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Exact text to type into the ChatGPT composer.",
            },
            "force_new": {
                "type": "boolean",
                "description": "If true, force a brand-new ChatGPT chat before typing.",
            },
        },
        "required": ["message"],
    },
}

CHATGPT_SEND: dict[str, Any] = {
    "name": "chatgpt_send",
    "description": (
        "Send the pending ChatGPT draft on the PC ONLY after the user taps ALLOW on the phone HUD. "
        "Waits up to wait_seconds for phone approval. NEVER send without phone ALLOW. "
        "Call after chatgpt_draft. If the user denies, do not retry send."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "wait_seconds": {
                "type": "number",
                "description": "How long to wait for phone ALLOW (default 120).",
            },
        },
    },
}

CHATGPT_STATUS: dict[str, Any] = {
    "name": "chatgpt_status",
    "description": "Check whether Jarvis has an open ChatGPT session and any pending draft/approval.",
    "parameters": {"type": "object", "properties": {}},
}

CLOSE_JARVIS_TABS: dict[str, Any] = {
    "name": "close_jarvis_tabs",
    "description": (
        "REQUIRED for closing browser tabs. Close ONLY Chrome tabs that Jarvis opened "
        "(open_pc_app, chrome_open_research_tabs, youtube/whatsapp opens). "
        "NEVER closes tabs the user opened themselves. "
        "When user says 'close tabs', 'close YouTube', 'close WhatsApp', 'close Chrome tabs you opened', "
        "or 'close all tabs' — ALWAYS call this tool (do not refuse; do not close the user's own Chrome). "
        "close_all=true (or no site) closes every Jarvis tab AND quits the Chrome window Jarvis started. "
        "site=youtube|whatsapp|classroom closes only those tabs and leaves the window open."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "close_all": {
                "type": "boolean",
                "description": (
                    "true = close every tab Jarvis opened. Defaults to true if no site/target_ids given. "
                    "User-opened tabs stay open."
                ),
            },
            "site": {
                "type": "string",
                "description": (
                    "Optional filter: youtube, whatsapp, classroom, google, chrome. "
                    "chrome/all = same as close_all. Only closes Jarvis-opened matching tabs."
                ),
            },
            "target_ids": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional specific target_id values from list_browser_tabs (jarvis_opened tabs only).",
            },
        },
    },
}

OPEN_PHONE_APP: dict[str, Any] = {
    "name": "open_phone_app",
    "description": (
        "Open an allowlisted app/site on the user's PHONE (not the PC). "
        "Use when the user says 'on my phone', 'on the phone', 'on my iPhone', or clearly wants "
        "the phone. Examples: YouTube, WhatsApp, ChatGPT, Maps, Instagram, Spotify, Classroom. "
        "Requires the Jarvis HUD to be open/connected on the phone. "
        "If they do NOT say phone, use open_pc_app instead."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "app": {
                "type": "string",
                "description": (
                    "Allowlisted phone app id: youtube, whatsapp, chatgpt, maps, safari, music, "
                    "instagram, tiktok, twitter, x, spotify, netflix, gmail, classroom, messages, "
                    "photos, camera, settings, phone."
                ),
            },
        },
        "required": ["app"],
    },
}

LIST_PHONE_APPS: dict[str, Any] = {
    "name": "list_phone_apps",
    "description": "List allowlisted apps/sites Jarvis may open on the phone.",
    "parameters": {"type": "object", "properties": {}},
}

REMEMBER_FACT: dict[str, Any] = {
    "name": "remember_fact",
    "description": (
        "Save a lasting personal fact to long-term memory so you NEVER forget it "
        "(friends/family, phones, prefs, school habits, shows/anime they watch, weekly homework). "
        "Call this whenever the user tells you something new about their life — "
        "do NOT wait to be asked, and NEVER ask if it helps or if you should save. "
        "Just save, then briefly confirm. For contacts, set category people and fill phone, "
        "email, and/or whatsapp_name when given. Also call second_brain_add_idea for the same note."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short label, e.g. 'Best friend' or 'Ali'.",
            },
            "value": {
                "type": "string",
                "description": "The fact to remember, e.g. 'Ali' or 'Best friend's name is Ali'.",
            },
            "key": {
                "type": "string",
                "description": "Optional stable id slug, e.g. best_friend or ali.",
            },
            "category": {
                "type": "string",
                "description": "Optional: personal, people, school, preferences, media, habits, other.",
            },
            "phone": {
                "type": "string",
                "description": "Contact phone with country code, e.g. +965xxxxxxxx.",
            },
            "email": {
                "type": "string",
                "description": "Contact email / Gmail address Jarvis may send to, e.g. ali@gmail.com.",
            },
            "whatsapp_name": {
                "type": "string",
                "description": "Exact name as saved in WhatsApp contacts (for name search).",
            },
        },
        "required": ["value"],
    },
}

LIST_MEMORIES: dict[str, Any] = {
    "name": "list_memories",
    "description": "List all long-term memory facts Jarvis has saved (Skills page).",
    "parameters": {"type": "object", "properties": {}},
}

FORGET_MEMORY: dict[str, Any] = {
    "name": "forget_memory",
    "description": "Delete a long-term memory fact by id or key when the user asks to forget something.",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Fact id or key to delete."},
        },
        "required": ["id"],
    },
}

HANDWRITING_STATUS: dict[str, Any] = {
    "name": "handwriting_status",
    "description": (
        "Check whether the user's handwriting is memorized (sample count, languages, pen/pencil). "
        "Use before writing a Doc in their handwriting."
    ),
    "parameters": {"type": "object", "properties": {}},
}

HANDWRITING_WRITE: dict[str, Any] = {
    "name": "handwriting_write",
    "description": (
        "Write a Google Doc / PDF in the user's memorized handwriting (Arabic or English, pen or pencil). "
        "Requires a prior handwriting sample (user sends a photo saying 'memorize my handwriting'). "
        "Renders lined handwritten pages and uploads to Google Drive/Docs when linked. "
        "ALWAYS use this when they ask to write in their handwriting — never say the tool is unavailable."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "body": {
                "type": "string",
                "description": "Exact text to write in their handwriting.",
            },
            "text": {
                "type": "string",
                "description": "Optional full user request if body is not separated.",
            },
            "title": {"type": "string", "description": "Optional document title."},
            "language": {
                "type": "string",
                "description": "en or ar. Auto-detected from text if omitted.",
            },
            "medium": {
                "type": "string",
                "description": "pen or pencil. Defaults to memorized medium.",
            },
            "upload": {
                "type": "boolean",
                "description": "Upload to Google Drive/Docs (default true).",
            },
        },
        "required": ["body"],
    },
}

GOOGLE_DOCS_CREATE: dict[str, Any] = {
    "name": "google_docs_create",
    "description": (
        "Open a NEW Google Doc in the user's PC Chrome (already signed in) and TYPE the text. "
        "Does NOT need Google API / CONNECT / API key. Use for essays, notes, Arabic or English. "
        "Always prefer this over saying Docs is unavailable."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string", "description": "Text to type into the Doc."},
            "body": {"type": "string", "description": "Alias for text."},
        },
        "required": ["text"],
    },
}

GOOGLE_SLIDES_CREATE: dict[str, Any] = {
    "name": "google_slides_create",
    "description": (
        "Open a NEW Google Slides deck in PC Chrome and TYPE into the first text box. "
        "No Google API / CONNECT required. For a full multi-slide deck use google_slides_build_deck."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string", "description": "Text to type on the slide."},
            "body": {"type": "string"},
        },
        "required": ["text"],
    },
}

GOOGLE_SLIDES_BUILD_DECK: dict[str, Any] = {
    "name": "google_slides_build_deck",
    "description": (
        "Build a full N-slide Google Slides presentation in PC Chrome (no Google API). "
        "Pass slides=[{title, body, image_query}, ...]. Jarvis picks design; adds images. "
        "Do NOT ask the user about design unless they asked for design suggestions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "slides": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "image_query": {"type": "string"},
                    },
                },
            },
            "design": {"type": "object"},
            "images": {"type": "boolean", "description": "Insert images (default true)."},
        },
        "required": ["slides"],
    },
}

GOOGLE_DOCS_CHROME_TYPE: dict[str, Any] = {
    "name": "google_docs_chrome_type",
    "description": "Same as google_docs_create — open Docs in Chrome and type (no API).",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["text"],
    },
}

GOOGLE_SLIDES_CHROME_TYPE: dict[str, Any] = {
    "name": "google_slides_chrome_type",
    "description": "Same as google_slides_create — open Slides in Chrome and type (no API).",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "text": {"type": "string"},
            "body": {"type": "string"},
        },
        "required": ["text"],
    },
}

WHATSAPP_OPEN_CHAT: dict[str, Any] = {
    "name": "whatsapp_open_chat",
    "description": (
        "Open a WhatsApp chat with a friend on PC or phone. "
        "Looks up Skills/Memory contacts by name, WhatsApp display name, or phone number. "
        "Use device=pc (default) when they do not say phone; use device=phone when they say "
        "'on my phone'. Prefers phone-number deep link; otherwise searches WhatsApp by name on PC. "
        "Requires WhatsApp Web logged in on PC for PC opens."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": "Friend label from memory, e.g. Ali or Best friend.",
            },
            "phone": {
                "type": "string",
                "description": "Optional phone with country code if known directly.",
            },
            "whatsapp_name": {
                "type": "string",
                "description": "Optional exact WhatsApp contact name if different from contact.",
            },
            "device": {
                "type": "string",
                "description": "pc (default) or phone.",
            },
        },
    },
}

CALL_CONTACT: dict[str, Any] = {
    "name": "call_contact",
    "description": (
        "Place a phone call to a person saved in Skills / Memory. "
        "ONLY works for contacts that already have a phone number saved — "
        "never invent or dial numbers that are not in memory. "
        "Use when the user says call, dial, or phone someone (e.g. 'call Ali', 'dial Mohamed'). "
        "Opens the Phone app on the user's phone via the Jarvis HUD (keep HUD open on the phone). "
        "If the contact has no phone number saved, tell them to add it in Skills / Memory first."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": "Name or label from Skills / Memory, e.g. Ali or Best friend.",
            },
        },
        "required": ["contact"],
    },
}

GMAIL_SEND: dict[str, Any] = {
    "name": "gmail_send",
    "description": (
        "Actually SEND a Gmail from PC Chrome after phone ALLOW. "
        "ONLY use when the user explicitly says send/deliver the email. "
        "For 'write/draft/compose an email' or 'email saying…' WITHOUT send — use gmail_draft "
        "(chat only, never sends). Recipients must be in Skills/Memory."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": "Name from Skills / Memory who has an email saved.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body / message text.",
            },
            "wait_seconds": {
                "type": "number",
                "description": "How long to wait for phone ALLOW (default 120).",
            },
        },
        "required": ["contact", "body"],
    },
}

GMAIL_DRAFT: dict[str, Any] = {
    "name": "gmail_draft",
    "description": (
        "Write a human-sounding email DRAFT and show it in Jarvis chat only. "
        "Does NOT open Gmail compose and does NOT send. "
        "Use for: 'write an email to Ali…', 'draft a mail saying…', 'compose an email about…', "
        "'email Mohamed that I'll be late' (unless they clearly say SEND)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "contact": {
                "type": "string",
                "description": "Who the email is to (name). Optional if body already has a greeting.",
            },
            "subject": {
                "type": "string",
                "description": "Subject line (optional — Jarvis invents a short one if missing).",
            },
            "body": {
                "type": "string",
                "description": (
                    "Full email text OR short intent like 'I'll be 20 minutes late to dinner'. "
                    "Prefer writing a polished human email body yourself, then pass it here."
                ),
            },
            "tone": {
                "type": "string",
                "description": "friendly (default), formal, or short.",
            },
        },
        "required": ["body"],
    },
}

GMAIL_INBOX: dict[str, Any] = {
    "name": "gmail_inbox",
    "description": (
        "Read the user's recent Gmail inbox into chat (list from/subject/snippet). "
        "Uses linked Gmail API if connected; otherwise opens Gmail in PC Chrome and reads the list. "
        "Use for: 'check my email', 'what's in my inbox', 'any new mail?', 'read my emails'."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Gmail search query, default in:inbox. e.g. is:unread, from:ali",
            },
            "max": {
                "type": "number",
                "description": "How many messages to list (default 8).",
            },
        },
    },
}

GMAIL_READ_MAIL: dict[str, Any] = {
    "name": "gmail_read_mail",
    "description": (
        "Read one email's full text into chat (not Gmail UI typing). "
        "Pass message id from gmail_inbox, or subject/search text, or index number (1 = newest)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Gmail message id from inbox list."},
            "subject": {"type": "string", "description": "Subject text to find and open."},
            "query": {"type": "string", "description": "Search text to match a thread."},
            "index": {"type": "number", "description": "1-based position from the latest inbox list."},
        },
    },
}

GMAIL_STATUS: dict[str, Any] = {
    "name": "gmail_status",
    "description": (
        "Check Gmail connection + Skills/Memory contacts with emails. "
        "Reading works via API or Chrome; drafting uses gmail_draft in chat."
    ),
    "parameters": {"type": "object", "properties": {}},
}

NOTEBOOKLM_QUERY: dict[str, Any] = {
    "name": "notebooklm_query",
    "description": (
        "Ask a question to the user's Google NotebookLM notebook to get factual, source-grounded "
        "answers with citations [1], [2] from their uploaded documents, notes, research, and PDFs. "
        "Use this as your co-brain whenever the user asks: 'What do my notes say about X?', "
        "'Ask NotebookLM X', 'According to my documents...', 'Check my notes on X', or "
        "when answering queries that depend on their personal research and study materials."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The exact question or prompt to ask NotebookLM sources.",
            },
            "notebook": {
                "type": "string",
                "description": "Optional name of the notebook to query if not using the active one.",
            },
        },
        "required": ["query"],
    },
}

NOTEBOOKLM_READ_NOTES: dict[str, Any] = {
    "name": "notebooklm_read_notes",
    "description": (
        "Read and extract all loaded sources, saved notes cards, recent answers, and studio artifacts "
        "from the currently active NotebookLM notebook. Use when the user asks: 'What notes do I have?', "
        "'Summarize my notebook', 'What documents are loaded?', or to prime your context before answering."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "notebook": {
                "type": "string",
                "description": "Optional notebook name to inspect.",
            },
        },
    },
}

NOTEBOOKLM_AUDIO_OVERVIEW: dict[str, Any] = {
    "name": "notebooklm_audio_overview",
    "description": (
        "Control NotebookLM's signature 'Audio Overview' (Deep Dive 2-host podcast conversation). "
        "Actions: 'status' (checks if audio podcast exists, is generating, or duration), "
        "'generate' (starts generating Deep Dive audio discussion from sources), "
        "'play' (plays the audio overview in Chrome), 'pause' (pauses playback). "
        "Use when the user asks to play, generate, check, or pause their audio overview or Deep Dive."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "generate", "play", "pause"],
                "description": "Action to perform: status, generate, play, or pause (default status).",
            },
        },
    },
}

NOTEBOOKLM_GENERATE_GUIDE: dict[str, Any] = {
    "name": "notebooklm_generate_guide",
    "description": (
        "Generate a structured study artifact in NotebookLM Studio from the uploaded sources. "
        "Supported types: 'study_guide', 'briefing_doc', 'faq', 'timeline', 'table_of_contents'. "
        "Use when the user asks for a study guide, briefing document, FAQ, or timeline from their notes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "guide_type": {
                "type": "string",
                "enum": ["study_guide", "briefing_doc", "faq", "timeline", "table_of_contents"],
                "description": "Type of guide to generate: study_guide, briefing_doc, faq, timeline, or table_of_contents.",
            },
        },
        "required": ["guide_type"],
    },
}

NOTEBOOKLM_ADD_NOTE: dict[str, Any] = {
    "name": "notebooklm_add_note",
    "description": (
        "Add a new note card to the user's open notebook in NotebookLM. "
        "Use when the user asks to save a note, write down a thought, or record a key takeaway."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The note body / text to save.",
            },
            "title": {
                "type": "string",
                "description": "Optional title for the note card.",
            },
        },
        "required": ["content"],
    },
}

NOTEBOOKLM_LIST_NOTEBOOKS: dict[str, Any] = {
    "name": "notebooklm_list_notebooks",
    "description": (
        "List all notebooks available in the user's Google NotebookLM account. "
        "Returns titles and URLs of all notebooks."
    ),
    "parameters": {"type": "object", "properties": {}},
}

NOTEBOOKLM_STATUS: dict[str, Any] = {
    "name": "notebooklm_status",
    "description": (
        "Check NotebookLM status: whether the tab is open in Chrome, whether Google sign-in "
        "or verification is needed, the active notebook name, and source counts."
    ),
    "parameters": {"type": "object", "properties": {}},
}

SECOND_BRAIN_ADD_IDEA: dict[str, Any] = {
    "name": "second_brain_add_idea",
    "description": (
        "Add an idea or note to the user's Second Brain (notes graph) with purpose-based colors. "
        "Use for ideas AND for new durable life facts (weekly homework, anime/TV they are watching, "
        "school habits, preferences) — save silently without asking permission. "
        "Purposes: 'work' (#2979ff blue), 'study' (#b388ff purple), "
        "'creative' (#ffd600 yellow), 'personal' (#00e676 green), 'urgent' (#ff1744 red), "
        "'tech' (#00e5ff cyan), 'finance' (#76ff03 lime), 'media' (#ff9100 orange), 'notes' (#ff4081 pink)."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short, clear title for the idea or note.",
            },
            "description": {
                "type": "string",
                "description": "Details, elaboration, context, or links for the idea.",
            },
            "purpose": {
                "type": "string",
                "enum": ["work", "study", "creative", "personal", "urgent", "tech", "finance", "media", "notes"],
                "description": "Category / purpose that determines the distinct color in the Second Brain graph.",
            },
            "genre_id": {
                "type": "string",
                "description": "Optional genre id to attach to.",
            },
        },
        "required": ["title"],
    },
}

SECOND_BRAIN_LIST_IDEAS: dict[str, Any] = {
    "name": "second_brain_list_ideas",
    "description": (
        "List, search, or inspect ideas and notes stored in the user's Second Brain. "
        "Can filter by purpose (e.g. 'study', 'work', 'creative') or search keyword."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "purpose": {
                "type": "string",
                "enum": ["work", "study", "creative", "personal", "urgent", "tech", "finance", "media", "notes"],
                "description": "Optional purpose filter.",
            },
            "search": {
                "type": "string",
                "description": "Optional search term to filter idea titles or descriptions.",
            },
        },
    },
}

SECOND_BRAIN_CLEAR_IDEAS: dict[str, Any] = {
    "name": "second_brain_clear_ideas",
    "description": (
        "Delete ALL ideas from the Second Brain (and their links). Genres stay. "
        "Use when the user says 'delete all ideas', 'clear my second brain', "
        "'wipe all notes from second brain'. Pass confirm=true only after they clearly want everything deleted."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "confirm": {
                "type": "boolean",
                "description": "Must be true to actually delete. Without it, returns a count preview only.",
            },
        },
        "required": ["confirm"],
    },
}

SECOND_BRAIN_ADD_GENRE: dict[str, Any] = {
    "name": "second_brain_add_genre",
    "description": "Create a new custom genre / category in the Second Brain graph.",
    "parameters": {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Genre / category name.",
            },
            "color": {
                "type": "string",
                "description": "Optional hex color e.g. '#00e5ff'.",
            },
        },
        "required": ["name"],
    },
}

MAPS_ETA: dict[str, Any] = {
    "name": "maps_eta",
    "description": (
        "Travel time in minutes between two places using free OpenStreetMap routing (no API key). "
        "Knows Kuwait areas and Kuwaiti spellings (Hiteen/Hitteen/حطين, Mishrif/Mishref/مشرف, Salmiya, Jahra, …). "
        "Use for: how long from A to B, ETA, من X لـ Y. Reply with minutes. Default English reply."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "origin": {
                "type": "string",
                "description": "Starting place (English or Arabic Kuwaiti name).",
            },
            "destination": {
                "type": "string",
                "description": "Destination place (English or Arabic Kuwaiti name).",
            },
            "profile": {
                "type": "string",
                "enum": ["driving", "walking"],
                "description": "Travel mode. Default driving.",
            },
        },
        "required": ["origin", "destination"],
    },
}

COMPOSIO_STATUS: dict[str, Any] = {
    "name": "composio_status",
    "description": (
        "Check whether Composio is connected/online (Composio Connect MCP in Hermes, or legacy COMPOSIO_API_KEY). "
        "Use when the user asks if Composio is connected. For real app actions and connecting apps, "
        "use the mcp__composio__* tools (COMPOSIO_MANAGE_CONNECTIONS, COMPOSIO_SEARCH_TOOLS, "
        "COMPOSIO_MULTI_EXECUTE_TOOL) when they are available."
    ),
    "parameters": {"type": "object", "properties": {}},
}

COMPOSIO_CONNECT: dict[str, Any] = {
    "name": "composio_connect",
    "description": (
        "Start a Composio Connect Link for an app toolkit (gmail, notion, github, slack, linear, …). "
        "Return the redirect URL so the user can sign in on the PC. "
        "Prefer mcp__composio__COMPOSIO_MANAGE_CONNECTIONS when available; this is the legacy fallback."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "toolkit": {
                "type": "string",
                "description": "App slug, e.g. gmail, notion, github, slack, googlecalendar.",
            },
        },
        "required": ["toolkit"],
    },
}

COMPOSIO_SETUP: dict[str, Any] = {
    "name": "composio_setup",
    "description": "Explain step-by-step how to add COMPOSIO_API_KEY and connect apps (never ask them to paste the key in chat).",
    "parameters": {"type": "object", "properties": {}},
}