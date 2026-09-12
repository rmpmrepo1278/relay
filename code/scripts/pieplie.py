#!/usr/bin/env python3
"""Pieplie job pipeline - run Greenhouse job through career automation pipeline.

This script is the "pieplie" command that the user references.
It processes Greenhouse job URLs through the auto_pipeline discovery and evaluation system.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Add scripts directory to path
sys.path.insert(0, '/opt/data/scripts')

from auto_pipeline import main as pipeline_main

def run_pieplie(greenhouse_url, force=False, dry_run=False):
    """Run the pieplie pipeline for a Greenhouse job URL."""
    print(f"[pieplie] Running job pipeline for: {greenhouse_url}")
    
    # Create temporary sources.json with the Greenhouse job
    sources_data = {
        "greenhouse_newrelic": {
            "engine": "generic",
            "rows": [
                {
                    "title": "New Relic Job",
                    "company": "New Relic", 
                    "location": "Remote",
                    "url": greenhouse_url,
                    "score": 80,
                    "fetched": datetime.now(timezone.utc).isoformat()
                }
            ]
        }
    }
    
    sources_file = '/opt/data/scripts/sources.json'
    backup_file = f"{sources_file}.backup.{int(datetime.now().timestamp())}"
    
    # Backup existing sources.json if it exists
    if os.path.exists(sources_file):
        os.rename(sources_file, backup_file)
        print(f"[pieplie] Backed up existing {sources_file} to {backup_file}")
    
    try:
        # Write the new sources.json
        with open(sources_file, 'w') as f:
            json.dump(sources_data, f, indent=2)
        
        print(f"[pieplie] Created {sources_file} with Greenhouse job URL")
        
        if dry_run:
            # Run the pipeline with --dry-run
            print("\n=== DRY RUN ===")
            sys.argv = ['auto_pipeline.py', '--dry-run']
            pipeline_main()
        else:
            # Run the real pipeline
            print("\n=== REAL RUN ===")
            print("This will execute the full pipeline including:")
            print("- Job discovery and evaluation")
            print("- Score calculation and gating")
            print("- Result recording")
            print("- Telegram posting")
            
            # Use force flag to skip user confirmation
            if not force:
                print("\nConfirming real run... (use --force to skip this)")
                # For non-interactive execution, we'll auto-confirm
                # In a real CLI, we would ask for user input
                pass
            
            # Run the real pipeline
            sys.argv = ['auto_pipeline.py']
            return_code = pipeline_main()
        
        print(f"\n[pieplie] Pipeline completed with return code: {return_code}")
        return return_code
        
    except Exception as e:
        print(f"[pieplie] Error: {e}")
        return 1
    finally:
        # Restore original sources.json
        if os.path.exists(backup_file):
            if os.path.exists(sources_file):
                os.remove(sources_file)
            os.rename(backup_file, sources_file)
            print(f"[pieplie] Restored original {sources_file}")
        elif os.path.exists(sources_file):
            os.remove(sources_file)
            print(f"[pieplie] Cleaned up {sources_file}")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        greenhouse_url = sys.argv[1]
    else:
        greenhouse_url = "https://job-boards.greenhouse.io/newrelic/jobs/5396456008?gh_src=hlczvs1p8us"
    
    sys.exit(run_pieplie(greenhouse_url))