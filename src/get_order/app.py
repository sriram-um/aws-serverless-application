"""GetOrder Lambda: returns the caller's order, reading through DAX when DAX_ENDPOINT is set."""
import json
import os
import time
from decimal import Decimal

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.logging import correlation_paths
from boto3.dynamodb.conditions import Key

logger = Logger()
logger.append_keys(app_version=os.environ.get("APP_VERSION", "local"))
tracer = Tracer(patch_modules=["botocore"])

TABLE_NAME = os.environ["TABLE_NAME"]
DAX_ENDPOINT = os.environ.get("DAX_ENDPOINT") or None


def _make_table():
    # Created once per execution environment (outside the handler) and reused.
    if DAX_ENDPOINT:
        from amazondax import AmazonDaxClient  # only imported when DAX is enabled

        return AmazonDaxClient.resource(endpoint_url=DAX_ENDPOINT).Table(TABLE_NAME), "dax"
    resource = boto3.resource("dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None)
    return resource.Table(TABLE_NAME), "dynamodb"


table, BACKEND = _make_table()


def _json_default(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    raise TypeError(f"not JSON serializable: {type(value)}")


def _response(status_code, body, headers=None):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body, default=_json_default),
    }


@tracer.capture_method
def _query_order(order_id):
    # DAX does not go through botocore's HTTP stack, so time it explicitly for logs/traces.
    started = time.perf_counter()
    items = table.query(KeyConditionExpression=Key("orderId").eq(order_id))["Items"]
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    tracer.put_metadata(key="read", value={"backend": BACKEND, "ms": elapsed_ms})
    return items, elapsed_ms


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    order_id = ((event.get("pathParameters") or {}).get("orderId") or "").strip()
    if not order_id:
        return _response(400, {"message": "orderId is required"})

    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims") or {}
    customer_id = claims.get("sub")

    items, read_ms = _query_order(order_id)
    # Same rule as the direct integration: only the owner may read the order, and a
    # foreign order is indistinguishable from a missing one.
    items = [i for i in items if i.get("customerId") == customer_id]
    logger.info("order read", extra={"orderId": order_id, "backend": BACKEND,
                                     "readMs": read_ms, "found": bool(items)})
    headers = {"X-Read-Backend": BACKEND, "X-Read-Ms": str(read_ms)}
    if not items:
        return _response(404, {"message": "order not found"}, headers)

    return _response(200, {
        "orderId": order_id,
        "itemCount": len(items),
        "items": [{
            "itemId": i["itemId"],
            "productName": i.get("productName", ""),
            "quantity": i["quantity"],
            "unitPrice": i["unitPrice"],
            "status": i.get("status"),
            "createdAt": i.get("createdAt"),
        } for i in items],
    }, headers)
