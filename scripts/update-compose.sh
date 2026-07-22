#!/usr/bin/env bash
set -euo pipefail

compose_file="${1:-compose/truenas.yml}"
docker compose -f "$compose_file" pull
docker compose -f "$compose_file" up -d --remove-orphans
docker compose -f "$compose_file" ps
