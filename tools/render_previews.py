#!/usr/bin/env python3
"""Render the README preview screenshots for all V1.1 message templates.

Every template of every language file (zbx_html-modern-message_V1.1_<LANG>.yaml)
gets its macros replaced with sample data and is rendered with headless Chrome
in light and dark mode:

    screenshots/<lang>/<template>.png
    screenshots/<lang>/<template>-dark.png

Usage:
    python3 tools/render_previews.py
    CHROME=/path/to/chrome python3 tools/render_previews.py

Requires PyYAML and Google Chrome or Chromium.
"""
import base64
import glob
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "screenshots")
WIDTH, MIN_HEIGHT, SCALE = 680, 900, 1

NAMES = {
    ("TRIGGERS", "PROBLEM"): "problem",
    ("TRIGGERS", "RECOVERY"): "recovery",
    ("TRIGGERS", "UPDATE"): "update",
    ("DISCOVERY", "PROBLEM"): "discovery",
    ("AUTOREGISTRATION", "PROBLEM"): "autoregistration",
    ("INTERNAL", "PROBLEM"): "internal-problem",
    ("INTERNAL", "RECOVERY"): "internal-recovery",
    ("SERVICE", "PROBLEM"): "service-problem",
    ("SERVICE", "RECOVERY"): "service-recovery",
    ("SERVICE", "UPDATE"): "service-update",
}

# Placeholder for {$ZABBIXHOST_LOGO}, so the previews do not depend on a web server.
LOGO = "data:image/svg+xml;base64," + base64.b64encode(
    b'<svg xmlns="http://www.w3.org/2000/svg" width="140" height="36" viewBox="0 0 140 36">'
    b'<text x="70" y="28" text-anchor="middle" font-family="Arial, Helvetica, sans-serif" '
    b'font-size="28" font-weight="700" letter-spacing="3" fill="#ffffff">ZABBIX</text></svg>'
).decode()

COMMON = {
    "$ZABBIXHOST": "zabbix.planetfox.biz",
    "$ZABBIXHOST_LINK": "https://zabbix.planetfox.biz",
    "$ZABBIXHOST_LOGO": LOGO,
    "$CUSTOM_MESSAGE_COMPANY": "PlanetFox IT",
    "$ZABBIXHOST_LOVE": "Created with Open Source and ❤️",
    "HOST.NAME": "web01.planetfox.biz",
    "HOST.HOST": "web01",
    "HOST.IP": "10.0.2.14",
    "HOST.GROUPS": "Linux servers, Production",
    "TRIGGER.HOSTGROUP.NAME": "Linux servers",
    "TRIGGER.ID": "55011",
    "EVENT.ID": "104822",
    "EVENT.DATE": "2026.09.10",
    "EVENT.TIME": "14:32:07",
    "EVENT.RECOVERY.DATE": "2026.09.10",
    "EVENT.RECOVERY.TIME": "14:44:11",
    "EVENT.DURATION": "12m 4s",
    "EVENT.UPDATE.DATE": "2026.09.10",
    "EVENT.UPDATE.TIME": "14:40:00",
    "EVENT.OPDATA": "Load: 9.8, Cores: 4",
    "EVENT.TAGS": "env: prod, service: web",
    "USER.FULLNAME": "Alexander Fox",
    "DISCOVERY.DEVICE.IPADDRESS": "10.0.5.77",
    "DISCOVERY.DEVICE.DNS": "printer03.planetfox.biz",
    "DISCOVERY.DEVICE.STATUS": "Up",
    "DISCOVERY.RULE.NAME": "Local network 10.0.5.0/24",
    "SERVICE.NAME": "Web Frontend",
    "SERVICE.STATUS": "—",
    "SERVICE.UPTIME": "29d 4h",
    "SERVICE.AVAILABILITY": "99.82%",
}

