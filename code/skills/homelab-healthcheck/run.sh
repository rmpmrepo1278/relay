#!/usr/bin/env bash
echo "=== HERMES HOMELAB HEALTH CHECK ==="
echo "timestamp: $(date -Iseconds)"
echo ""
echo "--- SYSTEM RESOURCES ---"
uptime
free -h
df -h /
echo ""
echo "--- DOCKER ---"
docker ps --format "table {{.Names}}\t{{.Status}}" | head -25
docker system df
echo ""
echo "--- KEY SERVICES ---"
docker ps --filter name=hermes --format "{{.Names}}: {{.Status}}"
docker ps --filter name=ollama --format "{{.Names}}: {{.Status}}"
curl -s --max-time 3 http://localhost:11434/api/tags | python3 -c "import json,sys; d=json.load(sys.stdin); print('Ollama Models:', [m['name'] for m in d.get('models',[])])" 2>/dev/null || echo "Ollama unreachable"
curl -s --max-time 3 http://localhost:8080/health && echo "Proxy: Running" || echo "Proxy: Down"
curl -s --max-time 5 -o /dev/null -w "Telegram API: HTTP %{http_code}\n" https://api.telegram.org
echo ""
echo "--- NETWORK ---"
dig +short google.com 2>/dev/null | head -3 || echo "DNS check failed"
echo ""
echo "=== HEALTH CHECK COMPLETE ==="
