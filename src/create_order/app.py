"""CreateOrder Lambda: validates an order payload and saves one DynamoDB item per order line."""
import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.logging import correlation_paths

logger = Logger()
logger.append_keys(app_version=os.environ.get("APP_VERSION", "local"))  # git SHA set by CI
tracer = Tracer()  # patches boto3, so DynamoDB calls appear as X-Ray subsegments

TABLE_NAME = os.environ["TABLE_NAME"]
dynamodb = boto3.resource("dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None)
table = dynamodb.Table(TABLE_NAME)


class ValidationError(Exception):
    pass


def _response(status_code, body):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _parse_items(payload):
    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise ValidationError("'items' must be a non-empty list")
    if len(items) > 25:
        raise ValidationError("an order can contain at most 25 items")

    parsed, seen = [], set()
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValidationError(f"items[{i}] must be an object")
        item_id = item.get("itemId")
        if not isinstance(item_id, str) or not item_id.strip():
            raise ValidationError(f"items[{i}].itemId is required")
        if item_id in seen:
            raise ValidationError(f"duplicate itemId '{item_id}'")
        seen.add(item_id)

        quantity = item.get("quantity")
        if not isinstance(quantity, int) or isinstance(quantity, bool) or quantity < 1:
            raise ValidationError(f"items[{i}].quantity must be a positive integer")
        try:
            unit_price = Decimal(str(item.get("unitPrice")))
        except InvalidOperation:
            raise ValidationError(f"items[{i}].unitPrice must be a number")
        if not unit_price.is_finite() or unit_price < 0:
            raise ValidationError(f"items[{i}].unitPrice must be a non-negative number")

        parsed.append({
            "itemId": item_id,
            "productName": str(item.get("productName", "")),
            "quantity": quantity,
            "unitPrice": unit_price,
        })
    return parsed


def _customer_id(event):
    # Populated by the Cognito authorizer once the API is secured (exercise 4).
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims") or {}
    return claims.get("sub", "anonymous")


@tracer.capture_method
def _save_order(order_id, customer_id, items):
    created_at = datetime.now(timezone.utc).isoformat()
    with table.batch_writer() as batch:
        for item in items:
            batch.put_item(Item={
                "orderId": order_id,
                **item,
                "customerId": customer_id,
                "status": "CREATED",
                "createdAt": created_at,
            })


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    try:
        payload = json.loads(event.get("body") or "{}")
        if not isinstance(payload, dict):
            raise ValidationError("request body must be a JSON object")
        items = _parse_items(payload)
    except json.JSONDecodeError:
        logger.warning("rejected order: invalid JSON")
        return _response(400, {"message": "request body must be valid JSON"})
    except ValidationError as err:
        logger.warning("rejected order", extra={"reason": str(err)})
        return _response(400, {"message": str(err)})

    order_id = str(uuid.uuid4())
    customer_id = _customer_id(event)
    tracer.put_annotation(key="orderId", value=order_id)

    _save_order(order_id, customer_id, items)

    total = sum(i["unitPrice"] * i["quantity"] for i in items)
    logger.info("order created", extra={"orderId": order_id, "itemCount": len(items), "total": str(total)})
    return _response(201, {"orderId": order_id, "itemCount": len(items), "total": str(total)})
