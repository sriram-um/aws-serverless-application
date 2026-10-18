"""AnalyticsAggregator Lambda: Orders table stream (INSERT events) -> OrderStats counters.

Each stream record (one order line) is applied exactly once: a transaction writes an
EVENT#<eventID> marker (condition: not seen before) together with the daily and per-item
counter updates, so a retried batch cannot double-count. Orders are counted once per
orderId through an ORDER#<orderId> marker.
"""
import os
import time
from decimal import Decimal

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.batch import (
    BatchProcessor,
    EventType,
    process_partial_response,
)
from boto3.dynamodb.types import TypeDeserializer
from botocore.exceptions import ClientError

logger = Logger()
logger.append_keys(app_version=os.environ.get("APP_VERSION", "local"))
tracer = Tracer(patch_modules=["botocore"])
processor = BatchProcessor(event_type=EventType.DynamoDBStreams)

STATS_TABLE = os.environ["STATS_TABLE_NAME"]
MARKER_TTL_SECONDS = 7 * 24 * 3600
client = boto3.client("dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None)
_deserializer = TypeDeserializer()


def _plain(image):
    return {k: _deserializer.deserialize(v) for k, v in image.items()}


def _counter_update(pk, sk, adds, sets=None):
    names, values, add_parts, set_parts = {}, {}, [], []
    for i, (attr, amount) in enumerate(adds.items()):
        names[f"#a{i}"] = attr
        values[f":a{i}"] = {"N": str(amount)}
        add_parts.append(f"#a{i} :a{i}")
    for i, (attr, value) in enumerate((sets or {}).items()):
        names[f"#s{i}"] = attr
        values[f":s{i}"] = {"S": value}
        set_parts.append(f"#s{i} = :s{i}")
    expression = "ADD " + ", ".join(add_parts)
    if set_parts:
        expression += " SET " + ", ".join(set_parts)
    return {"Update": {
        "TableName": STATS_TABLE,
        "Key": {"statType": {"S": pk}, "period": {"S": sk}},
        "UpdateExpression": expression,
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }}


def _marker_put(pk, sk, expires_at):
    return {"Put": {
        "TableName": STATS_TABLE,
        "Item": {"statType": {"S": pk}, "period": {"S": sk},
                 "expiresAt": {"N": str(expires_at)}},
        "ConditionExpression": "attribute_not_exists(statType)",
    }}


def _is_duplicate(err):
    reasons = err.response.get("CancellationReasons") or []
    return err.response["Error"]["Code"] == "TransactionCanceledException" and any(
        r.get("Code") == "ConditionalCheckFailed" for r in reasons)


@tracer.capture_method
def record_handler(record):
    line = _plain(record.raw_event["dynamodb"]["NewImage"])
    if "customerId" not in line or "createdAt" not in line:
        return  # not an order line (e.g. a replication probe)

    quantity = int(line["quantity"])
    revenue = Decimal(line["unitPrice"]) * quantity
    day = line["createdAt"][:10]
    expires_at = int(time.time()) + MARKER_TTL_SECONDS

    try:
        client.transact_write_items(TransactItems=[
            _marker_put("EVENT", record.event_id, expires_at),
            _counter_update("DAILY", day, {"revenue": revenue, "unitsSold": quantity,
                                           "orderLines": 1}),
            _counter_update("ITEM", line["itemId"], {"revenue": revenue, "unitsSold": quantity},
                            {"productName": line.get("productName", "")}),
        ])
    except ClientError as err:
        if _is_duplicate(err):
            logger.info("duplicate stream record skipped", extra={"eventID": record.event_id})
            return
        raise

    # Count each order once, on whichever of its lines arrives first.
    try:
        client.transact_write_items(TransactItems=[
            _marker_put("ORDER", line["orderId"], expires_at),
            _counter_update("DAILY", day, {"orderCount": 1}),
        ])
    except ClientError as err:
        if not _is_duplicate(err):
            raise


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    return process_partial_response(event=event, record_handler=record_handler,
                                    processor=processor, context=context)
