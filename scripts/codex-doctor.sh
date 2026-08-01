#!/usr/bin/env bash
set -euo pipefail

export REMOTE_DEV_ROLE=codex
exec /usr/local/bin/remote-dev-doctor "$@"
