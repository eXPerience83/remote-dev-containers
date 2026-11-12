#!/bin/sh
# One preinstalled stdio MCP per agent; no runtime downloads or ports.
# Image-owned interpreter, caller options rejected by the supervisor.
role="${REMOTE_DEV_ROLE:-}"
exec /usr/bin/env -i REMOTE_DEV_ROLE="$role" \
  /usr/local/lib/remote-dev/python -I \
  /usr/local/lib/remote-dev/browser-sandbox.py "$@"
