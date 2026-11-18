import os
import time

import httpx


class Handled(Exception):
    pass


class ApiError(Exception):
    pass


http = httpx.Client(
    base_url=os.environ["HELPDESK_URL"],
    headers={
        "Authorization": f"Bearer {os.environ['HELPDESK_KEY']}",
        "X-Candidate-Email": os.environ["CANDIDATE_EMAIL"],
        "X-Candidate-Name": os.environ.get("CANDIDATE_NAME", ""),
    },
    timeout=20,
)
gap = 0.25
last = 0.0


def pace():
    global last
    wait = last + gap - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    last = time.monotonic()


def call(method, path, body=None, tries=6):
    for n in range(tries):
        pace()
        try:
            r = http.request(method, path, json=body)
        except httpx.TransportError:
            if method == "POST":
                raise
            time.sleep(0.5 * 2**n)
            continue
        if r.status_code == 503:
            time.sleep(0.5 * 2**n)
            continue
        if r.status_code == 429:
            time.sleep(float(r.headers.get("Retry-After", 1)))
            continue
        if r.status_code == 409:
            raise Handled(path)
        if r.is_error:
            raise ApiError(f"{method} {path} -> {r.status_code} {r.text[:300]}")
        return r.json()
    raise ApiError(f"{method} {path} -> gave up after {tries} tries")


def status():
    return call("GET", "/status")


def examples():
    return call("GET", "/examples")["examples"]


def ticket(id):
    return call("GET", f"/tickets/{id}")


def tickets(state="open"):
    cursor = None
    while True:
        q = f"/tickets?limit=10&status={state}" + (f"&cursor={cursor}" if cursor else "")
        page = call("GET", q)
        yield from page["tickets"]
        cursor = page.get("next_cursor")
        if not cursor:
            return


def send(id, action, body):
    for n in range(4):
        try:
            return call("POST", f"/tickets/{id}/{action}", body)
        except httpx.TransportError:
            if ticket(id).get("handled"):
                return {"ok": True, "recovered": True}
            time.sleep(0.5 * 2**n)
    raise ApiError(f"POST {id}/{action} -> network kept failing")


def reset():
    return call("POST", "/practice/reset")
