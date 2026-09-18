# Running the Vyuha console

## Local

```bash
./scripts/serve.sh          # http://127.0.0.1:8601
```

## Over Tailscale

```bash
./scripts/tailscale-serve.sh tailnet   # your devices only, https://<node>.<tailnet>.ts.net:9443
./scripts/tailscale-serve.sh public    # public internet, https://<node>.<tailnet>.ts.net/vyuha
./scripts/tailscale-serve.sh off
```

### The Funnel footgun

Tailscale Funnel only works on ports **443, 8443 and 10000**. If all three are
already taken, the way to add another service is a *path* handler on one of
them.

But there is a trap. Running:

```bash
tailscale serve --bg --set-path=/vyuha http://127.0.0.1:8601
```

on a port that already has Funnel enabled prints
`Removing Funnel for <host>:443` and **takes every other site on that port off
the public internet**. It is a one-line command that silently de-publishes your
other services.

Use the `funnel` verb instead, which adds the path and keeps Funnel on:

```bash
tailscale funnel --bg --set-path=/vyuha http://127.0.0.1:8601
```

Check what you have before and after, every time:

```bash
tailscale serve status
```

### There is no authentication

A public Funnel mount is open to anyone who knows the URL. For Vyuha that means
they can trigger LLM inference on your machine and cause outbound scraping from
your IP. Prefer `tailnet` unless you specifically want it public, and consider
putting a token check in front of `/api/ask` if you do.

## Surviving a reboot

`scripts/serve.sh` run by hand does not come back after a restart. On macOS,
a LaunchAgent does:

```xml
<!-- ~/Library/LaunchAgents/com.vyuha.web.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.vyuha.web</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/YOU/Developer/vyuha/scripts/serve.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/vyuha-web.log</string>
  <key>StandardErrorPath</key><string>/tmp/vyuha-web.err</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.vyuha.web.plist
```

Tailscale's serve/funnel configuration persists across reboots on its own.
