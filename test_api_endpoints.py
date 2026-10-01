import json
import urllib.request
import urllib.error
import sys

BASE_URL = "http://127.0.0.1:8765"
TOKEN = "jarvis-9f2517"
HEADERS = {
    "X-Jarvis-Token": TOKEN,
    "Content-Type": "application/json",
    "User-Agent": "JarvisTest/1.0"
}

def make_request(method, endpoint, data=None):
    url = f"{BASE_URL}{endpoint}"
    payload = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = body
            return status, parsed
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except Exception:
            parsed = body
        return e.code, parsed
    except Exception as e:
        return None, str(e)

print("=" * 60)
print("TEST 1: GET /api/study/status")
status, res = make_request("GET", "/api/study/status")
print(f"HTTP Status: {status}")
print(f"Full Response: {json.dumps(res, indent=2) if isinstance(res, dict) else res}")
if isinstance(res, dict):
    print("Extracted fields:")
    print(f"  status: {res.get('status')}")
    print(f"  elapsed: {res.get('elapsed')}")
    print(f"  total_cards: {res.get('total_cards')}")
    print(f"  active_subject: {res.get('active_subject')}")

print("\n" + "=" * 60)
print("TEST 2: GET /api/dual_brain/stats")
status, res = make_request("GET", "/api/dual_brain/stats")
print(f"HTTP Status: {status}")
print(f"Full Response: {json.dumps(res, indent=2) if isinstance(res, dict) else res}")
if isinstance(res, dict):
    print(f"Stats: {res}")

print("\n" + "=" * 60)
print("TEST 3: POST /api/dual_brain/ask (15 percent of 80)")
payload3 = {"text": "What is 15 percent of 80?"}
status, res = make_request("POST", "/api/dual_brain/ask", payload3)
print(f"HTTP Status: {status}")
print(f"Full Response: {json.dumps(res, indent=2) if isinstance(res, dict) else res}")
if isinstance(res, dict):
    print("Extracted fields:")
    print(f"  layer: {res.get('layer')}")
    print(f"  model: {res.get('model')}")
    print(f"  latency_ms: {res.get('latency_ms')}")
    print(f"  text: {res.get('text')}")

print("\n" + "=" * 60)
print("TEST 4: POST /api/dual_brain/ask (Open movies and search Spider-Man)")
payload4 = {"text": "Open movies and search Spider-Man"}
status, res = make_request("POST", "/api/dual_brain/ask", payload4)
print(f"HTTP Status: {status}")
print(f"Full Response: {json.dumps(res, indent=2) if isinstance(res, dict) else res}")
if isinstance(res, dict):
    print("Extracted fields:")
    print(f"  layer: {res.get('layer')}")
    print(f"  reason: {res.get('reason')}")

print("\n" + "=" * 60)
print("TEST 5: POST /api/chat (Why is the sky blue during the day?)")
payload5 = {"text": "Why is the sky blue during the day?", "conversation": "jarvis-main"}
status, res = make_request("POST", "/api/chat", payload5)
print(f"HTTP Status: {status}")
print(f"Full Response: {json.dumps(res, indent=2) if isinstance(res, dict) else res}")
if isinstance(res, dict):
    reply_text = res.get("text") or res.get("response") or res.get("reply") or str(res)
    contains_layer1 = "[Layer 1: Local Mind]" in reply_text
    print(f"Reply text: {reply_text}")
    print(f"Contains '[Layer 1: Local Mind]': {contains_layer1}")
elif isinstance(res, str):
    contains_layer1 = "[Layer 1: Local Mind]" in res
    print(f"Reply text: {res}")
    print(f"Contains '[Layer 1: Local Mind]': {contains_layer1}")

print("\n" + "=" * 60)
print("TEST RUN COMPLETE")
