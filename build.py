#!/usr/bin/env python3
"""
Build the Zabbix HTML e-mail media types from src/.

    pip install -r requirements.txt
    python build.py                    # dist/yaml/*.yaml and dist/*.zip
    python build.py --preview          # additionally dist/previews/ (HTML with sample data)
    python build.py --release v1.2.0   # name the zip files after a release tag

Sources:
    build.yaml                 languages x variants (flavour + logo on/off), naming
    src/messages.yaml          the ten messages: rows, theme, button
    src/themes.yaml            colours, incl. the Zabbix severity palette
    src/i18n/<lang>.yaml       texts
    src/templates/             shared Jinja templates: page skeleton, components, YAML export
    src/flavors/<flavor>/      message.html.j2 (structure) + style.css (look)
    src/css/base.css           CSS shared by all flavours

Pipeline per message: render Jinja -> inline CSS -> expand severity colours ->
wrap in the YAML export -> parse the YAML again and compare.
"""
import argparse
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

import css_inline
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
MAX_MESSAGE_BYTES = 65535  # Zabbix stores message templates in a TEXT column
ZIP_DATE = (1980, 1, 1, 0, 0, 0)  # fixed timestamp -> reproducible zip files

TOKEN = re.compile(r"var\(--(accent|on-accent|ink|tint)\)")
SEV_VAR = re.compile(r"var\(--sev-([a-z-]+),\s*(#[0-9A-Fa-f]{3,8})\)")
STYLE_ATTR = re.compile(r'style="([^"]*)"')
LEFTOVER = re.compile(r"var\(--|\{%|%\}|\{#")
INLINER = css_inline.CSSInliner(keep_at_rules=True)


class BuildError(Exception):
    pass


def load_yaml(path):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# --- colours ------------------------------------------------------------------

