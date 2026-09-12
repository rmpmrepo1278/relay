#!/bin/bash
# Session Debrief — Extract learnings from recent agent sessions
# Runs daily at 6:30am (after reflective_phase at 6am)
cd /home/rohit/.hermes/hermes-agent
python3 -c "
import sys, logging
sys.path.insert(0, '/home/rohit/.hermes/hermes-agent')
logging.basicConfig(level=logging.INFO, format='%(asctime)s debrief: %(message)s')
from plugins.sentinel.session_debrief import run_debrief
result = run_debrief()
print(f'Sessions analyzed: {result[\"sessions_analyzed\"]}')
print(f'Learnings extracted: {result[\"learnings_extracted\"]}')
print(f'SOPs extracted: {result[\"sops_extracted\"]}')
print(f'Observations saved: {result[\"observations_saved\"]}')
print(f'SOPs saved: {result[\"sops_saved\"]}')
print(f'Incident patterns: {len(result[\"incident_patterns\"])}')
" 2>&1 | tee -a /home/rohit/.hermes/logs/session_debrief.log
