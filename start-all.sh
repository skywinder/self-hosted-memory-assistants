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

## Bring down all combined-mode services (quiet, ignores errors)
do_down() {
  docker compose -f "$SCRIPT_DIR/mycelia/docker-compose.yml" \
    -f "$SCRIPT_DIR/overrides/mycelia.override.yml" down 2>/dev/null || true
  docker compose -f "$SCRIPT_DIR/chronicle/backends/advanced/docker-compose.yml" \
    -f "$SCRIPT_DIR/overrides/chronicle.override.yml" down 2>/dev/null || true
  docker compose -f "$SCRIPT_DIR/chronicle/extras/openmemory-mcp/docker-compose.yml" \
    -f "$SCRIPT_DIR/overrides/chronicle-openmemory.override.yml" down 2>/dev/null || true
  docker compose -f "$SCRIPT_DIR/ushadow/docker-compose.yml" \
    -f "$SCRIPT_DIR/ushadow/compose/overrides/prod-webui.yml" \
    -f "$SCRIPT_DIR/overrides/ushadow-app.override.yml" down 2>/dev/null || true
  docker compose -f "$SCRIPT_DIR/ushadow/compose/docker-compose.infra.yml" \
    -f "$SCRIPT_DIR/overrides/ushadow-infra.override.yml" --profile infra down 2>/dev/null || true
  if [ -x "$EXOCORTEX_HELPER" ]; then
    "$EXOCORTEX_HELPER" stop 2>/dev/null || true
  fi
}

## Pre-flight: stop standalone containers that would conflict
stop_standalone_conflicts() {
  local standalone_containers
  standalone_containers=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^ushadow-second-|^mycelia-|^advanced-' || true)
  if [ -n "$standalone_containers" ]; then
    echo "Stopping standalone containers that would conflict..."
    echo "$standalone_containers" | sed 's/^/  - /'
    # Stop each standalone project
    cd "$SCRIPT_DIR/ushadow" && docker compose down 2>/dev/null || true
    cd "$SCRIPT_DIR/mycelia" && docker compose down 2>/dev/null || true
    cd "$SCRIPT_DIR/chronicle/backends/advanced" && docker compose down 2>/dev/null || true
    cd "$SCRIPT_DIR"
    echo ""
  fi
}

case "${1:-up}" in
  up|start)
    stop_standalone_conflicts
    echo "Stopping previous combined-mode containers..."
    do_down
    echo ""
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
      -f "$SCRIPT_DIR/overrides/chronicle.override.yml" up --build -d

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
    echo "============================================"
    echo "  All services started"
    echo "============================================"
    echo ""
    echo "Project          URL                              Description"
    echo "───────────────  ───────────────────────────────  ────────────────────────────────"
    echo "Ushadow          http://localhost:8010             Dashboard & service aggregator"
    echo "Ushadow UI       http://localhost:8011             Web frontend"
    echo "Chronicle API    http://localhost:9000             Audio processing & memory backend"
    echo "Chronicle UI     http://localhost:9010             Conversations & memories dashboard"
    echo "Mycelia          http://localhost:3210             Knowledge graph & notes"
    echo "OpenMemory UI    http://localhost:9001             Shared memory browser"
    echo "OpenMemory API   http://localhost:9765             Memory store REST API"
    echo "Exocortex        http://localhost:${EXOCORTEX_CONTROL_PANEL_PORT}             Control panel"
    echo ""
    echo "Infrastructure   Port                             Service"
    echo "───────────────  ───────────────────────────────  ────────────────────────────────"
    echo "Chronicle Mongo  localhost:27018                   MongoDB (chronicle data)"
    echo "Chronicle Redis  localhost:6380                    Redis (job queues)"
    echo "Chronicle Neo4j  localhost:7475                    Neo4j browser (knowledge graph)"
    echo "Ushadow Mongo    localhost:27020                   MongoDB (ushadow data)"
    echo "Ushadow Redis    localhost:6382                    Redis (ushadow sessions)"
    echo "Ushadow Qdrant   localhost:6335                    Qdrant (ushadow vectors)"
    echo "OpenMem Qdrant   localhost:9335                    Qdrant (shared memory vectors)"
    echo "Mycelia Mongo    localhost:27019                   MongoDB (mycelia data)"
    echo ""
    echo "Shared network: memory-net (cross-module communication)"
    echo "Memory flow: Chronicle -> OpenMemory MCP -> Ushadow (query via proxy)"
    echo ""

    # Health checks
    echo "Checking service health..."
    echo ""
    check_health() {
      local name="$1" url="$2"
      if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
        echo "  [UP]   $name"
      else
        echo "  [----] $name  (starting or unreachable)"
      fi
    }
    check_health "Ushadow API"     "http://localhost:8010/health"
    check_health "Chronicle API"   "http://localhost:9000/health"
    check_health "OpenMemory API"  "http://localhost:9765/docs"
    check_health "Mycelia"         "http://localhost:3210"
    echo ""
    echo "Note: services may take 30-60s to become healthy after first start."
    echo "Run '$0 status' to check container states."
    ;;

  down|stop)
    echo "Stopping all services..."
    do_down
    echo "All services stopped."
    ;;

  status)
    echo "============================================"
    echo "  Container Status"
    echo "============================================"
    echo ""

    show_project() {
      local label="$1" pattern="$2"
      local containers
      containers=$(docker ps -a --format '{{.Names}}\t{{.Status}}' 2>/dev/null | grep -E "$pattern" || true)
      if [ -n "$containers" ]; then
        echo "[$label]"
        echo "$containers" | while IFS=$'\t' read -r name status; do
          if echo "$status" | grep -q "^Up"; then
            printf "  %-35s %s\n" "$name" "$status"
          else
            printf "  %-35s %s\n" "$name" "$status"
          fi
        done
        echo ""
      fi
    }

    show_project "Ushadow"     "^ushadow-|^infra-"
    show_project "Chronicle"   "^advanced-"
    show_project "OpenMemory"  "^mem0|^openmemory-mcp-"
    show_project "Mycelia"     "^mycelia-"

    # Health probes
    echo "Service Health:"
    check_health() {
      local name="$1" url="$2"
      if curl -sf --max-time 3 "$url" >/dev/null 2>&1; then
        printf "  %-20s UP    %s\n" "$name" "$url"
      else
        printf "  %-20s DOWN  %s\n" "$name" "$url"
      fi
    }
    check_health "Ushadow API"    "http://localhost:8010/health"
    check_health "Chronicle API"  "http://localhost:9000/health"
    check_health "OpenMemory API" "http://localhost:9765/docs"
    check_health "Mycelia"        "http://localhost:3210"
    echo ""

    if [ -x "$EXOCORTEX_HELPER" ]; then
      "$EXOCORTEX_HELPER" status || true
      echo ""
    fi

    # Standalone detection
    local standalone
    standalone=$(docker ps --format '{{.Names}}' 2>/dev/null | grep -E '^ushadow-second-' || true)
    if [ -n "$standalone" ]; then
      echo "NOTE: Standalone ushadow containers also running (project: ushadow-second)"
      echo "$standalone" | sed 's/^/  - /'
      echo ""
    fi
    ;;

  *)
    echo "Usage: $0 {up|down|status}"
    ;;
esac
