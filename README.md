Es müssen im Zabbix System unter Administration  -> Macros --> folgende Macros gesetzt werden und die Values auf das eigene System angepasst werden .
Getestet ist das ganze mit Zabbbix 7.0

https://github.com/linuser/Zabbix-modern-html-template/blob/main/problem-behoben.png
Macro                   Value
{$ZABBIXHOST}           hostname 
{$ZABBIXHOST_LINK}      https://hostname.example
{$ZABBIXHOST_LOGO}      {$ZABBIXHOST_LINK}/zabbix_logo_.png
{$ZABBIXHOST_LOVE}      Create with Open Source and <i>&#10084;</i>  
{$CUSTOM_MESSAGE_COMPANY}  Company Example
Das Zabbix Logo für diesesn Template muss ins Zabbix Verzeichnis geladen werden unter

/usr/share/zabbix/

-

Danach kann das Mediatype Template "Email (HTML) Modern" hochgeladen werden und die Mailaccount Acoountdaten hinterlegt werden .Testen ob die
Benutzerdaten stimmen und Speichern .Nun könnt ihr diesen Mediatype Benutzern zu weisen und testen . 
