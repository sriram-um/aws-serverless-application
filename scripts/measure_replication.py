"""Measure DynamoDB Global Table replication lag (primary -> replica).

Writes a probe item in the primary region and polls the replica with a warm boto3 client
(~20 ms between reads) until it appears. Probe items use orderId "replication-probe" (ignored
by the analytics aggregator) and are deleted afterwards.

Usage: python scripts/measure_replication.py [--table T] [--primary R] [--replica R] [-n N]
"""
import argparse
import statistics
import time
import uuid

import boto3


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--table", default="orders-serverless-app-OrdersGlobal")
    parser.add_argument("--primary", default="us-east-1")
    parser.add_argument("--replica", default="us-west-2")
    parser.add_argument("--profile", default="default")
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()

    session = boto3.Session(profile_name=args.profile)
    primary = session.client("dynamodb", region_name=args.primary)
    replica = session.client("dynamodb", region_name=args.replica)
    # Warm up both connections so TLS setup is not counted
    primary.describe_table(TableName=args.table)
    replica.describe_table(TableName=args.table)

    lags = []
    print(f"{'sample':>6} {'lag_ms':>8} {'polls':>6}")
    for i in range(1, args.n + 1):
        key = {"orderId": {"S": "replication-probe"}, "itemId": {"S": f"probe-{uuid.uuid4()}"}}
        primary.put_item(TableName=args.table, Item={**key, "productName": {"S": "replication-probe"}})
        acked = time.perf_counter()
        polls = 0
        while True:
            polls += 1
            if "Item" in replica.get_item(TableName=args.table, Key=key):
                break
            time.sleep(0.02)
        lag_ms = (time.perf_counter() - acked) * 1000
        lags.append(lag_ms)
        print(f"{i:>6} {lag_ms:>8.0f} {polls:>6}")
        primary.delete_item(TableName=args.table, Key=key)
        time.sleep(0.5)

    print(f"replication {args.primary} -> {args.replica}: median {statistics.median(lags):.0f} ms, "
          f"min {min(lags):.0f}, max {max(lags):.0f}, n={len(lags)} "
          f"(poll interval ~20 ms + one cross-region GetItem round trip)")


if __name__ == "__main__":
    main()
