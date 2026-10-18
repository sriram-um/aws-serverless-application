import importlib
import json
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

SRC = Path(__file__).resolve().parents[2] / "src" / "get_order"
TABLE = "test-orders"


@dataclass
class FakeLambdaContext:
    function_name: str = "GetOrder"
    memory_limit_in_mb: int = 256
    invoked_function_arn: str = "arn:aws:lambda:us-east-1:123456789012:function:GetOrder"
    aws_request_id: str = "test-request-id"


CTX = FakeLambdaContext()


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("TABLE_NAME", TABLE)
    monkeypatch.delenv("DAX_ENDPOINT", raising=False)
    monkeypatch.setenv("POWERTOOLS_TRACE_DISABLED", "true")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName=TABLE,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "orderId", "AttributeType": "S"},
                {"AttributeName": "itemId", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "orderId", "KeyType": "HASH"},
                {"AttributeName": "itemId", "KeyType": "RANGE"},
            ],
        )
        table = boto3.resource("dynamodb").Table(TABLE)
        for item_id, qty, price in (("A", 2, "10.5"), ("B", 1, "4")):
            table.put_item(Item={"orderId": "o-1", "itemId": item_id, "customerId": "user-1",
                                 "productName": item_id, "quantity": qty,
                                 "unitPrice": Decimal(price), "status": "CREATED"})
        sys.modules.pop("app", None)
        sys.path.insert(0, str(SRC))
        module = importlib.import_module("app")
        yield module
        sys.path.remove(str(SRC))
        sys.modules.pop("app", None)


def _event(order_id, sub):
    return {"pathParameters": {"orderId": order_id},
            "requestContext": {"authorizer": {"claims": {"sub": sub}}}}


def test_owner_gets_order(app):
    resp = app.lambda_handler(_event("o-1", "user-1"), CTX)
    assert resp["statusCode"] == 200
    assert resp["headers"]["X-Read-Backend"] == "dynamodb"
    body = json.loads(resp["body"])
    assert body["itemCount"] == 2
    assert {i["itemId"]: i["unitPrice"] for i in body["items"]} == {"A": 10.5, "B": 4}


def test_other_user_gets_404(app):
    resp = app.lambda_handler(_event("o-1", "user-2"), CTX)
    assert resp["statusCode"] == 404


def test_unknown_order_404(app):
    assert app.lambda_handler(_event("nope", "user-1"), CTX)["statusCode"] == 404


def test_missing_order_id_400(app):
    assert app.lambda_handler({"pathParameters": None}, CTX)["statusCode"] == 400
