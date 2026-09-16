# Changelog

## V1.2 - 2026-09

### Added

- **Severity colours**: trigger problems use the six Zabbix severity colours (Disaster … Not classified), computed by Zabbix at send time with `{{EVENT.NSEVERITY}.regrepl(…)}`; other messages show the severity as a coloured badge. Static fallback colour when the macro is not resolved (media type Test button).
- **Compact flavour**: about a third less height - slim header, the same two boxes (host, details) with tight rows, slim footer.
- **No-logo variants** of both flavours: no image is loaded from a web server.
- **Rounded buttons in classic Outlook** for Windows via VML (`v:roundrect`).
- **Modular sources**: Jinja2 templates per flavour, one CSS file per flavour, texts in `src/i18n/<lang>.yaml`, colours in `src/themes.yaml`, messages in `src/messages.yaml`; `build.py` generates all media types and checks them.
- **Releases**: GitHub Actions builds every push and publishes zips (per variant, per language, all, previews) for version tags.
- **Previews** with sample data (`build.py --preview`).
- **End-to-end test**: Docker stack with a real Zabbix and Mailpit that imports all variants, fires problems / updates / recoveries, checks every mail for unresolved macros and screenshots it (`test/e2e/e2e.sh run`), also in CI against Zabbix 7.0, 7.4 and trunk. V1.2 passes it on Zabbix 7.0.30, 7.4.14 and 8.0.0rc1.

### Changed

- **Zabbix 7.0 and newer**: the export format is 7.0 (was 7.4), so the files import into 7.0, 7.2 and 7.4.
- Media type names contain the variant: *Email (HTML) modern V1.2 standard (EN)*, *… compact (EN)*, …
- The generated YAML files are no longer committed; download them from the releases.
- Dark text on light accent colours (internal, severity colours) for readable contrast; solid colours instead of `rgba()` (not supported by classic Outlook).
- Dark mode: the lines between detail rows are dark instead of light grey.
- Outlook: VML/Office namespaces on `<html>`, Segoe UI font fallback, `width` attribute on the logo.
- Internal problem mails show the host name in the header instead of the trigger severity (internal events of items have none).

### Fixed

Found by the end-to-end test against a real Zabbix 7.0:

- Service mails used macros Zabbix does not have (`{SERVICE.STATUS}`, `{SERVICE.UPTIME}`, `{SERVICE.AVAILABILITY}`) and showed them literally. They now show the severity (`{EVENT.SEVERITY}` / `{EVENT.UPDATE.SEVERITY}`) and the root cause (`{SERVICE.ROOTCAUSE}`).
- Internal mails showed `{TRIGGER.HOSTGROUP.NAME}`, `{TRIGGER.SEVERITY}` and `{TRIGGER.ID}` literally for internal events of items and LLD rules (which have no trigger), and their button linked to a non-existent trigger. They now use macros every internal event resolves and link to the host's items.
- Internal problem / recovery headers showed `{{TRIGGER.SEVERITY}}` / `{{HOST.NAME}}` with double braces.
- German: inconsistent "Details Ansehen" / "Details ansehen" and "Details zur (Problem)behebung".
