# Hey Jarvis on iPhone vs PC

## The hard limit (iPhone)

**A website cannot listen for "Hey Jarvis" while you are in another app or tab.**  
Apple only allows always-on wake words for **Siri** and native apps with special entitlements — not for Safari or Home Screen web apps.

Jarvis in the browser **cannot** do what Siri does in the background on iPhone. This is not a bug in your setup.

## What works instead

### PC (best) — true "Hey Jarvis" without opening the site

A **native wake-word client** runs on your Windows PC (microphone + speakers):

1. Flag file exists: `D:\jarvis_kokoro\WAKE_CLIENT_ENABLED`
2. Autostart launches `run-wake-client.bat` after Jarvis is up
3. Say **"Hey Jarvis"** near the PC mic — no browser tab needed
4. Keep talking; say **"stop"** to end the session

Install deps once:

```powershell
D:\jarvis_kokoro\jarvis-venv\Scripts\pip.exe install -r C:\Users\Jasem\Desktop\jarvis_ai\client\requirements-client.txt
```

Manual test:

```powershell
D:\jarvis_kokoro\jarvis-venv\Scripts\python.exe C:\Users\Jasem\Desktop\jarvis_ai\client\client.py
```

To disable: delete `D:\jarvis_kokoro\WAKE_CLIENT_ENABLED` and reboot (or kill the client process).

### iPhone (closest option) — "Hey Siri, Jarvis"

Apple allows **Hey Siri** to run a Shortcut. That is the closest you can get on iPhone without a native App Store app.

1. Open the **Shortcuts** app on iPhone
2. **+** → name it **Jarvis**
3. Add action **Open URL**
4. URL (use your **stable home Wi‑Fi** address, not the daily tunnel):

   ```
   https://YOUR_LAN_IP/hud/?wake=1&token=jarvis-9f2517
   ```

   Example: `https://192.168.1.57/hud/?wake=1&token=jarvis-9f2517`

5. Save. Then say: **"Hey Siri, Jarvis"**

Siri opens Jarvis and starts listening immediately. You still **briefly see Jarvis** — iOS requires that for mic access.

### iPhone while Jarvis is already open

Tap **HEY JARVIS** and **stay on the Jarvis screen**. Say "Hey Jarvis", talk, then "Stop".

## Calendar → phone reminders

Jarvis cannot write into Apple **Reminders.app** directly (Apple blocks that for web apps). Instead:

1. Open Jarvis HUD → **Connect** → link **Google Calendar** (reconnect if you linked it before — write permission is required now).
2. On iPhone: **Settings → Calendar → Accounts** → add the same Google account (or turn Calendar on for it).
3. Allow **Calendar** notifications on the phone.
4. When you ask Jarvis to add something to the calendar (or Classroom import adds dues), Jarvis also creates a **Google Calendar** event with alerts **30 minutes before** and **at the time**.

Your phone then reminds you through the Calendar app — same reliability as a normal calendar alert.

Optional Apple Reminders.app: set `JARVIS_APPLE_REMINDERS=1`, keep the phone HUD open, and create an iOS Shortcut named **Jarvis Reminder** that takes Text and runs **Add New Reminder**.

## Summary

| Goal | Solution |
|------|----------|
| Hey Jarvis, browser closed | **PC wake client** |
| Hey Jarvis, other phone apps | **Not possible** via web — use **Hey Siri, Jarvis** shortcut |
| Talk without button, Jarvis on screen | **HEY JARVIS** button on HUD |
| Calendar item → phone alert | **Google Calendar** link + iPhone Calendar account |
