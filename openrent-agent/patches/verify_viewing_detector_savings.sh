#!/usr/bin/env bash
# Verify the viewing-detector cost gate (patch: viewing_detector_cost_gate_20260825.patch).
# Read-only: only reads the systemd journal. Run BEFORE deploy (baseline is already
# recorded below) and again >=24h AFTER deploy, then compare against the thresholds.
#
# Usage (from Git Bash on the workstation, or directly on the prod host):
#   ssh -i ~/.ssh/hetzner -o IdentitiesOnly=yes root@178.105.225.12 'bash -s' < verify_viewing_detector_savings.sh
# or paste the journalctl|awk block below into a prod shell.
#
# ---------------------------------------------------------------------------
# PRE-DEPLOY BASELINE (openrent-rq-worker, 24h ending 2026-08-25 ~09:45 UTC):
#   detector_calls_total        = 6328
#   distinct_detector_threads   = 505
#   rerun_multiple              = 12.5x
#   calls_per_run               = 23.7   (runs=267)
#   distinct_threads_BOOKING_detected = 123   <- safety invariant
#   cancellations_sent                = 32    <- safety invariant
#   handoff_after_cancellation        = 32    <- safety invariant
#   replies_generated                 = 250   <- safety invariant
#
# PASS CRITERIA (>=24h after deploy):
#   PRIMARY (savings):
#     rerun_multiple        drops to ~1-3x   (from 12.5x)   << main signal
#     detector_calls_total  drops ~80-90%    (to ~600-1300)
#     calls_per_run         drops to <5      (from 23.7)
#   SAFETY (must stay ~flat, +/-20% allowing for daily volume):
#     distinct_threads_BOOKING_detected  ~= 123  (real bookings still detected)
#     cancellations_sent / handoff_after_cancellation ~= 32 (cancel flow intact)
#     replies_generated  ~= 250 (unrelated to detector; a drop = investigate)
#   FAIL / ROLLBACK if: bookings_detected or cancellations_sent fall materially
#   (e.g. >30%) while detector_calls drop -> a real detection was gated out.
# ---------------------------------------------------------------------------

journalctl -u openrent-rq-worker --since "24 hours ago" --no-pager -o cat 2>/dev/null | awk '
/AI_VIEWING_DETECTED / {vd++; if (match($0,/thread_id=[0-9]+/)) det[substr($0,RSTART,RLENGTH)]=1}
/AI_VIEWING_NOT_DETECTED/ {vnd++}
/AI_VIEWING_DETECTED_NO_DATETIME/ {vndt++}
/AI_VIEWING/ { if (match($0,/thread_id=[0-9]+/)) seen[substr($0,RSTART,RLENGTH)]=1 }
/REPLIES_STARTED/ {runs++}
/Generating AI reply for thread/ {gen++}
/VIEWING_CANCEL_TRIGGERED/ {ctrig++}
/VIEWING_CANCEL_SENT/ {csent++}
/VIEWING_CANCEL_NOW/ {cnow++}
/HANDOFF_AFTER_CANCELLATION/ {chand++}
END{
 calls=vd+vnd+vndt; dc=0; for(k in seen) dc++; dd=0; for(k in det) dd++
 print "=== openrent-rq-worker last 24h ==="
 printf "detector_calls_total        = %d\n", calls
 printf "distinct_detector_threads   = %d\n", dc
 printf "rerun_multiple              = %.1fx\n", (dc? calls/dc:0)
 printf "calls_per_run               = %.1f  (runs=%d)\n", (runs? calls/runs:0), runs
 print  "--- SAFETY INVARIANTS (must stay ~flat) ---"
 printf "distinct_threads_BOOKING_detected = %d\n", dd
 printf "cancellations_triggered           = %d\n", ctrig
 printf "cancellations_sent                = %d\n", csent
 printf "cancel_now(sweep)                 = %d\n", cnow
 printf "handoff_after_cancellation        = %d\n", chand
 printf "replies_generated                 = %d\n", gen
}'
