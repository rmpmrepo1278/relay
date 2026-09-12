#!/usr/bin/env bash
# =============================================================================
# Daily AI News Digest — sends 8-10 items to Telegram
#
# Uses interest_profile.json for personalized topic filtering.
# Reads Telegram credentials from ~/.hermes/.env.
#
# Cron: 0 8 * * * /home/rohit/.hermes/cron/send_daily_digest.sh
# =============================================================================

set -euo pipefail

HERMES_HOME="/home/rohit/.hermes"
LOG_FILE="$HERMES_HOME/cron/output/digest.log"

mkdir -p "$HERMES_HOME/cron/output"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] digest: $*" >> "$LOG_FILE"; }

# Load credentials from .env
if [ -f "$HERMES_HOME/.env" ]; then
    set -a
    source "$HERMES_HOME/.env"
    set +a
fi

INTEREST_FILE="$HERMES_HOME/interest_profile.json"

# Build RSS query
if [ -f "$INTEREST_FILE" ]; then
    QUERIES=$(/home/rohit/.hermes/hermes-agent/.venv/bin/python3 -c "
import json, urllib.request, sys
with open('$INTEREST_FILE') as f:
    data = json.load(f)
queries = data.get('sources', {}).get('google_news_rss_queries', [])
# URL-encode the queries
print(urllib.request.quote(' OR '.join(queries)))
" 2>/dev/null)
    RSS_URL="https://news.google.com/rss/search?q=${QUERIES}&hl=en-US&gl=US&ceid=US:en"
else
    # Fallback to default query
    RSS_URL="https://news.google.com/rss/search?q=local+LLM+OR+Claude+Code+OR+AI+agents+OR+llama.cpp+OR+GGUF+OR+autonomous+agents&hl=en-US&gl=US&ceid=US:en"
fi

log "Fetching digest from: ${RSS_URL:0:120}..."

# Fetch and parse RSS with Python stdlib
DIGEST=$(/home/rohit/.hermes/hermes-agent/.venv/bin/python3 -c "
import urllib.request
import xml.etree.ElementTree as ET
import html
import re
import sys
import json

url = sys.argv[1]
try:
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
except Exception as e:
    print(f'FETCH_ERROR:{e}', file=sys.stderr)
    sys.exit(1)

root = ET.fromstring(data)
items = root.findall('.//item')[:15]

if not items:
    print('NO_ITEMS', file=sys.stderr)
    sys.exit(1)

# Load interest profile for filtering
interest_data = {}
try:
    with open('${INTEREST_FILE}') as f:
        interest_data = json.load(f)
except Exception:
    pass

# Build keyword sets from interest profile
high_priority = set()
medium_priority = set()
exclude = set(interest_data.get('exclude', []))

for topic in interest_data.get('topics', {}).get('primary', []):
    for kw in topic.get('keywords', []):
        if topic.get('priority') == 'high':
            high_priority.add(kw.lower())
        else:
            medium_priority.add(kw.lower())

for topic in interest_data.get('topics', {}).get('secondary', []):
    for kw in topic.get('keywords', []):
        medium_priority.add(kw.lower())

# Score and filter items
scored_items = []
for item in items:
    title = item.findtext('title', 'No title')
    link = item.findtext('link', '')
    desc_raw = item.findtext('description', '')
    source_match = re.search(r'font color=\"#6f6f6f\">(.*?)</font>', desc_raw)
    source = html.unescape(source_match.group(1)) if source_match else ''

    title_lower = title.lower()

    # Check exclusions
    if any(excl.lower() in title_lower for excl in exclude):
        continue

    # Score
    score = 0
    for kw in high_priority:
        if kw in title_lower:
            score += 3
    for kw in medium_priority:
        if kw in title_lower:
            score += 1

    scored_items.append((score, title, link, source))

# Sort by score descending, take top 10
scored_items.sort(key=lambda x: x[0], reverse=True)
top_items = scored_items[:10]

if not top_items:
    # Fallback: just take first 10
    for item in items[:10]:
        title = item.findtext('title', 'No title')
        link = item.findtext('link', '')
        desc_raw = item.findtext('description', '')
        source_match = re.search(r'font color=\"#6f6f6f\">(.*?)</font>', desc_raw)
        source = html.unescape(source_match.group(1)) if source_match else ''
        top_items.append((0, title, link, source))

lines = []
lines.append('🌅 Good morning! Here is your personalized daily digest:\n')
for i, (score, title, link, source) in enumerate(top_items, 1):
    source_tag = f' ({source})' if source else ''
    priority_tag = ' 🔥' if score >= 3 else ''
    lines.append(f'{i}. {title}{source_tag}{priority_tag}\n   {link}\n')

print('\n'.join(lines))
" "$RSS_URL" 2>>"$LOG_FILE")

if [ -z "$DIGEST" ]; then
    log "Digest was empty or fetch failed, skipping send"
    exit 0
fi

# Send to Telegram via bridge
send_telegram() {
    local attempt=1
    local max_attempts=3

    while [ $attempt -le $max_attempts ]; do
        # Use Python bridge instead of curl
        result=$(/home/rohit/.hermes/hermes-agent/.venv/bin/python3 -c "
import sys
sys.path.insert(0, '/home/rohit/.hermes/scripts')
from telegram_bridge import send_telegram_markdown
result = send_telegram_markdown('''${DIGEST}''')
print('SUCCESS' if result.get('status') == 'ok' else 'FAIL')
" 2>>"$LOG_FILE")

        if [ "$result" = "SUCCESS" ]; then
            log "Digest sent successfully via bridge (attempt ${attempt})"
            return 0
        fi

        log "Telegram send attempt ${attempt} failed"
        attempt=$((attempt + 1))
        [ $attempt -le $max_attempts ] && sleep 5
    done

    log "ERROR: All ${max_attempts} Telegram send attempts failed"
    return 1
}

send_telegram
