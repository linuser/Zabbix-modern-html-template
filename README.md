Es müssen im Zabbix System unter Administration  -> Macros --> folgende Macros gesetzt werden und die Values auf das eigene System angepasst werden .
Getestet ist das ganze mit Zabbbix 7.0


Macro                   Value
{$ZABBIXHOST}           hostname 
{$ZABBIXHOST_LINK}      https://hostname.example
{$ZABBIXHOST_LOGO}      {$ZABBIXHOST_LINK}/zabbix_logo_.png
{$ZABBIXHOST_LOVE}      Create with Open Source and <i>&#10084;</i>  
{$CUSTOM_MESSAGE_COMPANY}  Company Example
Das Zabbix Logo für diesesn Template muss ins Zabbix Verzeichnis geladen werden unter

/usr/share/zabbix/

-

Danach kann das Mediatype Template "Email (HTML) Modern" hochgeladen werden und die Mailaccount Acoountdaten hinterlegt werden .Danach  Testen ob die
Benutzerdaten stimmen und Speichern .Nun könnte ihr diesen Mediatype Benutzern zu wiesen und testen . 
