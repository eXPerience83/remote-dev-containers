#!/usr/bin/env bash
set -euo pipefail
# This server uses stdio per agent. No shared HTTP listener or runtime installs.
export PLAYWRIGHT_BROWSERS_PATH=/opt/remote-dev/playwright-browsers
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1
exec /opt/remote-dev/playwright/node_modules/.bin/playwright-mcp \
  --config /usr/share/remote-dev/playwright-mcp.json "$@"
