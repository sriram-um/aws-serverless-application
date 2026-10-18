#!/usr/bin/env bash
# Start DynamoDB Local in Docker and create the Orders table for `sam local` runs.
# Usage: scripts/local-setup.sh        (idempotent)
#        scripts/local-setup.sh down   (stop and remove the container + network)
set -euo pipefail

NETWORK=sam-local
CONTAINER=dynamodb-local
TABLE=orders-local
ENDPOINT=http://localhost:8000
# DynamoDB Local accepts any credentials; use dummy ones so nothing touches AWS
export AWS_ACCESS_KEY_ID=local AWS_SECRET_ACCESS_KEY=local AWS_DEFAULT_REGION=us-east-1
unset AWS_PROFILE

if [[ "${1:-}" == "down" ]]; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  docker network rm "$NETWORK" >/dev/null 2>&1 || true
  echo "DynamoDB Local stopped"
  exit 0
fi

docker network inspect "$NETWORK" >/dev/null 2>&1 || docker network create "$NETWORK" >/dev/null

if [[ -z "$(docker ps -q -f name="^${CONTAINER}$")" ]]; then
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  # -sharedDb: one database regardless of the caller's access key/region
  docker run -d --name "$CONTAINER" --network "$NETWORK" -p 8000:8000 \
    amazon/dynamodb-local -jar DynamoDBLocal.jar -sharedDb -inMemory >/dev/null
  echo "Started DynamoDB Local on $ENDPOINT (container '$CONTAINER', network '$NETWORK')"
  for _ in $(seq 1 20); do
    aws dynamodb list-tables --endpoint-url "$ENDPOINT" >/dev/null 2>&1 && break
    sleep 1
  done
fi

if ! aws dynamodb describe-table --table-name "$TABLE" --endpoint-url "$ENDPOINT" >/dev/null 2>&1; then
  aws dynamodb create-table --table-name "$TABLE" --endpoint-url "$ENDPOINT" \
    --billing-mode PAY_PER_REQUEST \
    --attribute-definitions AttributeName=orderId,AttributeType=S AttributeName=itemId,AttributeType=S \
    --key-schema AttributeName=orderId,KeyType=HASH AttributeName=itemId,KeyType=RANGE >/dev/null
  echo "Created table '$TABLE'"
fi

echo "Ready. Examples:"
echo "  sam build && sam local invoke CreateOrderFunction -e events/create_order.json --env-vars env.json --docker-network $NETWORK"
echo "  sam local start-api --env-vars env.json --docker-network $NETWORK"
echo "  aws dynamodb scan --table-name $TABLE --endpoint-url $ENDPOINT"
