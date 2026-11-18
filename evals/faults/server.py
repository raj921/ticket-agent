import json
import random
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

port, src, logfile = int(sys.argv[1]), sys.argv[2], sys.argv[3]
cfg = json.loads(sys.argv[4])
keep = ("id", "subject", "body", "channel", "customer_plan", "received_at")
tickets = {t["id"]: {k: t[k] for k in keep} for t in json.load(open(src))["tickets"]}
handled = {}
lock = threading.Lock()
rng = random.Random(cfg.get("seed", 7))
recent = deque()
seen = {"all": 0, "list": 0, "post": 0}
cats = {"bug", "billing", "feature_request", "question", "other"}
need = {"reply": "draft_reply", "handoff": "handoff_note", "close": None}


def record(entry):
    with open(logfile, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def problems(action, b):
    bad = []
    if b.get("language") not in {"nl", "en", "de"}:
        bad.append("language")
    if b.get("category") not in cats:
        bad.append("category")
    if b.get("priority") not in {"P1", "P2", "P3", "P4"}:
        bad.append("priority")
    if not str(b.get("reason", "")).strip():
        bad.append("reason")
    if need[action] and not str(b.get(need[action], "")).strip():
        bad.append(need[action])
    return bad


class Desk(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def reply(self, code, body, extra=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)
        self.done(code)

    def done(self, code, **more):
        record({"t": time.time(), "method": self.command, "path": self.path, "status": code, **more})

    def gate(self, kind):
        if self.headers.get("Authorization") != f"Bearer {cfg['key']}":
            return self.reply(401, {"error": "unauthorized"}) or True
        if not self.headers.get("X-Candidate-Email"):
            return self.reply(400, {"error": "missing_email"}) or True
        with lock:
            now = time.time()
            seen["all"] += 1
            if kind:
                seen[kind] += 1
            n, k = seen["all"], seen.get(kind, 0)
            while recent and now - recent[0] > 1:
                recent.popleft()
            recent.append(now)
            busy = len(recent) > 5
        if busy or n == cfg.get("throttle_at"):
            return self.reply(429, {"error": "rate_limited"}, {"Retry-After": "1"}) or True
        forced = k in cfg.get("fail", {}).get(kind or "", [])
        if kind and (forced or rng.random() < cfg.get("rate", 0)):
            return self.reply(503, {"error": "service_unavailable"}) or True
        return False

    def do_GET(self):
        u = urlparse(self.path)
        parts = u.path.strip("/").split("/")
        if u.path == "/_state":
            return self.reply(200, {"handled": handled})
        if u.path == "/status":
            if self.gate(None):
                return
            return self.reply(200, {"mode": "practice", "open_tickets": len(tickets) - len(handled), "handled_tickets": len(handled)})
        if parts[0] == "tickets" and len(parts) == 1:
            if self.gate("list"):
                return
            q = parse_qs(u.query)
            limit = min(int(q.get("limit", ["10"])[0]), 10)
            cursor = q.get("cursor", [None])[0]
            state = q.get("status", ["open"])[0]
            ids = [i for i in sorted(tickets) if state == "all" or i not in handled]
            if cursor:
                ids = [i for i in ids if i > cursor]
            page = ids[:limit]
            nxt = page[-1] if len(ids) > limit else None
            return self.reply(200, {"tickets": [{**tickets[i], "handled": (handled.get(i) or {}).get("action")} for i in page], "next_cursor": nxt})
        if parts[0] == "tickets" and len(parts) == 2:
            if self.gate(None):
                return
            if parts[1] not in tickets:
                return self.reply(404, {"error": "not_found"})
            h = handled.get(parts[1])
            return self.reply(200, {**tickets[parts[1]], "handled": h and {"at": h["at"], "action": h["action"]}})
        return self.reply(404, {"error": "not_found"})

    def do_POST(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        size = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(size) if size else b""
        if parts == ["practice", "reset"]:
            if self.gate(None):
                return
            handled.clear()
            return self.reply(200, {"reset": True})
        if len(parts) != 3 or parts[0] != "tickets" or parts[2] not in need:
            return self.reply(404, {"error": "not_found"})
        id, action = parts[1], parts[2]
        if self.gate("post"):
            return
        if id not in tickets:
            return self.reply(404, {"error": "not_found"})
        try:
            b = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self.reply(400, {"error": "invalid_json"})
        bad = problems(action, b)
        if bad:
            return self.reply(422, {"error": "validation_failed", "problems": bad})
        with lock:
            if id in handled:
                return self.reply(409, {"error": "already_handled"})
            handled[id] = {"action": action, **b, "at": time.time()}
        if id == cfg.get("drop"):
            self.close_connection = True
            return self.done(0, dropped=True)
        return self.reply(200, {"ok": True, "id": id, "action": action})


ThreadingHTTPServer(("127.0.0.1", port), Desk).serve_forever()
