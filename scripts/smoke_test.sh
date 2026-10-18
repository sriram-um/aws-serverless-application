#!/usr/bin/env bash
# End-to-end smoke test of a deployed stack, using the test users from ~/.orders-test-user.env
# (written by scripts/rebuild.sh). Checks every route, the ownership rule, the admins-only
# analytics API and the stream -> analytics pipeline. Creates one real order.
# Usage: bash scripts/smoke_test.sh
set -uo pipefail
export AWS_PROFILE=default AWS_DEFAULT_REGION=us-east-1
# shellcheck disable=SC1090
source ~/.orders-test-user.env   # USER_POOL_ID CLIENT_ID API_URL TEST_USER(2) TEST_PASSWORD(2)
fails=0
check() {  # check <description> <expected> <actual>
  if [ "$2" = "$3" ]; then echo "PASS  $1 ($3)"; else echo "FAIL  $1 (expected $2, got $3)"; fails=$((fails+1)); fi
}
token() {
  aws cognito-idp initiate-auth --auth-flow USER_PASSWORD_AUTH --client-id "$CLIENT_ID" \
    --auth-parameters USERNAME="$1",PASSWORD="$2" --query AuthenticationResult.IdToken --output text
}
code() { curl -s -o /dev/null -w "%{http_code}" "$@"; }

# A fresh deployment takes a few seconds to propagate: wait until routes answer
for _ in $(seq 1 30); do
  [ "$(code -X POST "$API_URL/orders" -d '{}')" = "401" ] && break
  sleep 2
done

T1=$(token "$TEST_USER" "$TEST_PASSWORD")
T2=$(token "$TEST_USER2" "$TEST_PASSWORD2")
DAY=$(date -u +%Y-%m-%d)

check "POST /orders without token" 401 "$(code -X POST "$API_URL/orders" -d '{}')"
check "POST /orders invalid body" 400 "$(code -X POST "$API_URL/orders" -H "Authorization: $T1" -d '{"items":[]}')"
resp=$(curl -s -w "\n%{http_code}" -X POST "$API_URL/orders" -H "Authorization: $T1" \
  -H "Content-Type: application/json" \
  -d '{"items":[{"itemId":"SKU-SMOKE","productName":"Smoke test","quantity":2,"unitPrice":5}]}')
check "POST /orders as user 1" 201 "$(tail -1 <<<"$resp")"
OID=$(head -1 <<<"$resp" | python -c "import json,sys; print(json.load(sys.stdin).get('orderId',''))")

check "GET /orders/{id} owner (Lambda)" 200 "$(code "$API_URL/orders/$OID" -H "Authorization: $T1")"
check "GET /orders/{id} other user" 404 "$(code "$API_URL/orders/$OID" -H "Authorization: $T2")"
check "GET /direct/orders/{id} owner (no Lambda)" 200 "$(code "$API_URL/direct/orders/$OID" -H "Authorization: $T1")"
check "GET /direct/orders/{id} other user" 404 "$(code "$API_URL/direct/orders/$OID" -H "Authorization: $T2")"
check "GET /analytics/daily non-admin" 403 "$(code "$API_URL/analytics/daily" -H "Authorization: $T2")"

# Stream -> aggregator -> OrderStats: the order should show up in today's stats
seen=0
for _ in $(seq 1 24); do
  units=$(curl -s "$API_URL/analytics/daily?from=$DAY&to=$DAY" -H "Authorization: $T1" \
    | python -c "import json,sys; print(json.load(sys.stdin).get('totals',{}).get('unitsSold',0))" 2>/dev/null)
  [ "${units:-0}" -ge 2 ] 2>/dev/null && { seen=1; break; }
  sleep 5
done
check "analytics counted the new order (stream pipeline)" 1 "$seen"
check "GET /analytics/top-items admin" 200 "$(code "$API_URL/analytics/top-items?limit=3" -H "Authorization: $T1")"

echo
[ $fails -eq 0 ] && echo "ALL CHECKS PASSED" || { echo "$fails CHECK(S) FAILED"; exit 1; }
