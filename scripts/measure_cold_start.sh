#!/usr/bin/env bash
# Force N cold starts of a Lambda function and report Init Duration / Duration / Max Memory.
# A configuration change (here: the Description) makes Lambda discard warm execution
# environments, so the next invoke is a guaranteed cold start. The Description is restored
# by the next `sam deploy` (CloudFormation owns it).
#
# Usage: scripts/measure_cold_start.sh [function-name] [samples] [event-file]
set -euo pipefail

FN=${1:-orders-serverless-app-CreateOrder}
N=${2:-5}
EVENT=${3:-events/create_order.json}
ORIG_DESC=$(aws lambda get-function-configuration --function-name "$FN" --query Description --output text)
MEM=$(aws lambda get-function-configuration --function-name "$FN" --query MemorySize --output text)
OUT=$(mktemp)

printf "%-8s %10s %10s %8s\n" "sample" "init_ms" "dur_ms" "mem_mb"
inits=() durs=()
for i in $(seq 1 "$N"); do
  aws lambda update-function-configuration --function-name "$FN" \
    --description "cold-start probe $(date +%s%N)" >/dev/null
  aws lambda wait function-updated-v2 --function-name "$FN"
  report=$(aws lambda invoke --function-name "$FN" --payload "fileb://$EVENT" \
    --log-type Tail --query LogResult --output text "$OUT" | tr -d '[:space:]' | base64 -d | grep '^REPORT')
  init=$(sed -n 's/.*Init Duration: \([0-9.]*\) ms.*/\1/p' <<<"$report")
  dur=$(sed -n 's/.*\tDuration: \([0-9.]*\) ms.*/\1/p' <<<"$report")
  mem=$(sed -n 's/.*Max Memory Used: \([0-9]*\) MB.*/\1/p' <<<"$report")
  printf "%-8s %10s %10s %8s\n" "$i" "${init:-warm?}" "$dur" "$mem"
  inits+=("${init:-0}") durs+=("$dur")
done

aws lambda update-function-configuration --function-name "$FN" --description "$ORIG_DESC" >/dev/null
aws lambda wait function-updated-v2 --function-name "$FN"
rm -f "$OUT"

printf '%s\n' "${inits[@]}" | sort -n | awk -v mem="$MEM" -v n="$N" '
  {a[NR]=$1; s+=$1} END {printf "memory=%sMB  init: avg=%.0f ms  median=%.0f ms  min=%.0f  max=%.0f\n",
  mem, s/n, a[int((n+1)/2)], a[1], a[n]}'
printf '%s\n' "${durs[@]}" | awk '{s+=$1} END {printf "first-invoke duration: avg=%.0f ms\n", s/NR}'
