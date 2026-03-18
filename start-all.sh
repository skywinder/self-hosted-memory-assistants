#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
      -f "$SCRIPT_DIR/overrides/ushadow-app.override.yml" up -d

    echo "Starting chronicle..."
    docker compose -f "$SCRIPT_DIR/chronicle/backends/advanced/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle.override.yml" up -d

    echo "Starting mycelia..."
    docker compose -f "$SCRIPT_DIR/mycelia/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/mycelia.override.yml" up -d

    echo ""
    echo "All services started. Access points:"
    echo "  Ushadow:      http://localhost:8010"
    echo "  Chronicle:     http://localhost:9000"
    echo "  Chronicle UI:  http://localhost:9010"
    echo "  Mycelia:       http://localhost:3210"
    ;;

  down|stop)
    echo "Stopping all services..."
    docker compose -f "$SCRIPT_DIR/mycelia/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/mycelia.override.yml" down
    docker compose -f "$SCRIPT_DIR/chronicle/backends/advanced/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/chronicle.override.yml" down
    docker compose -f "$SCRIPT_DIR/ushadow/docker-compose.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-app.override.yml" down
    docker compose -f "$SCRIPT_DIR/ushadow/compose/docker-compose.infra.yml" \
      -f "$SCRIPT_DIR/overrides/ushadow-infra.override.yml" --profile infra down
    ;;

  status)
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | head -50
    ;;

  *)
    echo "Usage: $0 {up|down|status}"
    ;;
esac
