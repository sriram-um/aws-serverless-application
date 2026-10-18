"""AnalyticsApi Lambda: store-wide sales analytics for members of the Cognito 'admins' group.

GET /analytics/daily?from=YYYY-MM-DD&to=YYYY-MM-DD  revenue / orders / units per day
GET /analytics/top-items?limit=10                   best-selling items by units sold
"""
import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.logging import correlation_paths
from boto3.dynamodb.conditions import Key

logger = Logger()
logger.append_keys(app_version=os.environ.get("APP_VERSION", "local"))
tracer = Tracer(patch_modules=["botocore"])

ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "admins")
MAX_DAYS = 92
table = boto3.resource(
    "dynamodb", endpoint_url=os.environ.get("DYNAMODB_ENDPOINT") or None
).Table(os.environ["STATS_TABLE_NAME"])


def _num(value):
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    return value


def _response(status_code, body):
    return {"statusCode": status_code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, default=_num)}


def _is_admin(event):
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("claims") or {}
    groups = claims.get("cognito:groups") or ""
    # API Gateway passes the groups claim as a string, e.g. "admins" or "[admins, other]"
    return ADMIN_GROUP in groups.strip("[]").replace(",", " ").split()


def _parse_day(value, name):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise ValueError(f"'{name}' must be a date in YYYY-MM-DD format")


@tracer.capture_method
def daily(params):
    today = datetime.now(timezone.utc).date()
    end = _parse_day(params["to"], "to") if params.get("to") else today
    start = _parse_day(params["from"], "from") if params.get("from") else end - timedelta(days=6)
    if start > end:
        raise ValueError("'from' must not be after 'to'")
    if (end - start).days + 1 > MAX_DAYS:
        raise ValueError(f"date range is limited to {MAX_DAYS} days")

    rows = table.query(KeyConditionExpression=Key("statType").eq("DAILY")
                       & Key("period").between(start.isoformat(), end.isoformat()))["Items"]
    days = [{"date": r["period"], "orders": r.get("orderCount", 0),
             "orderLines": r.get("orderLines", 0), "unitsSold": r.get("unitsSold", 0),
             "revenue": r.get("revenue", 0)} for r in rows]
    totals = {k: sum(d[k] for d in days) for k in ("orders", "orderLines", "unitsSold", "revenue")}
    return {"from": start.isoformat(), "to": end.isoformat(), "days": days, "totals": totals}


@tracer.capture_method
def top_items(params):
    try:
        limit = int(params.get("limit") or 10)
    except ValueError:
        raise ValueError("'limit' must be an integer")
    if not 1 <= limit <= 50:
        raise ValueError("'limit' must be between 1 and 50")

    items, kwargs = [], {"KeyConditionExpression": Key("statType").eq("ITEM")}
    while True:  # fine at portfolio scale; a sorted GSI / leaderboard would replace this at scale
        page = table.query(**kwargs)
        items.extend(page["Items"])
        if "LastEvaluatedKey" not in page:
            break
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    items.sort(key=lambda r: (r.get("unitsSold", 0), r.get("revenue", 0)), reverse=True)
    return {"limit": limit, "items": [{
        "itemId": r["period"], "productName": r.get("productName", ""),
        "unitsSold": r.get("unitsSold", 0), "revenue": r.get("revenue", 0)} for r in items[:limit]]}


ROUTES = {"/analytics/daily": daily, "/analytics/top-items": top_items}


@logger.inject_lambda_context(correlation_id_path=correlation_paths.API_GATEWAY_REST)
@tracer.capture_lambda_handler
def lambda_handler(event, context):
    if not _is_admin(event):
        return _response(403, {"message": f"requires membership in the '{ADMIN_GROUP}' group"})
    route = ROUTES.get(event.get("resource") or event.get("path"))
    if route is None:
        return _response(404, {"message": "not found"})
    try:
        return _response(200, route(event.get("queryStringParameters") or {}))
    except ValueError as err:
        return _response(400, {"message": str(err)})
