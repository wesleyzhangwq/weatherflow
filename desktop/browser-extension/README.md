# WeatherFlow Activity WebExtension

Load this directory as an unpacked Manifest V3 extension. The extension is disabled by default.
After WeatherFlow browser collection is explicitly enabled, open the extension, enter the local
bridge address/token, and enable recording. Incognito collection requires authorization in the
browser, the extension popup, and WeatherFlow.

The extension reads only focused tab/window metadata through `tabs`, `windows`, `alarms`, and
`idle`. It does not request page-content injection, cookies, history, clipboard, downloads,
screenshots, microphone, or keyboard permissions.
