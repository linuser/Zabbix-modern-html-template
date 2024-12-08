Es müssen im Zabbix System unter Administration -> Macros --> folgende Macros gesetzt werden und die Values auf das eigene System angepasst werden . Getestet ist das ganze mit Zabbbix 7.0

## 1. Setzen der Macros
1. **Navigieren Sie zu:**  
   `Administration -> Macros`.

2. **Erstellen Sie die Macros:**  
   Klicken Sie auf **"Macro hinzufügen"** und geben Sie folgende Werte ein:

   | Macro                   | Value                                     |
   |-------------------------|-------------------------------------------|
   | `{$ZABBIXHOST}`         | `hostname`                               |
   | `{$ZABBIXHOST_LINK}`    | `https://hostname.example`               |
   | `{$ZABBIXHOST_LOGO}`    | `{$ZABBIXHOST_LINK}/zabbix_logo_.png`    |
   | `{$ZABBIXHOST_LOVE}`    | `Create with Open Source and <i>&#10084;</i>` |
   | `{$CUSTOM_MESSAGE_COMPANY}` | `Company Example`                    |
   

## 2. Hochladen des Zabbix Logos
1. **Speichern Sie die Logodatei:**  
   Stellen Sie sicher, dass die Datei `zabbix_logo_.png` verfügbar ist.

2. **Kopieren Sie die Datei in das Zabbix-Verzeichnis:**  
   ```bash
   sudo cp zabbix_logo_.png /usr/share/zabbix/

Danach kann das Mediatype Template "Email (HTML) Modern" hochgeladen werden und die Mailaccount Acoountdaten hinterlegt werden .Testen ob die Benutzerdaten stimmen und Speichern .Nun könnt ihr diesen Mediatype Benutzern zu weisen und testen .
