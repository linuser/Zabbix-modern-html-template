#!/usr/bin/env python3
"""
End-to-end test runner - runs inside the "runner" container (see ../compose.yaml).

    run.py scenario   build the media types, import them into a real Zabbix, fire
                      problems / an update / recoveries, collect every mail from
                      Mailpit and check it; screenshots if E2E_SCREENSHOTS is set
    run.py previews   only screenshot the build's HTML previews (no Zabbix needed)
    run.py docs       scenario for standard + compact in English, then write the README
                      images to /docs-img (docs/img, mounted by e2e.sh docs)

Everything lands in /output (test/e2e/output on the host); open output/index.html.
"""
import html
import json
import os
import re
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path("/work")
OUT = Path("/output")
DIST = Path("/tmp/dist")
LOGO = REPO / "src" / "preview" / "logo.svg"

ZBX_API = os.environ.get("ZBX_API", "http://zabbix-web:8080/api_jsonrpc.php")
ZBX_SERVER = (os.environ.get("ZBX_SERVER", "zabbix-server"), 10051)
MAILPIT = os.environ.get("MAILPIT_URL", "http://mailpit:8025")
WEB_PORT = os.environ.get("ZBX_WEB_PORT", "8080")
MAILPIT_UI = f"http://localhost:{os.environ.get('MAILPIT_PORT', '8025')}"
ASSETS_PORT = os.environ.get("ASSETS_PORT", "8081")
TIMEOUT = int(os.environ.get("E2E_TIMEOUT", "180"))
# Seconds between creating the test service and firing its problem. Must exceed the
# server's ServiceManagerSyncFrequency (default 60), see fire_events().
SERVICE_SYNC_WAIT = int(os.environ.get("E2E_SERVICE_SYNC_WAIT", "70"))


def env_list(name, default=""):
    return [x.strip() for x in os.environ.get(name, default).split(",") if x.strip()]


VARIANTS = env_list("E2E_VARIANTS")
LANGS = env_list("E2E_LANGS")
MODES = [m for m in env_list("E2E_SCREENSHOTS") if m != "none"]  # default: no screenshots

HOST = "e2e-host"
GROUP = "E2E"
# Zabbix does not notify users about their own problem updates, so the acknowledgement
# is made by this user and the notifications go to Admin.
OPERATOR = {"username": "e2e-operator", "password": "Zbx-Mail-Test-7431!"}  # must not contain the user's names
SERVICE_SEVERITY = 4  # the trigger of this severity also drives the test service
# Since Zabbix 8.0 trapper items only accept values from {$TRAPPER.ALLOWED_HOSTS}
# (default 127.0.0.1); the runner sends from another container.
TRAPPER_HOSTS = "0.0.0.0/0"

# Mails expected per media type, classified by subject (subjects come from src/messages.yaml).
KINDS = [
    ("trigger problem", r"^Problem: ", 6),
    ("trigger update", r"^Updated problem", 1),
    ("trigger recovery", r"^Resolved in ", 6),
    ("service problem", r'^Service ".*" problem', 1),
    ("service recovery", r'^Service ".*" resolved', 1),
    ("service update", r"^Changed ", 1),
    ("internal problem", r"^Internal: ", 1),
    ("internal recovery", r"^Internal resolved", 1),
]

UNRESOLVED = re.compile(r"\{\$?[A-Z][A-Z0-9_.]*\}|\*UNKNOWN\*")

