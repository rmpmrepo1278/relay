#!/bin/bash
# Prune Docker build cache and dangling images
# Runs weekly via Hermes scheduler (Sun 3:30am)
# Build cache retention: 7 days (matches debloat.sh pattern)

set -euo pipefail

echo "=== Docker Build Cache Prune ==="
echo "Before:"
docker system df --format "table {{.Type}}\t{{.Size}}\t{{.Reclaimable}}" 2>/dev/null || docker system df

echo ""
echo "Pruning build cache older than 7 days..."
docker builder prune -af --filter until=168h 2>&1

echo ""
echo "Pruning dangling images..."
docker image prune -f 2>&1

echo ""
echo "After:"
docker system df --format "table {{.Type}}\t{{.Size}}\t{{.Reclaimable}}" 2>/dev/null || docker system df

echo ""
echo "Docker prune complete"
