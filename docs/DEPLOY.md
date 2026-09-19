# Running the Vyuha console

## "Can we switch to ASP.NET so the URL is fixed?"

Worth untangling, because it mixes up three separate things.

**ASP.NET is a web framework, not a host.** It is Microsoft's C#/.NET
equivalent of FastAPI — an alternative to the *code*, not to the *tunnel*.
Rewriting Vyuha in ASP.NET would mean discarding the entire Python codebase
(risk engine, council, ingest, 160 tests) and you would still have no URL,
because a framework does not host anything. The association is probably with
Azure App Service, which hosts ASP.NET well — and also hosts Python.

**Your IP is not currently exposed.** Tailscale Funnel proxies through
Tailscale's own edge infrastructure; visitors see that, not your home IP. The
real drawbacks of Funnel are different and genuine: your Mac must be awake,
and the hostname carries your tailnet name.

**The actual obstacle is Ollama, not the web server.** The council needs a
language model. Free hosting tiers give you 512MB of RAM; `llama3.1:8b` needs
several gigabytes. So moving to the cloud means either dropping the council or
pointing it at a hosted endpoint.

### What to do instead

Keep the Python, containerise it, and send inference to a hosted endpoint that
serves **open-weight** models — so the "open models only" property survives:

| Host | Free tier | Notes |
|---|---|---|
| **Fly.io** | ~3 small VMs | `fly.toml` included, region `bom` (Mumbai) |
| **Render** | 512MB, sleeps after 15 min idle | `render.yaml` included; first request after a sleep takes 30–60s |
| **Hugging Face Spaces** | free CPU | Docker SDK; good if you want it discoverable |
| **Azure App Service** | free F1 tier | if you specifically want Microsoft's stack |

For inference, any OpenAI-compatible endpoint works. `VYUHA_LLM_BASE_URL`
accepts a preset name or a full URL:

```
groq | openrouter | cerebras | together | deepinfra
```

These serve Llama, Qwen, Gemma and Mixtral on free tiers, so the council stays
open-weight — it just no longer runs on your desk.

```bash
fly launch --no-deploy
fly secrets set VYUHA_LLM_API_KEY=...       # you create this, never commit it
fly secrets set VYUHA_DATA_GOV_IN_KEY=...
fly deploy
```

**It degrades honestly.** With no model configured, live figures and stress
tests still work and the council says plainly that no advisors are available,
rather than serving a fake 0.5 probability.

**Note:** the Dockerfile has not been built and run on this machine — Docker
was not installed — so treat the first `fly deploy` as the real test. The
environment-variable path it depends on *is* verified.



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