def luminance(colour):
    h = colour.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)

    def channel(c):
        c = int(c, 16) / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (channel(h[i:i + 2]) for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def severity_expr(palette, token):
    """Zabbix picks the colour at send time:
    {{EVENT.NSEVERITY}.regrepl(^5$,#E45959,^4$,#E97659,...)}

    regrepl() applies the pattern/replacement pairs one after another, so every
    pattern is anchored - otherwise the "4" in "#E45959" would be rewritten by the
    next pair.
    """
    levels = palette["severity"]["levels"]
    pairs = ",".join(f"^{n}$,{levels[n][token]}" for n in sorted(levels, reverse=True))
    return "{{%s}.regrepl(%s)}" % (palette["severity"]["macro"], pairs)


class Theme:
    """Colour tokens of one message (src/themes.yaml)."""

    def __init__(self, spec, palette):
        self.palette = palette
        self.severity = spec.get("severity", False)
        if self.severity:
            self.colours = dict(spec["fallback"], **{"on-accent": palette["severity"]["on-accent"]})
        else:
            self.colours = spec
        self.dark_text = luminance(self.colours["on-accent"]) < 0.5

    def _dynamic(self, token):
        return self.severity and token != "on-accent"

    def css(self, token):
        """Value that replaces var(--token) in the flavour CSS."""
        if self._dynamic(token):
            return f"var(--sev-{token}, {self.colours[token]})"
        return self.colours[token]

    def attr(self, token):
        """Colour for HTML attributes (bgcolor) and Outlook VML (fillcolor).

        Attributes cannot carry a fallback, so severity themes get the regrepl
        expression itself: in real notifications Zabbix resolves it and the attribute
        matches the CSS (classic Outlook may prefer bgcolor over CSS). If it stays
        unresolved (Test button), browsers still use the CSS fallback.
        """
        return severity_expr(self.palette, token) if self._dynamic(token) else self.colours[token]


def expand_severity(html, palette):
    """style="background-color: var(--sev-accent, #E45959)" becomes
    style="background-color: #E45959;background-color: {{EVENT.NSEVERITY}.regrepl(...)}"

    If Zabbix leaves the macro unresolved (media type "Test", event without
    severity) the second declaration is invalid and dropped, the fallback remains.
    """
    def declaration(d):
        if "var(--sev-" not in d:
            return d
        fallback = SEV_VAR.sub(lambda m: m.group(2), d)
        dynamic = SEV_VAR.sub(lambda m: severity_expr(palette, m.group(1)), d)
        return f"{fallback};{dynamic}"

    return STYLE_ATTR.sub(lambda m: 'style="%s"' % ";".join(map(declaration, m.group(1).split(";"))), html)


# --- checks -------------------------------------------------------------------

def check_i18n(i18n):
    reference = set(i18n["en"])
    problems = []
    for lang, strings in i18n.items():
        missing, extra = reference - set(strings), set(strings) - reference
        if missing:
            problems.append(f"{lang}.yaml is missing: {', '.join(sorted(missing))}")
        if extra:
            problems.append(f"{lang}.yaml has keys not in en.yaml: {', '.join(sorted(extra))}")
    if problems:
        raise BuildError("\n".join(problems))


def unused_texts(i18n, messages):
    """Keys of en.yaml that no message and no template refers to."""
    used = set()

    def value(v):
        if isinstance(v, dict) and "text" in v:
            used.add(v["text"])

    for m in messages:
        rows = m["box"]["rows"] + m["details"]["rows"]
        used.update([m["preheader"], m["title"], m["box"]["title"], m["details"]["title"], m["button"]["label"]])
        used.update(label for label, _ in rows)
        for _, v in rows:
            value(v)
        value(m["subtitle"])
    for template in SRC.rglob("*.j2"):
        used.update(re.findall(r"\bt\.([a-z_]+)", template.read_text(encoding="utf-8")))
    return sorted(set(i18n["en"]) - used)


def check_palette(palette):
    """WCAG contrast: 4.5 for normal text, 3.0 for the large bold header text."""
    warnings = []

    def need(what, a, b, minimum):
        if contrast(a, b) < minimum:
            warnings.append(f"{what}: {a} on {b} has contrast {contrast(a, b):.2f} (< {minimum})")

    sev = palette["severity"]
    for n, level in sev["levels"].items():
        need(f"severity {n} on-accent", sev["on-accent"], level["accent"], 4.5)
        need(f"severity {n} ink", level["ink"], "#ffffff", 4.5)
        need(f"severity {n} ink on tint", level["ink"], level["tint"], 4.5)
    for name, spec in palette["themes"].items():
        colours = spec["fallback"] if spec.get("severity") else spec
        on_accent = sev["on-accent"] if spec.get("severity") else spec["on-accent"]
        need(f"theme {name} on-accent", on_accent, colours["accent"], 3.0)
        need(f"theme {name} ink", colours["ink"], "#ffffff", 4.5)
    return warnings


def verify_yaml(text, messages, where):
    """Parse the written export again and make sure it carries exactly what we rendered."""
    doc = yaml.safe_load(text)
    templates = doc["zabbix_export"]["media_types"][0]["message_templates"]
    if len(templates) != len(messages):
        raise BuildError(f"{where}: {len(templates)} message templates in YAML, expected {len(messages)}")
    for got, want in zip(templates, messages):
        for key in ("event_source", "operation_mode", "subject"):
            if got[key] != want[key]:
                raise BuildError(f"{where}: {key} differs after YAML round trip")
        if got["message"] != want["html"] + "\n":
            raise BuildError(f"{where}: {want['event_source']}/{want['operation_mode']} message differs after YAML round trip")


# --- rendering ----------------------------------------------------------------

class Builder:
    def __init__(self):
        self.cfg = load_yaml(ROOT / "build.yaml")
        self.messages = load_yaml(SRC / "messages.yaml")
        for m in self.messages:
            m.setdefault("tags", False)
        self.palette = load_yaml(SRC / "themes.yaml")
        self.themes = {name: Theme(spec, self.palette) for name, spec in self.palette["themes"].items()}
        self.i18n = {lang: load_yaml(SRC / "i18n" / f"{lang}.yaml") for lang in self.cfg["languages"]}
        check_i18n(self.i18n)
        base_css = (SRC / "css" / "base.css").read_text(encoding="utf-8")
        self.css = {v["flavor"]: base_css + "\n" + (SRC / "flavors" / v["flavor"] / "style.css").read_text(encoding="utf-8")
                    for v in self.cfg["variants"]}
        self.env = Environment(
            loader=FileSystemLoader(SRC),
            autoescape=select_autoescape(["html.j2"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["yaml_str"] = lambda s: json.dumps(s, ensure_ascii=False)  # JSON strings are valid YAML

    def names(self, variant, lang):
        fields = dict(version=self.cfg["version"], variant=variant["id"], lang=lang, LANG=lang.upper())
        return self.cfg["name"].format(**fields), self.cfg["file"].format(**fields)

    def render_message(self, variant, lang, msg):
        where = f"{variant['id']}/{lang}/{msg['event_source']}/{msg['operation_mode']}"
        theme = self.themes[msg["theme"]]
        css = TOKEN.sub(lambda m: theme.css(m.group(1)), self.css[variant["flavor"]])
        html = self.env.get_template(f"flavors/{variant['flavor']}/message.html.j2").render(
            version=self.cfg["version"], lang=lang, t=self.i18n[lang], msg=msg,
            variant=variant, logo=variant["logo"], theme=theme, css=css)
        html = INLINER.inline(html)
        html = expand_severity(html, self.palette)
        html = "\n".join(line.strip() for line in html.splitlines() if line.strip())
        leftover = LEFTOVER.search(html)
        if leftover:
            context = html[max(0, leftover.start() - 60):leftover.end() + 60]
            raise BuildError(f"{where}: unprocessed template/CSS syntax near: {context!r}")
        size = len(html.encode("utf-8"))
        if size > MAX_MESSAGE_BYTES:
            raise BuildError(f"{where}: message is {size} bytes, Zabbix allows {MAX_MESSAGE_BYTES}")
        return html

    def media_type(self, variant, lang):
        name, filename = self.names(variant, lang)
        messages = [dict(m, html=self.render_message(variant, lang, m)) for m in self.messages]
        text = self.env.get_template("templates/media_type.yaml.j2").render(
            zabbix_version=self.cfg["zabbix_version"], version=self.cfg["version"],
            name=name, variant=variant, messages=messages)
        verify_yaml(text, messages, filename)
        return filename, text

    # --- outputs --------------------------------------------------------------

    def build(self, out, release):
        yaml_dir = out / "yaml"
        shutil.rmtree(yaml_dir, ignore_errors=True)
        for old in out.glob("*.zip"):
            old.unlink()
        yaml_dir.mkdir(parents=True)

        files = {}
        for variant in self.cfg["variants"]:
            for lang in self.cfg["languages"]:
                filename, text = self.media_type(variant, lang)
                (yaml_dir / filename).write_text(text, encoding="utf-8")
                files[variant["id"], lang] = yaml_dir / filename
        print(f"{len(files)} media types in {yaml_dir.relative_to(ROOT) if yaml_dir.is_relative_to(ROOT) else yaml_dir}")

        prefix = f"zabbix-html-mail-{release}"
        groups = {"all": list(files.values())}
        groups.update({v["id"]: [p for (vid, _), p in files.items() if vid == v["id"]] for v in self.cfg["variants"]})
        groups.update({lang: [p for (_, l), p in files.items() if l == lang] for lang in self.cfg["languages"]})
        for group, paths in groups.items():
            write_zip(out / f"{prefix}-{group}.zip", paths, yaml_dir)
        print(f"{len(groups)} zip files: {prefix}-{{{','.join(groups)}}}.zip")
        return prefix

    def previews(self, out, prefix):
        """HTML files with sample data, as Zabbix would send them."""
        sample = load_yaml(SRC / "preview" / "sample.yaml")
        levels = self.palette["severity"]["levels"]
        macro = "{%s}" % self.palette["severity"]["macro"]
        pdir = out / "previews"
        shutil.rmtree(pdir, ignore_errors=True)
        pdir.mkdir(parents=True)
        shutil.copy(SRC / "preview" / "logo.svg", pdir / "logo.svg")
        cards = []

        def emit(filename, label, variant, lang, msg, severity):
            html = self.render_message(variant, lang, msg)
            if severity is not None:
                values = dict(sample["macros"], **{macro: str(severity), "{EVENT.SEVERITY}": levels[severity]["name"]})
                html = resolve(html, values)
            (pdir / filename).write_text(html, encoding="utf-8")
            cards.append((filename, label))

        problem = self.messages[0]
        default = sample["severity"]
        for v in self.cfg["variants"]:
            for n in sorted(levels, reverse=True):
                emit(f"{v['id']}_en_problem_sev{n}.html", f"{v['label']} - problem - {levels[n]['name']}", v, "en", problem, n)
            for m in self.messages[1:]:
                kind = f"{m['event_source'].lower()}_{m['operation_mode'].lower()}"
                emit(f"{v['id']}_en_{kind}.html", f"{v['label']} - {kind}", v, "en", m, default)
            emit(f"{v['id']}_en_problem_unresolved.html", f"{v['label']} - problem - unresolved macros (media type Test)",
                 v, "en", problem, None)
        for v in (v for v in self.cfg["variants"] if v["logo"]):
            for lang in self.cfg["languages"][1:]:
                emit(f"{v['id']}_{lang}_problem.html", f"{v['label']} - problem - {lang}", v, lang, problem, 3)

        items = "\n".join(
            f'<figure><figcaption>{label} &middot; <a href="{f}">open</a></figcaption>'
            f'<iframe src="{f}" loading="lazy" onload="this.style.height=this.contentDocument.body.scrollHeight+\'px\'"></iframe></figure>'
            for f, label in cards)
        (pdir / "index.html").write_text(
            "<!DOCTYPE html><html><head><meta charset='utf-8'><title>Zabbix mail previews</title><style>"
            "body{font-family:system-ui,sans-serif;margin:16px;background:#d9dce1}"
            "main{display:grid;grid-template-columns:repeat(auto-fill,minmax(640px,1fr));gap:20px}"
            "figure{margin:0}figcaption{font-size:12px;margin:0 0 4px}"
            "iframe{width:640px;height:700px;border:0;background:#fff}</style></head><body><main>\n"
            f"{items}\n</main></body></html>\n", encoding="utf-8")
        write_zip(out / f"{prefix}-previews.zip", sorted(pdir.iterdir()), pdir)
        print(f"{len(cards)} previews in {pdir}")


MACRO_FUNC = re.compile(r"\{\{([A-Z0-9_.]+)\}\.regrepl\(([^)]*)\)\}")
MACRO = re.compile(r"\{\$?[A-Z0-9_.]+\}")


def resolve(html, values):
    """Mimic Zabbix macro expansion, including regrepl(), for previews."""
    def func(m):
        value = values.get("{%s}" % m.group(1))
        if value is None:
            return m.group(0)
        args = m.group(2).split(",")
        for pattern, replacement in zip(args[::2], args[1::2]):
            value = re.sub(pattern, replacement, value)
        return value

    html = MACRO_FUNC.sub(func, html)
    return MACRO.sub(lambda m: str(values.get(m.group(0), m.group(0))), html)


def write_zip(path, files, base):
    with zipfile.ZipFile(path, "w") as z:
        for f in sorted(files):
            info = zipfile.ZipInfo(str(f.relative_to(base)), ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, f.read_bytes())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "dist", help="output directory (default: dist/)")
    ap.add_argument("--release", help="release tag used in zip names; must start with v<version> (default: v<version>)")
    ap.add_argument("--preview", action="store_true", help="also render HTML previews with sample data")
    args = ap.parse_args()

    try:
        builder = Builder()
        version = builder.cfg["version"]
        release = args.release or f"v{version}"
        if not release.startswith(f"v{version}"):
            raise BuildError(f"release tag {release!r} does not match version {version!r} in build.yaml")
        for warning in check_palette(builder.palette):
            print("warning:", warning, file=sys.stderr)
        unused = unused_texts(builder.i18n, builder.messages)
        if unused:
            print(f"warning: unused keys in src/i18n: {', '.join(unused)}", file=sys.stderr)
        args.out.mkdir(parents=True, exist_ok=True)
        prefix = builder.build(args.out.resolve(), release)
        if args.preview:
            builder.previews(args.out.resolve(), prefix)
    except BuildError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
