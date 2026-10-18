import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

ROOT = Path(__file__).resolve().parents[2] / "src"
STATS = "test-stats"


@dataclass
class FakeLambdaContext:
    function_name: str = "Analytics"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = "arn:aws:lambda:us-east-1:123456789012:function:Analytics"
    aws_request_id: str = "test-request-id"


CTX = FakeLambdaContext()


def _load(name):
    spec = importlib.util.spec_from_file_location(f"{name}_app", ROOT / name / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("STATS_TABLE_NAME", STATS)
    monkeypatch.setenv("POWERTOOLS_TRACE_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=STATS,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "statType", "AttributeType": "S"},
                {"AttributeName": "period", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "statType", "KeyType": "HASH"},
                {"AttributeName": "period", "KeyType": "RANGE"},
            ],
        )
        yield boto3.resource("dynamodb").Table(STATS)


def _record(event_id, order_id, item_id, qty, price, day="2026-10-18", name="Thing"):
    return {
        "eventID": event_id,
        "eventName": "INSERT",
        "eventSource": "aws:dynamodb",
        "dynamodb": {"NewImage": {
            "orderId": {"S": order_id}, "itemId": {"S": item_id},
            "customerId": {"S": "user-1"}, "productName": {"S": name},
            "quantity": {"N": str(qty)}, "unitPrice": {"N": str(price)},
            "createdAt": {"S": f"{day}T10:00:00+00:00"},
        }, "SequenceNumber": event_id},
    }


def test_aggregates_orders_lines_and_items(aws):
    agg = _load("analytics_aggregator")
    event = {"Records": [
        _record("e1", "o1", "A", 2, "10.50", name="Mouse"),
        _record("e2", "o1", "B", 1, "4", name="Hub"),
        _record("e3", "o2", "A", 3, "10.50", name="Mouse"),
    ]}
    assert agg.lambda_handler(event, CTX) == {"batchItemFailures": []}

    day = aws.get_item(Key={"statType": "DAILY", "period": "2026-10-18"})["Item"]
    assert day["orderCount"] == 2           # o1 counted once despite two lines
    assert day["orderLines"] == 3
    assert day["unitsSold"] == 6
    assert day["revenue"] == pytest.approx(56.5)
    item_a = aws.get_item(Key={"statType": "ITEM", "period": "A"})["Item"]
    assert item_a["unitsSold"] == 5 and item_a["productName"] == "Mouse"


def test_redelivered_record_is_not_double_counted(aws):
    agg = _load("analytics_aggregator")
    event = {"Records": [_record("e1", "o1", "A", 2, "10")]}
    agg.lambda_handler(event, CTX)
    agg.lambda_handler(event, CTX)  # stream retry delivers the same eventID again
    day = aws.get_item(Key={"statType": "DAILY", "period": "2026-10-18"})["Item"]
    assert day["revenue"] == 20 and day["orderCount"] == 1


def test_ignores_non_order_items(aws):
    agg = _load("analytics_aggregator")
    probe = {"eventID": "p1", "eventName": "INSERT", "eventSource": "aws:dynamodb",
             "dynamodb": {"NewImage": {"orderId": {"S": "replication-probe"},
                                       "itemId": {"S": "x"}}, "SequenceNumber": "p1"}}
    assert agg.lambda_handler({"Records": [probe]}, CTX) == {"batchItemFailures": []}
    assert aws.scan()["Items"] == []


def _api_event(resource, params=None, groups="admins"):
    claims = {"sub": "user-1"}
    if groups is not None:
        claims["cognito:groups"] = groups
    return {"resource": resource, "path": resource, "queryStringParameters": params,
            "requestContext": {"authorizer": {"claims": claims}}}


def test_api_requires_admin_group(aws):
    api = _load("analytics_api")
    assert api.lambda_handler(_api_event("/analytics/daily", groups=None), CTX)["statusCode"] == 403
    assert api.lambda_handler(_api_event("/analytics/daily", groups="other"), CTX)["statusCode"] == 403


def test_api_daily_and_top_items(aws):
    agg, api = _load("analytics_aggregator"), _load("analytics_api")
    agg.lambda_handler({"Records": [
        _record("e1", "o1", "A", 2, "10", day="2026-10-17", name="Mouse"),
        _record("e2", "o2", "B", 5, "1", day="2026-10-18", name="Cable"),
        _record("e3", "o3", "A", 1, "10", day="2026-10-18", name="Mouse"),
    ]}, CTX)

    resp = api.lambda_handler(_api_event("/analytics/daily",
                                         {"from": "2026-10-17", "to": "2026-10-18"}), CTX)
    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert [d["date"] for d in body["days"]] == ["2026-10-17", "2026-10-18"]
    assert body["totals"] == {"orders": 3, "orderLines": 3, "unitsSold": 8, "revenue": 35}

    top = json.loads(api.lambda_handler(_api_event("/analytics/top-items", {"limit": "1"}),
                                        CTX)["body"])
    assert top["items"] == [{"itemId": "B", "productName": "Cable", "unitsSold": 5, "revenue": 5}]


@pytest.mark.parametrize("resource,params", [
    ("/analytics/daily", {"from": "bad"}),
    ("/analytics/daily", {"from": "2026-10-18", "to": "2026-10-01"}),
    ("/analytics/daily", {"from": "2026-01-01", "to": "2026-10-18"}),
    ("/analytics/top-items", {"limit": "0"}),
    ("/analytics/top-items", {"limit": "abc"}),
])
def test_api_rejects_bad_parameters(aws, resource, params):
    api = _load("analytics_api")
    assert api.lambda_handler(_api_event(resource, params), CTX)["statusCode"] == 400