# Full-page screenshots are at least as tall as the viewport - keep it low so every
# screenshot ends where the mail ends.
MODE_CONTEXT = {
    "desktop": dict(viewport={"width": 680, "height": 200}),
    "mobile": dict(viewport={"width": 390, "height": 200}, device_scale_factor=2, is_mobile=True, has_touch=True),
    "dark": dict(viewport={"width": 680, "height": 200}, color_scheme="dark"),
}


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def http(url, data=None, method=None, headers=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, body, method=method, headers={"Content-Type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:  # e.g. Mailpit answers "ok" to DELETE
        return raw.decode(errors="replace")


def wait_for(what, check, timeout, interval=3):
    """Call check() until it returns something truthy."""
    deadline = time.time() + timeout
    last_error = None
    while time.time() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as e:
            last_error = e
        time.sleep(interval)
    raise TimeoutError(f"timed out waiting for {what}" + (f" (last error: {last_error})" if last_error else ""))


# --- build ----------------------------------------------------------------------

def build(preview=False):
    cmd = [sys.executable, str(REPO / "build.py"), "--out", str(DIST)] + (["--preview"] if preview else [])
    log("building:", " ".join(cmd))
    subprocess.run(cmd, check=True)
    sys.path.insert(0, str(REPO))
    import build as build_module  # noqa: E402 - the repository's build.py
    return build_module.Builder()


def selected_media(builder):
    cfg = builder.cfg
    media = []
    for variant in cfg["variants"]:
        if VARIANTS and variant["id"] not in VARIANTS:
            continue
        for lang in cfg["languages"]:
            if LANGS and lang not in LANGS:
                continue
            name, filename = builder.names(variant, lang)
            media.append(dict(variant=variant["id"], lang=lang, name=name, file=DIST / "yaml" / filename,
                              sendto=f"{variant['id']}.{lang}@e2e.test"))
    if not media:
        sys.exit("E2E_VARIANTS / E2E_LANGS select nothing")
    return media


# --- Zabbix ---------------------------------------------------------------------

class Zabbix:
    def __init__(self, url):
        self.url, self.token, self.id = url, None, 0

    def call(self, method, params):
        self.id += 1
        headers = {"Content-Type": "application/json-rpc"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        resp = http(self.url, {"jsonrpc": "2.0", "method": method, "params": params, "id": self.id}, headers=headers)
        if "error" in resp:
            raise RuntimeError(f"{method}: {resp['error'].get('data') or resp['error']}")
        return resp["result"]

    def login(self, username="Admin", password="zabbix"):
        version = wait_for("Zabbix API", lambda: self.call("apiinfo.version", {}), 300)
        self.token = wait_for("Zabbix login", lambda: self.call("user.login", {"username": username, "password": password}), 120)
        log(f"Zabbix API {version}, logged in as {username}")
        return self


def zabbix_send(values):
    """Push trapper values with the Zabbix sender protocol; returns (processed, server info)."""
    payload = json.dumps({"request": "sender data",
                          "data": [{"host": HOST, "key": k, "value": str(v)} for k, v in values]}).encode()
    with socket.create_connection(ZBX_SERVER, timeout=10) as s:
        s.sendall(b"ZBXD\x01" + struct.pack("<II", len(payload), 0) + payload)
        resp = b""
        while chunk := s.recv(65536):
            resp += chunk
    info = json.loads(resp[13:].decode()).get("info", "")
    match = re.search(r"processed: (\d+)", info)
    return (int(match.group(1)) if match else 0), info


def setup(z, media, builder):
    admin = z.call("user.get", {"filter": {"username": "Admin"}, "output": ["userid"]})[0]["userid"]

    # Leftovers of a previous run. Actions first: the service action references the service.
    actions = z.call("action.get", {"search": {"name": "E2E "}, "startSearch": True, "output": ["actionid"]})
    if actions:
        z.call("action.delete", [a["actionid"] for a in actions])

    # The service comes first - the service manager has to know it before its problem
    # arrives (see fire_events).
    services = z.call("service.get", {"search": {"name": "E2E "}, "startSearch": True, "output": ["serviceid"]})
    if services:
        z.call("service.delete", [s["serviceid"] for s in services])
    serviceid = z.call("service.create", {"name": "E2E online shop", "algorithm": 2, "sortorder": 0,
                                          "problem_tags": [{"tag": "e2e-service", "operator": 0, "value": "shop"}]})["serviceids"][0]
    service_created = time.time()

    log(f"importing {len(media)} media types")
    for m in media:
        z.call("configuration.import", {"format": "yaml", "source": m["file"].read_text(encoding="utf-8"),
                                        "rules": {"mediaTypes": {"createMissing": True, "updateExisting": True}}})
    ids = {mt["name"]: mt["mediatypeid"] for mt in
           z.call("mediatype.get", {"output": ["mediatypeid", "name"], "filter": {"name": [m["name"] for m in media]}})}
    for m in media:
        m["id"] = ids[m["name"]]
        z.call("mediatype.update", {"mediatypeid": m["id"], "status": 0, "smtp_server": "mailpit", "smtp_port": "1025",
                                    "smtp_helo": "zabbix.e2e", "smtp_email": "zabbix@e2e.test",
                                    "smtp_security": 0, "smtp_authentication": 0})

    macros = {
        "{$ZABBIXHOST}": f"localhost:{WEB_PORT}",
        "{$ZABBIXHOST_LINK}": f"http://localhost:{WEB_PORT}",
        "{$ZABBIXHOST_LOGO}": f"http://localhost:{ASSETS_PORT}/logo.svg",
        "{$CUSTOM_MESSAGE_COMPANY}": "ACME Corp - E2E test",
        "{$ZABBIXHOST_LOVE}": "Created with Open Source and ❤️",
    }
    existing = {m["macro"]: m["globalmacroid"] for m in
                z.call("usermacro.get", {"globalmacro": True, "output": ["globalmacroid", "macro"]})}
    for macro, value in macros.items():
        if macro in existing:
            z.call("usermacro.updateglobal", {"globalmacroid": existing[macro], "value": value})
        else:
            z.call("usermacro.createglobal", {"macro": macro, "value": value})

    z.call("user.update", {"userid": admin, "medias": [
        {"mediatypeid": m["id"], "sendto": [m["sendto"]], "active": 0, "severity": 63, "period": "1-7,00:00-24:00"}
        for m in media]})

    old = z.call("user.get", {"filter": {"username": OPERATOR["username"]}, "output": ["userid"]})
    if old:
        z.call("user.delete", [u["userid"] for u in old])
    role = z.call("role.get", {"filter": {"name": "Super admin role"}, "output": ["roleid"]})[0]["roleid"]
    usrgrp = z.call("usergroup.get", {"filter": {"name": "Zabbix administrators"}, "output": ["usrgrpid"]})[0]["usrgrpid"]
    z.call("user.create", {"username": OPERATOR["username"], "passwd": OPERATOR["password"], "name": "E2E",
                           "surname": "Operator", "roleid": role, "usrgrps": [{"usrgrpid": usrgrp}]})

    for h in z.call("host.get", {"filter": {"host": [HOST]}, "output": ["hostid"]}):
        z.call("host.delete", [h["hostid"]])

    groups = z.call("hostgroup.get", {"filter": {"name": [GROUP]}, "output": ["groupid"]})
    groupid = groups[0]["groupid"] if groups else z.call("hostgroup.create", {"name": GROUP})["groupids"][0]
    hostid = z.call("host.create", {
        "host": HOST, "name": "E2E test host", "groups": [{"groupid": groupid}],
        "interfaces": [{"type": 1, "main": 1, "useip": 1, "ip": "192.0.2.10", "dns": "", "port": "10050"}],
    })["hostids"][0]

    levels = builder.palette["severity"]["levels"]
    itemids = {}
    for n in sorted(levels):
        itemids[n] = z.call("item.create", {"hostid": hostid, "name": f"E2E severity {n}", "key_": f"e2e.sev{n}",
                                            "type": 2, "value_type": 3, "trapper_hosts": TRAPPER_HOSTS})["itemids"][0]
        tags = [{"tag": "scope", "value": "e2e"}]
        if n == SERVICE_SEVERITY:
            tags.append({"tag": "e2e-service", "value": "shop"})
        z.call("trigger.create", {"description": f"E2E {levels[n]['name']}: test problem on {{HOST.NAME}}",
                                  "expression": f"last(/{HOST}/e2e.sev{n})=1", "priority": n,
                                  "opdata": "Value: {ITEM.LASTVALUE}", "tags": tags})
    # A calculated item that divides by zero becomes "not supported" -> internal event.
    calc = z.call("item.create", {"hostid": hostid, "name": "E2E unsupported item", "key_": "e2e.unsupported",
                                  "type": 15, "value_type": 0, "params": "1/0", "delay": "5s"})["itemids"][0]

    message = {"operationtype": 0, "opmessage": {"default_msg": 1, "mediatypeid": "0"}, "opmessage_usr": [{"userid": admin}]}
    in_group = {"conditiontype": 0, "operator": 0, "value": groupid}
    z.call("action.create", {"name": "E2E trigger notifications", "eventsource": 0, "status": 0, "esc_period": "1h",
                             "filter": {"evaltype": 0, "conditions": [in_group]},
                             "operations": [message], "recovery_operations": [message], "update_operations": [message]})
    z.call("action.create", {"name": "E2E internal notifications", "eventsource": 3, "status": 0, "esc_period": "1h",
                             "filter": {"evaltype": 0, "conditions": [{"conditiontype": 23, "operator": 0, "value": "0"}, in_group]},
                             "operations": [message], "recovery_operations": [message]})
    z.call("action.create", {"name": "E2E service notifications", "eventsource": 4, "status": 0, "esc_period": "1h",
                             # conditiontype 27 = service (25 would be "event tag")
                             "filter": {"evaltype": 0, "conditions": [{"conditiontype": 27, "operator": 0, "value": serviceid}]},
                             "operations": [message], "recovery_operations": [message], "update_operations": [message]})
    log("service, host, items, triggers and actions created")
    return hostid, calc, itemids, service_created


# --- Mailpit --------------------------------------------------------------------

def mail_count():
    return http(f"{MAILPIT}/api/v1/messages?limit=1")["total"]


def wait_mails(expected, label):
    log(f"waiting for {expected} mails ({label})")
    try:
        wait_for(f"{expected} mails", lambda: mail_count() >= expected, TIMEOUT, interval=2)
    except TimeoutError:
        log(f"WARNING: only {mail_count()} of {expected} mails arrived ({label}) - continuing")


def all_messages():
    messages, start = [], 0
    while True:
        page = http(f"{MAILPIT}/api/v1/messages?start={start}&limit=500")
        messages += page["messages"]
        start += len(page["messages"])
        if not page["messages"] or start >= page["total"]:
            return messages


def fire_events(z, hostid, calc, itemids, service_created, per_round):
    keys = {n: f"e2e.sev{n}" for n in itemids}
    others = [k for n, k in keys.items() if n != SERVICE_SEVERITY]

    # On a re-run the server may still have the previous e2e-host in its configuration
    # cache and accept values for its deleted items - so wait until the *new* items have data.
    def items_ready():
        processed, info = zabbix_send([(k, 0) for k in keys.values()])
        if processed < len(keys):
            raise RuntimeError(f"server answered '{info}' - see test/e2e/e2e.sh logs zabbix-server")
        items = z.call("item.get", {"itemids": list(itemids.values()), "output": ["lastclock"]})
        return len(items) == len(itemids) and all(int(i["lastclock"]) > 0 for i in items)

    log("waiting for the server to pick up the test items")
    wait_for("the test items to receive data", items_ready, 180)

    log("problems: every severity except the service one, internal (unsupported item)")
    zabbix_send([(k, 1) for k in others])
    expected = per_round * (len(others) + 1)
    wait_mails(expected, "problems")

    # The service manager creates a service event only when a service it already knows
    # changes status, and it loads new services every ServiceManagerSyncFrequency
    # (default 60 s). A problem arriving earlier just becomes the initial status: no mail.
    remaining = SERVICE_SYNC_WAIT - (time.time() - service_created)
    if remaining > 0:
        log(f"waiting {remaining:.0f}s until the service manager has loaded the test service")
        time.sleep(remaining)
    log("problem: the service trigger - trigger problem + service problem")
    zabbix_send([(keys[SERVICE_SEVERITY], 1)])
    expected += per_round * 2
    wait_mails(expected, "service problem")

    problem = wait_for("the problem to acknowledge", lambda: z.call("problem.get", {
        "hostids": [hostid], "severities": [SERVICE_SEVERITY], "output": ["eventid"]}), 60)
    # One update: acknowledge (2) + message (4) + change severity (8). The new severity
    # also changes the service status - trigger update + service update.
    log(f"update: {OPERATOR['username']} acknowledges, comments and raises the severity to Disaster")
    Zabbix(ZBX_API).login(**OPERATOR).call("event.acknowledge", {
        "eventids": [problem[0]["eventid"]], "action": 14, "message": "E2E: looking into it", "severity": 5})
    expected += per_round * 2
    wait_mails(expected, "trigger update + service update")

    log("recovery: every severity, service, internal")
    z.call("item.update", {"itemid": calc, "params": "1"})
    zabbix_send([(k, 0) for k in keys.values()])
    expected += per_round * (len(keys) + 2)
    wait_mails(expected, "recoveries")


def slug(text, limit=80):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:limit]


def collect(media):
    by_address = {m["sendto"]: m for m in media}
    mails = []
    for summary in all_messages():
        detail = http(f"{MAILPIT}/api/v1/message/{summary['ID']}")
        address = detail["To"][0]["Address"] if detail.get("To") else ""
        m = by_address.get(address)
        if not m:
            continue
        kind = next((k for k, pattern, _ in KINDS if re.search(pattern, detail["Subject"])), "other")
        body = detail.get("HTML") or f"<pre>{html.escape(detail.get('Text', ''))}</pre>"
        path = OUT / "mails" / m["variant"] / m["lang"] / f"{slug(kind)}--{slug(detail['Subject'])}.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        mails.append(dict(variant=m["variant"], lang=m["lang"], kind=kind, subject=detail["Subject"], html=path,
                          unresolved=sorted(set(UNRESOLVED.findall(detail["Subject"] + body)))))
    return mails


