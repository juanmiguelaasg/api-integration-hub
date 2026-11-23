"""Three small demo systems on one port, so the hub has something real to connect.

    CRM       /crm/...       X-API-Key: demo-crm-key        customers (source)
    ERP       /erp/...       Bearer demo-erp-token          partners  (target, upserts by external_id)
    Helpdesk  /helpdesk/...  Basic hub:demo                 tickets   (source for the Scrum backlog)

Demo controls (no auth):
    POST /__demo/outage?system=erp&down=1   – make a system return 503 (shows the health gate)
    POST /__demo/touch                      – change a CRM customer (shows 'updated' on the next sync)
    POST /__demo/new-customer               – add a CRM customer (shows 'created')
    POST /__demo/reset                      – back to the initial data

Run:  python mock_systems.py [--port 8100]
"""
from __future__ import annotations

import argparse
import base64
import copy
import json
import random
import threading
import unicodedata
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

AUTH = {
    "crm": ("X-API-Key", "demo-crm-key"),
    "erp": ("Authorization", "Bearer demo-erp-token"),
    "helpdesk": ("Authorization", "Basic " + base64.b64encode(b"hub:demo").decode()),
}

FIRST = ["Anna", "Bence", "Csilla", "Dániel", "Eszter", "Ferenc", "Gréta", "Hunor", "Ilona", "János"]
LAST = ["Kovács", "Nagy", "Tóth", "Szabó", "Horváth", "Varga", "Kiss", "Molnár", "Németh", "Farkas"]
COMPANIES = [("Danube Logistics Kft.", "hu"), ("Northwind GmbH", "de"), ("Contoso s.r.o.", "sk"),
             ("Fabrikam Zrt.", "hu"), ("Tailspin Ltd.", "gb"), ("Adatum Kft.", "hu")]


