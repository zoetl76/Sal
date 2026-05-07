#!/usr/bin/env bash
# PostTrade.sh — Layer 3 Guardrail Hook
# Runs after every execution. Logs the fill to trades.log (gitignored).
#
# Usage:
#   PostTrade.sh \
#     --instrument ES \
#     --direction long \
#     --entry 5234.50 \
#     --stop 5230.00 \
#     --size 2 \
#     --setup breakout

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="${ROOT}/trades.log"

INSTRUMENT=""
DIRECTION=""
ENTRY=""
STOP=""
SIZE=""
SETUP=""
NOTES=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --instrument) INSTRUMENT="$2"; shift 2;;
    --direction)  DIRECTION="$2";  shift 2;;
    --entry)      ENTRY="$2";      shift 2;;
    --stop)       STOP="$2";       shift 2;;
    --size)       SIZE="$2";       shift 2;;
    --setup)      SETUP="$2";      shift 2;;
    --notes)      NOTES="$2";      shift 2;;
    *) echo "unknown arg: $1" >&2; exit 1;;
  esac
done

for v in INSTRUMENT DIRECTION ENTRY STOP SIZE SETUP; do
  if [[ -z "${!v}" ]]; then
    echo "missing required arg: --${v,,}" >&2
    exit 1
  fi
done

TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# JSON-line format for downstream parsing by journal-analyzer subagent.
printf '{"ts":"%s","instrument":"%s","direction":"%s","entry":%s,"stop":%s,"size":%s,"setup":"%s","notes":"%s"}\n' \
  "$TS" "$INSTRUMENT" "$DIRECTION" "$ENTRY" "$STOP" "$SIZE" "$SETUP" "${NOTES//\"/\\\"}" \
  >> "$LOG"

echo "logged: $TS $INSTRUMENT $DIRECTION @ $ENTRY stop $STOP size $SIZE setup=$SETUP"