def report(media, mails):
    """Mail counts per media type, plus macros Zabbix left unresolved (a template using a
    macro that this event source or Zabbix version does not support)."""
    ok = True
    lines = []
    for m in media:
        counts = {k: 0 for k, _, _ in KINDS}
        unresolved = {}
        for mail in mails:
            if mail["variant"] == m["variant"] and mail["lang"] == m["lang"]:
                if mail["kind"] in counts:
                    counts[mail["kind"]] += 1
                if mail["unresolved"]:
                    unresolved.setdefault(mail["kind"], set()).update(mail["unresolved"])
        missing = {k: want - counts[k] for k, _, want in KINDS if counts[k] < want}
        ok &= not missing and not unresolved
        lines.append(f"{m['name']:50} {sum(counts.values()):3} mails"
                     + (f"  MISSING {missing}" if missing else "")
                     + "".join(f"  UNRESOLVED in {k}: {' '.join(sorted(v))}" for k, v in sorted(unresolved.items())))
    print("\n".join(lines), flush=True)
    (OUT / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return ok


# --- screenshots + gallery ----------------------------------------------------------

def screenshot(jobs):
    """jobs: list of (source, png) - source is an HTML file; mode is the png's first directory below OUT/screenshots."""
    if not MODES or not jobs:
        return
    from playwright.sync_api import sync_playwright
    log(f"screenshots: {len(jobs)} x {', '.join(MODES)}")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for mode in MODES:
            context = browser.new_context(**MODE_CONTEXT[mode])
            context.route(re.compile(r".*/logo\.svg$"), lambda route: route.fulfill(path=str(LOGO)))
            page = context.new_page()
            for source, png in jobs:
                target = OUT / "screenshots" / mode / png
                target.parent.mkdir(parents=True, exist_ok=True)
                page.goto(source.as_uri(), wait_until="load")
                page.screenshot(path=str(target), full_page=True)
            context.close()
        browser.close()


def gallery(title, sections, note=""):
    """sections: {heading: [(caption, html_path, png_relpath)]}"""
    parts = [f"<!DOCTYPE html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title><style>"
             "body{font-family:system-ui,sans-serif;margin:24px;background:#eef0f3;color:#16191d}"
             "h2{margin:32px 0 8px;font-size:18px}.grid{display:flex;flex-wrap:wrap;gap:16px;align-items:flex-start}"
             "figure{margin:0;background:#fff;padding:8px;border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.1)}"
             "figcaption{font-size:12px;max-width:340px;margin-bottom:6px}.shots{display:flex;gap:6px;align-items:flex-start}"
             "img{width:340px;border:1px solid #ddd}img.mobile{width:170px}.mode{font-size:10px;color:#667}</style></head><body>",
             f"<h1>{html.escape(title)}</h1>{note}"]
    for heading, items in sections.items():
        parts.append(f"<h2>{html.escape(heading)}</h2><div class='grid'>")
        for caption, source, png in items:
            shots = "".join(
                f"<a href='screenshots/{mode}/{png}'><div class='mode'>{mode}</div>"
                f"<img class='{mode}' loading='lazy' src='screenshots/{mode}/{png}'></a>" for mode in MODES)
            parts.append(f"<figure><figcaption>{html.escape(caption)} &middot; "
                         f"<a href='{source.relative_to(OUT)}'>html</a></figcaption><div class='shots'>{shots}</div></figure>")
        parts.append("</div>")
    parts.append("</body></html>")
    (OUT / "index.html").write_text("\n".join(parts), encoding="utf-8")


DOCS_IMG = Path("/docs-img")  # docs/img of the repository, mounted by `e2e.sh docs`


def docs_images(target):
    """Compose the README images from the screenshots of the docs scenario."""
    import yaml
    from PIL import Image

    shots = OUT / "screenshots"
    levels = yaml.safe_load((REPO / "src" / "themes.yaml").read_text(encoding="utf-8"))["severity"]["levels"]
    problem = "trigger-problem--problem-e2e-{}-*.png"

    def shot(mode, variant, pattern):
        hits = sorted((shots / mode / variant / "en").glob(pattern))
        if not hits:
            raise FileNotFoundError(f"no screenshot {mode}/{variant}/en/{pattern}")
        return Image.open(hits[0]).convert("RGB")

    def width(image, w):
        return image.resize((w, round(image.height * w / image.width)), Image.LANCZOS)

    def sheet(name, images, cols, gap=16):
        rows = [images[i:i + cols] for i in range(0, len(images), cols)]
        canvas = Image.new("RGB", (max(sum(im.width for im in r) + gap * (len(r) - 1) for r in rows),
                                   sum(max(im.height for im in r) for r in rows) + gap * (len(rows) - 1)), "#ffffff")
        y = 0
        for r in rows:
            x = 0
            for im in r:
                canvas.paste(im, (x, y))
                x += im.width + gap
            y += max(im.height for im in r) + gap
        canvas = canvas.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        canvas.save(target / name, optimize=True)
        log(f"docs/img/{name}: {canvas.width}x{canvas.height}, {(target / name).stat().st_size // 1024} KiB")

    sheet("standard-vs-compact.png",
          [width(shot("desktop", v, problem.format("high")), 510) for v in ("standard", "compact")], 2)
    sheet("severities.png",
          [width(shot("desktop", "compact", problem.format(slug(levels[n]["name"]))), 340)
           for n in sorted(levels, reverse=True)], 3)
    sheet("mobile-dark.png",
          [width(shot("mobile", "compact", problem.format("high")), 300),
           width(shot("dark", "standard", problem.format("average")), 510)], 2)
    sheet("message-types.png",
          [width(shot("desktop", "compact", p), 510) for p in
           ("trigger-update--*", "trigger-recovery--*disaster*", "service-problem--*", "internal-problem--*")], 2)


def clean_output():
    for sub in ("mails", "screenshots", "previews"):
        subprocess.run(["rm", "-rf", str(OUT / sub)], check=True)
    for f in ("index.html", "summary.txt"):
        (OUT / f).unlink(missing_ok=True)


# --- commands ---------------------------------------------------------------------

def cmd_previews():
    global MODES
    MODES = MODES or ["desktop"]  # screenshots are the point of this command
    clean_output()
    build(preview=True)
    target = OUT / "previews"
    subprocess.run(["cp", "-r", str(DIST / "previews"), str(target)], check=True)
    files = sorted(f for f in target.glob("*.html") if f.name != "index.html")
    jobs = [(f, f.with_suffix(".png").name) for f in files]
    screenshot(jobs)
    sections = {}
    for f, png in jobs:
        sections.setdefault(f.name.split("_")[0], []).append((f.stem, f, png))
    gallery("Zabbix mail previews (sample data)", sections)
    log(f"done - open test/e2e/output/index.html")


def cmd_scenario():
    clean_output()
    builder = build()
    media = selected_media(builder)
    z = Zabbix(ZBX_API)
    z.login()
    wait_for("Mailpit", lambda: http(f"{MAILPIT}/api/v1/info"), 60)
    http(f"{MAILPIT}/api/v1/messages", {}, method="DELETE")
    hostid, calc, itemids, service_created = setup(z, media, builder)
    fire_events(z, hostid, calc, itemids, service_created, len(media))

    mails = collect(media)
    ok = report(media, mails)
    order = {k: i for i, (k, _, _) in enumerate(KINDS)}
    mails.sort(key=lambda m: (m["variant"], m["lang"], order.get(m["kind"], 99), m["subject"]))
    jobs = [(m["html"], str(m["html"].relative_to(OUT / "mails").with_suffix(".png"))) for m in mails]
    screenshot(jobs)
    sections = {}
    for m, (_, png) in zip(mails, jobs):
        sections.setdefault(f"{m['variant']} / {m['lang']}", []).append((f"{m['kind']}: {m['subject']}", m["html"], png))
    note = (f"<p>{len(mails)} mails - also browsable in Mailpit at "
            f"<a href='{MAILPIT_UI}'>{MAILPIT_UI}</a>.</p>"
            + ("" if MODES else "<p>Screenshots are off - run with <code>E2E_SCREENSHOTS=desktop,mobile,dark</code> "
                                "to add them.</p>")
            + f"<pre>{html.escape((OUT / 'summary.txt').read_text())}</pre>")
    gallery("Zabbix mail E2E test", sections, note)
    log(f"done - {len(mails)} mails; open test/e2e/output/index.html or {MAILPIT_UI}")
    return ok


def cmd_docs():
    """The scenario for both layouts in English with all screenshot modes, then the README images."""
    global VARIANTS, LANGS, MODES
    if not DOCS_IMG.is_dir():
        sys.exit(f"{DOCS_IMG} is not mounted - use test/e2e/e2e.sh docs")
    VARIANTS, LANGS, MODES = ["standard", "compact"], ["en"], ["desktop", "mobile", "dark"]
    ok = cmd_scenario()
    if ok:
        docs_images(DOCS_IMG)
    return ok


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    command = sys.argv[1] if len(sys.argv) > 1 else "scenario"
    ok = {"scenario": cmd_scenario, "previews": cmd_previews, "docs": cmd_docs}[command]()
    sys.exit(0 if ok is not False else 1)
