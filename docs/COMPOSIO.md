# Composio + Jarvis

Connect many apps (Gmail, Notion, GitHub, Slack, …) through [Composio](https://composio.dev) without pasting keys into chat.

## One-time setup (you do this)

1. Create an account at [https://app.composio.dev](https://app.composio.dev)
2. Open **Settings** → copy your **API key**
3. Edit `C:\Users\Jasem\.hermes\.env` and add (do **not** commit this file):

```env
COMPOSIO_API_KEY=paste_your_key_here
COMPOSIO_USER_ID=jarvis_local
```

4. Install the SDK in the Jarvis venv:

```powershell
D:\jarvis_kokoro\jarvis-venv\Scripts\python.exe -m pip install composio
```

5. Restart **Hermes gateway** and **Jarvis** (`server.py`)
6. Open HUD → **CONNECT** → Composio card → **STATUS** (should say configured)
7. Click **CONNECT APP**, type e.g. `gmail` or `notion`, sign in in the browser link

Or ask Jarvis: “connect Notion with Composio” / “Composio setup”

## Safety

- Keep `COMPOSIO_API_KEY` only in `.env`
- Never put API keys or account passwords in Second Brain
- Prefer OAuth Connect Links over sharing passwords with Jarvis

## Photo notes → Second Brain

1. Open HUD chat
2. Tap **CAM**, photograph your notes
3. Type or say: **add these notes to my second brain**
4. Jarvis reads the photo and creates Second Brain ideas

Homework photos without that phrase still go to solve/homework mode.
