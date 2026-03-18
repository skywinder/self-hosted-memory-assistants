#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PORTS_FILE="$SCRIPT_DIR/.env.ports"
EXOCORTEX_HELPER="$SCRIPT_DIR/scripts/exocortex-control-panel.sh"

if [ -f "$PORTS_FILE" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$PORTS_FILE"
  set +a
fi

EXOCORTEX_CONTROL_PANEL_PORT="${EXOCORTEX_CONTROL_PANEL_PORT:-3333}"

# Create shared network if it doesn't exist
docker network create memory-net 2>/dev/null || true

# Also create module-specific external networks
docker network create ushadow-network 2>/dev/null || true
docker network create infra-network 2>/dev/null || true
docker network create chronicle-network 2>/dev/null || true

case "${1:-up}" in
  up|start)
    echo "Starting ushadow infra..."
    docker compose -f "$SCRIPT_DIR/ushadow/compose/docker-compose.infra.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-infra.override.yml" --profile infra up -d

    echo "Starting ushadow app..."
    docker compose -f "$SCRIPT_DIR/ushadow/docker-compose.yml" \
      -f "$SCRIPT_DIR/ushadow/compose/overrides/prod-webui.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-app.override.yml" up -d

    echo "Starting OpenMemory MCP (shared memory store)..."
    docker compose -f "$SCRIPT_DIR/chronicle/extras/openmemory-mcp/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle-openmemory.override.yml" up -d

    echo "Starting chronicle..."
    docker compose -f "$SCRIPT_DIR/chronicle/backends/advanced/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle.override.yml" up -d

    echo "Starting mycelia..."
    docker compose -f "$SCRIPT_DIR/mycelia/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/mycelia.override.yml" up -d

    if [ -x "$EXOCORTEX_HELPER" ]; then
      echo "Starting exocortex control panel..."
      "$EXOCORTEX_HELPER" start || {
        echo "Warning: exocortex control panel was not started. Run 'npm ci --prefix exocortex/control-panel' and retry." >&2
      }
    fi

    echo ""
    echo "All services started. Access points:"
    echo "  Exocortex:      http://localhost:${EXOCORTEX_CONTROL_PANEL_PORT}"
    echo "  Ushadow:        http://localhost:8010"
    echo "  Chronicle:       http://localhost:9000"
    echo "  Chronicle UI:    http://localhost:9010"
    echo "  Mycelia:         http://localhost:3210"
    echo "  OpenMemory UI:   http://localhost:9001"
    echo "  OpenMemory API:  http://localhost:9765"
    ;;

  down|stop)
    echo "Stopping all services..."
    docker compose -f "$SCRIPT_DIR/mycelia/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/mycelia.override.yml" down
    docker compose -f "$SCRIPT_DIR/chronicle/backends/advanced/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle.override.yml" down
    docker compose -f "$SCRIPT_DIR/chronicle/extras/openmemory-mcp/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle-openmemory.override.yml" down
    docker compose -f "$SCRIPT_DIR/ushadow/docker-compose.yml" \
      -f "$SCRIPT_DIR/ushadow/compose/overrides/prod-webui.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-app.override.yml" down
    docker compose -f "$SCRIPT_DIR/ushadow/compose/docker-compose.infra.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-infra.override.yml" --profile infra down

    if [ -x "$EXOCORTEX_HELPER" ]; then
      "$EXOCORTEX_HELPER" stop || true
    fi
    ;;

  status)
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -50
    if [ -x "$EXOCORTEX_HELPER" ]; then
      echo ""
      "$EXOCORTEX_HELPER" status || true
    fi
    ;;

  *)
    echo "Usage: $0 {up|down|status}"
    ;;
esac