# Sample values that would appear translated in a real notification.
LOCAL = {
    "de": {"problem": "CPU-Auslastung zu hoch (> 90%)", "severity": "Hoch", "ack": "Bestätigt",
           "message": "Wird untersucht, Neustart geplant."},
    "en": {"problem": "CPU usage too high (> 90%)", "severity": "High", "ack": "Acknowledged",
           "message": "Investigating, restart scheduled."},
    "fr": {"problem": "Utilisation CPU trop élevée (> 90 %)", "severity": "Haute", "ack": "Acquitté",
           "message": "En cours d'analyse, redémarrage prévu."},
    "es": {"problem": "Uso de CPU demasiado alto (> 90%)", "severity": "Alta", "ack": "Reconocido",
           "message": "En análisis, reinicio programado."},
    "pt": {"problem": "Uso de CPU muito alto (> 90%)", "severity": "Alta", "ack": "Reconhecido",
           "message": "Em análise, reinício agendado."},
}

MACRO = re.compile(r"\{(\$?[A-Z][A-Z0-9_.]*)\}")


def find_chrome():
    candidates = [os.environ.get("CHROME"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                  shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    sys.exit("Chrome/Chromium not found - set CHROME=/path/to/chrome")


def sample_values(lang):
    local = LOCAL[lang]
    return dict(COMMON, **{
        "EVENT.NAME": local["problem"],
        "EVENT.SEVERITY": local["severity"],
        "TRIGGER.SEVERITY": local["severity"],
        "EVENT.UPDATE.SEVERITY": local["severity"],
        "EVENT.ACK.STATUS": local["ack"],
        "EVENT.UPDATE.MESSAGE": local["message"],
    })


def fill(message, values):
    # {{TRIGGER.SEVERITY}} becomes {High} - exactly what Zabbix sends for that typo.
    return MACRO.sub(lambda m: values.get(m.group(1), m.group(0)), message)


def page_heights(chrome, tmp, pages):
    """Content height of every page, measured in one Chrome run via srcdoc iframes."""
    frames = "".join(f'<iframe style="width:{WIDTH}px;height:100px;border:0" srcdoc="{html.escape(p, quote=True)}"></iframe>'
                     for p in pages)
    probe = os.path.join(tmp, "probe.html")
    with open(probe, "w", encoding="utf-8") as f:
        f.write(f'{frames}<pre id="o"></pre><script>onload = () => document.getElementById("o").textContent = '
                'JSON.stringify([...document.querySelectorAll("iframe")].map(i => i.contentDocument.documentElement.scrollHeight));'
                '</script>')
    dom = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--virtual-time-budget=15000", "--dump-dom",
                          "file://" + probe], capture_output=True, text=True, check=True).stdout
    return json.loads(html.unescape(re.search(r'<pre id="o">(.*?)</pre>', dom, re.S).group(1)))


def screenshot(chrome, src, dst, height, dark):
    args = [chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}", f"--window-size={WIDTH},{height}", f"--screenshot={dst}"]
    if dark:
        args += ["--force-dark-mode", "--blink-settings=preferredColorScheme=0"]
    subprocess.run(args + ["file://" + src], capture_output=True, check=True)


def main():
    chrome = find_chrome()
    jobs = []
    for path in sorted(glob.glob(os.path.join(ROOT, "zbx_html-modern-message_V1.1_*.yaml"))):
        lang = path[-7:-5].lower()
        with open(path, encoding="utf-8") as f:
            media_type = yaml.safe_load(f)["zabbix_export"]["media_types"][0]
        values = sample_values(lang)
        for t in media_type["message_templates"]:
            jobs.append((lang, NAMES[(t["event_source"], t["operation_mode"])], fill(t["message"], values)))

    with tempfile.TemporaryDirectory() as tmp:
        heights = page_heights(chrome, tmp, [page for _, _, page in jobs])
        for (lang, name, page), height in zip(jobs, heights):
            os.makedirs(os.path.join(OUT, lang), exist_ok=True)
            src = os.path.join(tmp, f"{lang}-{name}.html")
            with open(src, "w", encoding="utf-8") as f:
                f.write(page)
            for dark in (False, True):
                dst = os.path.join(OUT, lang, f"{name}{'-dark' if dark else ''}.png")
                screenshot(chrome, src, dst, max(MIN_HEIGHT, height), dark)
            print(f"{lang}/{name}: {max(MIN_HEIGHT, height)}px")


if __name__ == "__main__":
    main()
