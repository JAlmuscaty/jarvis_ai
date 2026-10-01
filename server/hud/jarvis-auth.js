/* Shared Jarvis HUD auth — keep token across pages and always send it. */
(function (w) {
  const TOKEN_KEY = "jarvis_token";

  function readToken() {
    try {
      const q = new URLSearchParams(location.search).get("token");
      if (q) return q.trim();
    } catch (_) {}
    try {
      return (localStorage.getItem(TOKEN_KEY) || "").trim();
    } catch (_) {
      return "";
    }
  }

  function writeCookie(tok) {
    if (!tok) return;
    const secure = location.protocol === "https:" ? "; secure" : "";
    document.cookie =
      TOKEN_KEY +
      "=" +
      encodeURIComponent(tok) +
      "; path=/; max-age=31536000; samesite=lax" +
      secure;
  }

  function saveToken(tok) {
    const v = (tok || "").trim();
    if (!v) return;
    try {
      localStorage.setItem(TOKEN_KEY, v);
    } catch (_) {}
    writeCookie(v);
  }

  function seedFromUrl() {
    try {
      const q = new URLSearchParams(location.search).get("token");
      if (q) saveToken(q);
    } catch (_) {}
  }

  function authHeaders(extra) {
    const h = Object.assign({}, extra || {});
    const tok = readToken();
    if (tok) h["X-Jarvis-Token"] = tok;
    return h;
  }

  function withToken(url) {
    const tok = readToken();
    if (!tok) return url;
    try {
      const u = new URL(url, location.origin);
      if (!u.searchParams.get("token")) u.searchParams.set("token", tok);
      return u.pathname + u.search + u.hash;
    } catch (_) {
      const sep = url.indexOf("?") >= 0 ? "&" : "?";
      return url + sep + "token=" + encodeURIComponent(tok);
    }
  }

  function ensurePinGate() {
    let gate = document.getElementById("pinGate");
    if (gate) return gate;
    gate = document.createElement("div");
    gate.id = "pinGate";
    gate.style.cssText =
      "display:none;position:fixed;inset:0;z-index:9999;background:#020509f2;" +
      "flex-direction:column;align-items:center;justify-content:center;gap:14px;" +
      "font-family:Rajdhani,sans-serif";
    gate.innerHTML =
      '<div style="font-family:Orbitron,sans-serif;font-size:18px;letter-spacing:8px;color:#00e5ff">ACCESS CODE</div>' +
      '<input id="pinInput" type="password" autocomplete="off" style="background:#06101c;border:1px solid #0a7f96;' +
      "color:#cfeefb;padding:10px 14px;font-family:Orbitron,sans-serif;font-size:16px;letter-spacing:4px;" +
      'text-align:center;width:240px;outline:none">' +
      '<button id="pinBtn" type="button" style="background:#081523;border:1px solid #0a7f96;color:#00e5ff;' +
      "font-family:Orbitron,sans-serif;font-size:11px;letter-spacing:2px;padding:10px 18px;cursor:pointer\">AUTHENTICATE</button>" +
      '<div id="pinMsg" style="font-size:12px;color:#4d7d92;letter-spacing:2px">&nbsp;</div>';
    document.body.appendChild(gate);
    const btn = gate.querySelector("#pinBtn");
    const input = gate.querySelector("#pinInput");
    const submit = async () => {
      const v = (input.value || "").trim();
      if (!v) return;
      saveToken(v);
      try {
        const r = await fetch("/api/usage", { headers: authHeaders() });
        if (r.status === 401) {
          document.getElementById("pinMsg").textContent = "ACCESS DENIED";
          input.value = "";
          return;
        }
      } catch (_) {}
      location.reload();
    };
    btn.addEventListener("click", submit);
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") submit();
    });
    return gate;
  }

  function showPinGate(msg) {
    const gate = ensurePinGate();
    gate.style.display = "flex";
    const m = document.getElementById("pinMsg");
    if (m && msg) m.textContent = msg;
    const input = document.getElementById("pinInput");
    if (input) setTimeout(() => input.focus(), 50);
  }

  async function requireAuth() {
    seedFromUrl();
    // Persist whatever we already have so cookies work for APIs/WebSocket.
    const existing = readToken();
    if (existing) saveToken(existing);
    try {
      const r = await fetch("/api/usage", { headers: authHeaders() });
      if (r.status === 401) {
        showPinGate("Enter your Jarvis access code to unlock pages.");
        return false;
      }
    } catch (_) {
      // Network blip — still allow UI; API calls will re-check.
    }
    return true;
  }

  async function api(path, opts) {
    opts = opts || {};
    opts.headers = authHeaders(opts.headers || {});
    const r = await fetch(path, opts);
    if (r.status === 401) {
      showPinGate("Enter your Jarvis access code to unlock pages.");
      throw new Error(401);
    }
    if (!r.ok) throw new Error(await r.text());
    const ct = r.headers.get("content-type") || "";
    if (ct.indexOf("application/json") >= 0) return r.json();
    return r.text();
  }

  seedFromUrl();
  w.jarvisAuth = {
    readToken,
    saveToken,
    authHeaders,
    withToken,
    showPinGate,
    requireAuth,
    api,
  };
})(window);
