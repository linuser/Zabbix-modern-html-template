# Zabbix HTML E-Mail Templates V1.1

Modern, responsive HTML email templates for **Zabbix 7.4** with Dark Mode support, Outlook compatibility and mobile-friendly design. Available in 5 languages.

![Version](https://img.shields.io/badge/version-1.1-blue)
![Zabbix](https://img.shields.io/badge/zabbix-7.4-red)
![License](https://img.shields.io/badge/license-CC%20BY--SA%204.0-green)
![Languages](https://img.shields.io/badge/languages-5-orange)

---

## Features

| Feature | V1.0 (Original) | V1.1 |
|---------|:---:|:---:|
| Outlook compatible (table layout) | ❌ | ✅ |
| Inline CSS | ❌ | ✅ |
| Dark Mode | ❌ | ✅ |
| System Fonts | ❌ | ✅ |
| MSO Conditionals | ❌ | ✅ |
| Host IP `{HOST.IP}` | ❌ | ✅ |
| Acknowledge Button | ❌ | ✅ |
| Event Tags | ❌ | ✅ |
| Operational Data | ❌ | ✅ |
| Duration in Recovery | ❌ | ✅ |
| Update User/Message | ❌ | ✅ |
| Mobile responsive (620px) | ❌ | ✅ |
| Languages | DE | DE / EN / FR / ES / PT |

## Languages

| File | Language |
|------|----------|
| `zbx_html-modern-message_V1.1_DE.yaml` | Deutsch |
| `zbx_html-modern-message_V1.1_EN.yaml` | English |
| `zbx_html-modern-message_V1.1_FR.yaml` | Français |
| `zbx_html-modern-message_V1.1_ES.yaml` | Español |
| `zbx_html-modern-message_V1.1_PT.yaml` | Português |

Each file contains **10 message templates**: Trigger (Problem/Recovery/Update), Discovery, Autoregistration, Internal (Problem/Recovery), Service (Problem/Recovery/Update).

## Color Scheme

| Event Type | Color | Hex |
|------------|-------|-----|
| Problem | 🔴 Red | `#dc3545` |
| Recovery | 🟢 Green | `#28a745` |
| Update | 🔵 Cyan | `#17a2b8` |
| Discovery | 🔵 Blue | `#0275d8` |
| Internal | 🟡 Yellow | `#e6a800` |
| Service | 🟠 Orange | `#f0ad4e` |

---

## Installation

### 1. Download Logo

Download the official Zabbix logo (or use your own):

**→ [Zabbix Logo Download](https://www.zabbix.com/de/trademark#colors)**

### 2. Place Logo on Server

```bash
sudo cp zabbix_logo.png /usr/share/zabbix/ui/assets/img/
sudo chmod 644 /usr/share/zabbix/ui/assets/img/zabbix_logo.png
```

Verify: open `https://your-zabbix-host/assets/img/zabbix_logo.png` in a browser.

> **Note:** If your Zabbix root is `/usr/share/zabbix/` (not `/usr/share/zabbix/ui/`), adjust the path accordingly.

### 3. Import Template

**New installation:**
1. Go to **Alerts → Media types → Import** (top right)
2. Select the YAML file for your language
3. Enable **"Create new"**
4. Click **Import**
5. Configure SMTP settings (see step 4)

**Update from V1.0:**
1. Go to **Alerts → Media types → Import** (top right)
2. Select the V1.1 YAML file
3. Enable **"Update existing"**
4. Click **Import**
5. **Re-enter your SMTP settings** (server, port, auth) — the import resets them to placeholders

### 4. Configure SMTP

Open the imported media type and enter your SMTP settings:

| Field | Example |
|-------|---------|
| SMTP server | `mail.example.de` |
| SMTP server port | `587` |
| SMTP helo | `zabbix.example.de` |
| SMTP email | `zabbix@example.de` |
| Connection security | STARTTLS |
| Authentication | Username and password |

### 5. Set Global Macros

Go to **Administration → Macros** and create:

| Macro | Value | Purpose |
|-------|-------|---------|
| `{$ZABBIXHOST}` | `zabbix.example.de` | Hostname in footer |
| `{$ZABBIXHOST_LINK}` | `https://zabbix.example.de` | Base URL for links |
| `{$ZABBIXHOST_LOGO}` | `https://zabbix.example.de/assets/img/zabbix_logo.png` | Logo URL |
| `{$CUSTOM_MESSAGE_COMPANY}` | `ACME Corp — IT Dept` | Company name in footer |
| `{$ZABBIXHOST_LOVE}` | `Created with Open Source and ❤️` | Optional footer text |

### 6. Assign to Users

1. Go to **Users → Users** → select user
2. **Media** tab → **Add**
3. Type: `Email (HTML) modern V1.1 (DE/EN/FR/ES/PT)`
4. Send to: user's email address
5. **Add** → **Update**

### 7. Test

Click **Test** in the media type row under **Alerts → Media types**.

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Import error `unexpected tag content_type` | You have an old version. Use V1.1 which uses `message_format`. |
| Logo not showing | The logo must be placed inside your **Nginx/Apache document root** (check `root` directive in your webserver config). For Zabbix 7.4 with Nginx this is typically `/usr/share/zabbix/ui/`, so place the logo in `/usr/share/zabbix/ui/assets/img/`. Paths outside the document root (e.g. `/usr/share/zabbix/local/`) return 404. Also check: URL accessible in browser? `{$ZABBIXHOST_LOGO}` macro correct? File permissions `644`? Email clients may block external images by default. |
| Macros show as `{HOST.NAME}` | Global macros (`{$...}`): check Administration → Macros. Zabbix macros: only replaced in real events, not in media type test. |
| Text unreadable in Dark Mode | Update to V1.1 (CSS fix for `td`/`th`/`span` selectors). |
| Emails in spam | Not a template issue. Configure SPF, DKIM and DMARC for your domain. |

## Uninstall

**Alerts → Media types** → check the box → **Delete**.

The YAML can be re-imported at any time. Make sure no active actions reference the media type before deletion.

---

## Credits

- **Original:** Alexander Fox (V0.2) — fox@linuser.de
- **V1.1 Rewrite:** Feb 2026 — Complete rewrite with modern email standards

## License

[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)
