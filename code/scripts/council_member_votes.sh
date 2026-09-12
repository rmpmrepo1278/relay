#!/usr/bin/env bash
# council_member_votes — each Agent Parliament member casts an evidence-based
# ballot on any open proposal. Idempotent: members may vote once per proposal.
H="/home/rohit/.hermes"
for m in learning_integrator insight_engine adversarial_engine predictive_signals self_correction; do
  python3 "$H/scripts/$m.py" --vote-council 2>/dev/null
done
