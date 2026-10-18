# Cost estimate (exercise 12)

Monthly cost of the architecture in `us-east-1` (+ the `us-west-2` replica) at a modest
production-like load. Prices are **on-demand list prices, retrieved from the AWS Price List API
on 2026-10-18** (marked ✓) or from the public pricing pages (marked ◦). The free tier is
**ignored** so the numbers show what the architecture costs once it is past it.

## Assumptions

| Driver | Value | Notes |
|---|---|---|
| Orders created (`POST /orders`) | 100,000 / month | 2 lines per order → 200,000 order-line items |
| Order reads | 1,000,000 / month | split evenly between `GET /orders/{id}` (Lambda) and `GET /direct/orders/{id}` |
| Analytics API calls | 10,000 / month | admins only |
| Item size | < 1 KB | 1 WRU per write; a 2-line order fits in one 4 KB read |
| Lambda | arm64, CreateOrder/GetOrder 512 MB, analytics 256 MB | durations from the measurements in the README (with headroom for cold starts) |
| Monthly active users | ≤ 10,000 | Cognito Lite tier |
| Traffic profile | ~0.4 requests/s average | low enough that X-Ray's 1 req/s reservoir samples most requests |

## Scenario A — caching off (the default)

| Service | Calculation | Monthly |
|---|---|---|
| **API Gateway** (REST) | 1.11 M requests × $3.50/M ✓ | **$3.89** |
| **Lambda** requests | 1.63 M invocations × $0.20/M ✓ | $0.33 |
| **Lambda** compute (arm) | CreateOrder 100 k × 0.5 GB × 20 ms = 1,000 GB‑s; GetOrder 500 k × 0.5 GB × 15 ms = 3,750 GB‑s; Aggregator ~20 k batches × 0.25 GB × 100 ms = 500 GB‑s; AnalyticsApi 10 k × 0.25 GB × 50 ms = 125 GB‑s → 5,375 GB‑s × $0.0000133334 ✓ | $0.07 |
| **DynamoDB** Orders writes | 200 k WRU × $0.625/M ✓ | $0.13 |
| **DynamoDB** replicated writes (us-west-2) | 200 k rWRU × $0.625/M ✓ | $0.13 |
| **DynamoDB** OrderStats writes | per line: 1 transaction of 3 writes = 6 WRU (transactions cost 2×); per order: 1 transaction of 2 writes = 4 WRU → 1.6 M WRU × $0.625/M ✓ | $1.00 |
| **DynamoDB** reads | 1 M order queries × 0.5 RRU (eventually consistent) + ~60 k RRU analytics → 0.56 M RRU × $0.125/M ✓ | $0.07 |
| **DynamoDB** Streams | read by Lambda triggers — no charge ◦ | $0.00 |
| **DynamoDB** storage + PITR, 2 regions | ~50 MB growth/month × ($0.25 ✓ + $0.20 ✓ PITR) × 2 | < $0.05 |
| **AWS WAF** | $5 web ACL + $1 rule + 1.11 M × $0.60/M ◦ | **$6.67** |
| **Cognito** | Lite tier, ≤ 10 k MAU free ◦ | $0.00 |
| **CloudWatch** dashboard | 1 × $3 ◦ | **$3.00** |
| **CloudWatch** API Gateway detailed metrics | `MetricsEnabled` per method = custom metrics: ~7 metrics × 5 methods × $0.30 ◦ | **$10.50** |
| **CloudWatch** Logs | ~1 KB JSON log per invocation → ~1.6 GB × $0.50/GB ◦ | $0.80 |
| **X-Ray** / Transaction Search | most of ~1.1 M requests sampled (1 req/s reservoir); ~$5 per million traces ◦ — depends on sampling and on Transaction Search span ingestion | ~$5.00 |
| SQS dead-letter queue, KMS (AWS-managed keys) | negligible | < $0.10 |
| **Total** | | **≈ $31.70 / month** |

**What drives the bill:** usage-based charges (API Gateway, Lambda, DynamoDB) add up to only
**~$5.70**. The rest is fixed or semi-fixed: WAF ($6.67), the dashboard ($3), **API Gateway
detailed metrics ($10.50)** and tracing (~$5).

**Cheapest improvements:**

1. Turn off per-method `MetricsEnabled` unless per-route metrics are needed → **−$10.50**. The
   dashboard uses the free stage-level metrics.
2. Add an X-Ray sampling rule, for example 1 % of traffic after the reservoir → most of the
   tracing cost goes away.
3. The analytics write amplification (6 WRU per order line, for the exactly-once transaction) is
   the biggest DynamoDB line. It is still only $1 per 100 k orders.

## Scenario B — caching on (`EnableCaching=true`)

Adds hourly-billed infrastructure (730 h/month):

| Service | Calculation | Monthly |
|---|---|---|
| DAX | 1 × `dax.t3.small` × $0.040/h ✓ (production: 3 nodes for multi-AZ → $87.60) | $29.20 |
| API Gateway cache | 0.5 GB × $0.020/h ✓ | $14.60 |
| X-Ray interface VPC endpoint | 2 AZs × $0.01/h ◦ (+ $0.01/GB) | $14.60 |
| *Savings* | fewer GetOrder invocations and DynamoDB reads on cache hits | ≈ −$0.30 |
| **Total** | Scenario A + **≈ $58** | **≈ $90 / month** |

**Verdict:** at this load caching roughly **triples** the bill and saves well under a dollar.
DynamoDB already answers in ~4.5 ms, against ~2.6 ms for DAX. Caching starts to pay off with:

- read volumes in the tens of millions per month, or
- hot keys that would otherwise need provisioned capacity, or
- a latency target below what DynamoDB delivers.

That is why it sits behind a switch.

## What this project actually cost to build

Charges came from about 24 hours of development: WAF and the dashboard prorated, about 21 minutes
of DAX, the API cache and the interface endpoint, a few thousand test requests, and two Power
Tuning runs. See the README's teardown section for the Cost Explorer figure, which lags by up to
24 hours.

## Reproducing this in the AWS Pricing Calculator

Create an estimate at <https://calculator.aws/#/estimate> with these entries. All are in
US East (N. Virginia) except the DynamoDB replica:

- **API Gateway** — REST API, 1.11 million requests/month (+ cache 0.5 GB for scenario B).
- **Lambda** (arm) — 4 functions as in the table above (requests, duration, memory).
- **DynamoDB** on-demand — Orders: 200 k writes, 1 M eventually consistent reads; OrderStats:
  1.6 M write request units, 60 k reads; replica in US West (Oregon): 200 k replicated writes.
- **AWS WAF** — 1 web ACL, 1 rule, 1.11 million requests.
- **CloudWatch** — 1 dashboard, 35 custom metrics, 1.6 GB logs ingested.
- **X-Ray** — ~1 million traces recorded.
- Scenario B: **DAX** 1 × dax.t3.small, **VPC** 1 interface endpoint × 2 AZs.

The calculator needs an interactive session to save and share an estimate, so no shared link
was generated during the unattended part of the build.
