#!/usr/bin/env bash
# Publish the Vyuha console over Tailscale.
#
# IMPORTANT, learned the hard way: `tailscale serve --set-path=...` on a port
# that already has Funnel enabled will SILENTLY DISABLE Funnel for that whole
# port, taking any other site you serve there off the public internet. Use
# `tailscale funnel --set-path=...` instead, which preserves it.
#
#   ./scripts/tailscale-serve.sh public     -> public internet (Funnel)
#   ./scripts/tailscale-serve.sh tailnet    -> your devices only
#   ./scripts/tailscale-serve.sh off        -> remove the /vyuha handler
set -euo pipefail

PORT="${PORT:-8601}"
MOUNT="${MOUNT:-/vyuha}"
MODE="${1:-tailnet}"

case "$MODE" in
  public)
    tailscale funnel --bg --set-path="$MOUNT" "http://127.0.0.1:${PORT}"
    echo "Public. Anyone with the URL can reach it -- there is no auth."
    ;;
  tailnet)
    # A distinct HTTPS port keeps this off any port that already has Funnel on,
    # so enabling it here cannot accidentally expose it.
    tailscale serve --bg --https=9443 "http://127.0.0.1:${PORT}"
    echo "Tailnet only: https://$(tailscale status --json | python3 -c 'import json,sys;print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'):9443"
    ;;
  off)
    tailscale serve --set-path="$MOUNT" off 2>/dev/null || true
    tailscale serve --https=9443 off 2>/dev/null || true
    echo "Removed."
    ;;
  *) echo "usage: $0 [public|tailnet|off]" >&2; exit 1 ;;
esac

tailscale serve status