def _ascii(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _initial() -> dict:
    customers = []
    for i in range(1, 9):
        company, country = COMPANIES[i % len(COMPANIES)]
        first, last = FIRST[i % len(FIRST)], LAST[(i * 3) % len(LAST)]
        customers.append({
            "id": 1000 + i, "first_name": first, "last_name": last,
            "email": _ascii(f"{first}.{last}@example.com"),
            "company": {"name": company, "country": country},
            "status": "lead" if i in (3, 7) else "active", "updated_at": _now(),
        })
    tickets = [
        {"id": 501, "subject": "Invoices missing in ERP after CRM update", "priority": "critical", "status": "open",
         "customer_email": customers[0]["email"]},
        {"id": 502, "subject": "Partner country codes are lowercase", "priority": "high", "status": "open",
         "customer_email": customers[1]["email"]},
        {"id": 503, "subject": "Password reset e-mail delayed", "priority": "low", "status": "open",
         "customer_email": customers[2]["email"]},
        {"id": 504, "subject": "Duplicate partners after manual import", "priority": "high", "status": "open",
         "customer_email": customers[3]["email"]},
        {"id": 505, "subject": "Report export times out", "priority": "medium", "status": "closed",
         "customer_email": customers[4]["email"]},
    ]
    return {"customers": customers, "partners": {}, "tickets": tickets, "next_partner": 1, "down": set()}


STATE = _initial()
LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    server_version = "MockSystems/1.0"

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # ------------------------------------------------------------------ helpers
    def _send(self, status: int, body=None) -> None:
        data = b"" if body is None else json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            return {}

    def _route(self, method: str) -> None:
        url = urlsplit(self.path)
        parts = [p for p in url.path.split("/") if p]
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        if not parts:
            return self._send(200, {"systems": list(AUTH), "docs": "see mock_systems.py"})
        if parts[0] == "__demo":
            return self._demo(method, parts[1:], query)
        system, rest = parts[0], parts[1:]
        if system not in AUTH:
            return self._send(404, {"error": "unknown system"})
        if system in STATE["down"]:
            return self._send(503, {"error": f"{system} is down (demo outage)"})
        if rest == ["health"]:
            return self._send(200, {"status": "ok", "system": system})
        header, expected = AUTH[system]
        if self.headers.get(header) != expected:
            return self._send(401, {"error": "unauthorized"})
        handler = getattr(self, f"_{system}", None)
        return handler(method, rest, query)

    # ------------------------------------------------------------------ systems
    def _crm(self, method, rest, query):
        if method == "GET" and rest == ["api", "customers"]:
            with LOCK:
                return self._send(200, copy.deepcopy(STATE["customers"]))
        return self._send(404, {"error": "not found"})

    def _erp(self, method, rest, query):
        with LOCK:
            partners = STATE["partners"]
            if rest == ["api", "partners"] and method == "GET":
                return self._send(200, list(partners.values()))
            if rest == ["api", "partners"] and method == "POST":
                body = self._body()
                if not body.get("external_id") or not body.get("name"):
                    return self._send(422, {"error": "external_id and name are required"})
                existing = next((p for p in partners.values() if p["external_id"] == body["external_id"]), None)
                if existing:                       # upsert: never create a duplicate partner
                    existing.update(body, updated_at=_now())
                    return self._send(200, existing)
                pid = STATE["next_partner"]
                STATE["next_partner"] += 1
                partner = {"id": pid, **body, "created_at": _now()}
                partners[pid] = partner
                return self._send(201, partner)
            if len(rest) == 3 and rest[:2] == ["api", "partners"] and rest[2].isdigit():
                pid = int(rest[2])
                if pid not in partners:
                    return self._send(404, {"error": "partner not found"})
                if method == "PUT":
                    partners[pid].update(self._body(), updated_at=_now())
                    return self._send(200, partners[pid])
                if method == "GET":
                    return self._send(200, partners[pid])
        return self._send(404, {"error": "not found"})

    def _helpdesk(self, method, rest, query):
        if method == "GET" and rest == ["api", "tickets"]:
            with LOCK:
                return self._send(200, {"total": len(STATE["tickets"]), "tickets": copy.deepcopy(STATE["tickets"])})
        return self._send(404, {"error": "not found"})

    # ------------------------------------------------------------------ demo controls
    def _demo(self, method, rest, query):
        global STATE
        with LOCK:
            if rest == ["outage"]:
                system = query.get("system", "erp")
                (STATE["down"].add if query.get("down", "1") == "1" else STATE["down"].discard)(system)
                return self._send(200, {"down": sorted(STATE["down"])})
            if rest == ["touch"]:
                c = random.choice([c for c in STATE["customers"] if c["status"] == "active"])
                c["company"]["name"] = c["company"]["name"].replace(" (updated)", "") + " (updated)"
                c["updated_at"] = _now()
                return self._send(200, c)
            if rest == ["new-customer"]:
                i = len(STATE["customers"]) + 1
                first, last = random.choice(FIRST), random.choice(LAST)
                company, country = random.choice(COMPANIES)
                c = {"id": 1000 + i, "first_name": first, "last_name": last,
                     "email": f"new{i}@example.com", "company": {"name": company, "country": country},
                     "status": "active", "updated_at": _now()}
                STATE["customers"].append(c)
                return self._send(201, c)
            if rest == ["reset"]:
                STATE = _initial()
                return self._send(200, {"reset": True})
            if rest == ["state"]:
                return self._send(200, {"down": sorted(STATE["down"]), "customers": len(STATE["customers"]),
                                        "partners": len(STATE["partners"])})
        return self._send(404, {"error": "unknown demo action"})

    def do_GET(self):
        self._route("GET")

    def do_POST(self):
        self._route("POST")

    def do_PUT(self):
        self._route("PUT")


def make_server(port: int = 8100, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    global STATE
    STATE = _initial()
    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo CRM / ERP / Helpdesk APIs for API Integration Hub")
    parser.add_argument("--port", type=int, default=8100)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args()
    server = make_server(args.port, args.host)
    print(f"Demo systems on http://{args.host}:{args.port}  (crm, erp, helpdesk) – Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
