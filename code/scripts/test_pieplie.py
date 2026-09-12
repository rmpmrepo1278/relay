#!/usr/bin/env python3
"""Test the pieplie pipeline without interactive prompts."""

import sys
from pathlib import Path

SCRIPT_DIR = Path('/opt/data/scripts')
sys.path.insert(0, str(SCRIPT_DIR))

from pieplie import run_pieplie

def main():
    # Test with Greenhouse URL
    greenhouse_url = "https://job-boards.greenhouse.io/newrelic/jobs/5396456008?gh_src=hlczvs1p8us"
    
    print("=== Testing pieplie pipeline ===")
    print(f"Greenhouse URL: {greenhouse_url}")
    print()
    
    # Run with dry_run=True first to test
    print("=== DRY RUN TEST ===")
    result = run_pieplie(greenhouse_url, force=True, dry_run=True)
    
    if result == 0:
        print("\n✓ Dry run completed successfully")
    else:
        print(f"\n✗ Dry run failed with return code: {result}")
    
    # Ask if user wants to run real test
    response = input("\nContinue with real pipeline run? (y/N): ").lower().strip()
    if response == 'y':
        print("\n=== REAL PIPELINE TEST ===")
        result = run_pieplie(greenhouse_url, force=True, dry_run=False)
        
        if result == 0:
            print("\n✓ Real pipeline run completed successfully")
        else:
            print(f"\n✗ Real pipeline run failed with return code: {result}")
    else:
        print("\nReal pipeline test skipped")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())