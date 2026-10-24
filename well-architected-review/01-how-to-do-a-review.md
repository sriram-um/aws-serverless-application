# How to do an AWS Well-Architected review — step by step

A practical guide to running an AWS Well-Architected review against a **real code repository**,
written while reviewing this project
([aws-serverless-application](https://github.com/sriram-um/aws-serverless-application): API Gateway,
Lambda, DynamoDB, Cognito, WAF, SAM). No prior review experience is assumed.

**Contents**

1. [What a Well-Architected review is](#1-what-a-well-architected-review-is)
2. [Words you will see](#2-words-you-will-see)
3. [Before you start](#3-before-you-start)
4. [Step by step in the AWS console](#4-step-by-step-in-the-aws-console)
5. [The same steps with the AWS CLI](#5-the-same-steps-with-the-aws-cli)
6. [How to answer from code, not from memory](#6-how-to-answer-from-code-not-from-memory)
7. [After the review: from findings to pull requests](#7-after-the-review-from-findings-to-pull-requests)
8. [Pitfalls](#8-pitfalls)
9. [Checklist](#9-checklist)

---

## 1. What a Well-Architected review is

The **AWS Well-Architected Framework** is AWS's collection of best practices for building systems
in the cloud. It is written as a set of **questions** — for example *"How do you manage permissions
for people and machines?"* — each with a list of **best practices** you either follow or don't.

A **review** means going through those questions for one system and answering honestly. The
result is a list of **risks**: places where the system does not yet follow a best practice, ranked
by how much that matters.

The **AWS Well-Architected Tool** is a free page in the AWS console where you record the review:
it shows you the questions, stores your answers, calculates the risks, and produces a PDF report and
an improvement plan. It does **not** scan your account or your code — the answers come from you.
That is why this guide spends a lot of time on *how to find the right answer* (section 6).

The questions are grouped into **six pillars**:

| Pillar | Asks about | Example question |
|---|---|---|
| **Operational Excellence** (OPS) | Running and improving the system: deployments, monitoring, runbooks | How do you mitigate deployment risks? |
| **Security** (SEC) | Identities, permissions, data protection, detecting incidents | How do you manage permissions for people and machines? |
| **Reliability** (REL) | Surviving failures, backups, scaling, recovery | How do you back up data? |
| **Performance Efficiency** (PERF) | Choosing and sizing the right resources | How do you select and use compute resources? |
| **Cost Optimization** (COST) | Knowing and controlling what you spend | How do you monitor your cost and usage? |
| **Sustainability** (SUS) | Using no more resources (and energy) than needed | How do you align cloud resources to your demand? |

> Question numbers (e.g. *SEC 3*) and wording change slightly between Framework versions. Always use
> what the tool shows you; the IDs used by the CLI come from `list-answers` (section 5).

## 2. Words you will see

| Term | Meaning |
|---|---|
| **Workload** | The system you review — here: the Orders application (one SAM stack + CI/CD). One workload per review. |
| **Lens** | A set of questions. The **Well-Architected Framework** lens (the "core" lens) is always included; extra lenses add questions for a technology or industry. |
| **Serverless Lens** | AWS's extra lens for Lambda / API Gateway / DynamoDB / SQS / Step Functions architectures. Adds serverless-specific checks (concurrency, cold starts, async failure handling, …). |
| **Choice** | One best practice under a question. You tick the ones you actually do. Each question also has **"None of these"**. |
| **HRI** — high risk issue | A question where important best practices are missing. Fix these first. |
| **MRI** — medium risk issue | A question where some best practices are missing. |
| **Not applicable** | A question that doesn't apply to this workload. You must give a reason. |
| **Milestone** | A frozen, numbered snapshot of the whole review (all answers and risk counts) at a point in time — e.g. *baseline* before fixes and *after-fixes* later. Lets you show progress. |
| **Improvement plan** | The tool's list of missing best practices, ordered by risk, with links to AWS guidance. |

## 3. Before you start

### 3.1 Define the scope
Write down, in one or two sentences, what is in and out of the review. For this project:

> *In scope:* the `orders-serverless-app` stack defined in [`template.yaml`](../template.yaml)
> (API Gateway, Lambda, DynamoDB global table, Cognito, WAF, DAX option, analytics stream), its CI/CD
> ([`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml),
> [`infra/github-oidc.yaml`](../infra/github-oidc.yaml)) and the scripts in [`scripts/`](../scripts/).
> *Also in scope:* the security and cost settings of the AWS account it runs in (root user,
> CloudTrail, GuardDuty, budgets), because several questions are about them.
> *Out of scope:* other projects in the same account.

A review without a clear scope turns into a review of "everything", and most answers become "it
depends".

### 3.2 Gather the evidence
The tool asks questions; the answers are in your repository and your measurements. Collect:

| Evidence | Where it is in this repo | Answers questions about |
|---|---|---|
| Infrastructure as code | [`template.yaml`](../template.yaml) | IAM, encryption, backups, scaling, logging, networking |
| Function code | [`src/`](../src/) | Input validation, error handling, idempotency, logging/tracing |
| Tests | [`tests/`](../tests/) | Quality gates, change safety |
| CI/CD | [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), [`infra/github-oidc.yaml`](../infra/github-oidc.yaml) | Deployment risk, credentials, automation |
| Measurements | [`README.md` — Observations](../README.md#observations-and-lessons-learned) | Performance, sizing, latency, cold starts |
| Cost model | [`docs/cost-estimate.md`](../docs/cost-estimate.md) | Cost awareness, pricing model choices |
| Runbooks / scripts | [`scripts/teardown.sh`](../scripts/teardown.sh), [`scripts/rebuild.sh`](../scripts/rebuild.sh), [`scripts/smoke_test.sh`](../scripts/smoke_test.sh) | Recovery, repeatability, operations |
| The AWS account itself (read-only CLI checks) | Root user MFA and access keys, CloudTrail, GuardDuty, Access Analyzer, Security Hub, Config, budgets | Account security, detection, cost monitoring |

If you can't point to evidence for a best practice, the honest answer is that you don't do it.

### 3.3 Decide who answers
In a company, a review is a meeting: the people who build and run the system answer, a reviewer
(often an AWS Solutions Architect or a senior engineer) challenges the answers. For a personal
project, you play both roles: answer, then re-read each answer and ask *"where is the proof?"*.

### 3.4 Cost and access
- The Well-Architected Tool is **free**. Creating a workload creates no AWS resources.
- The system you review does **not** need to be running — the review is about its design. (This
  project was torn down when it was reviewed; the template and README still describe it.)
- You need IAM permissions for `wellarchitected:*` in the account (an admin user has them).
- Workloads are **regional** — create and find them in the same region (here `us-east-1`).

## 4. Step by step in the AWS console

Console: **AWS Well-Architected Tool** →
<https://us-east-1.console.aws.amazon.com/wellarchitected/home?region=us-east-1>

### Step 1 — Define the workload
1. **Workloads → Define workload.**
2. Fill in the properties:
   - **Name:** `aws-serverless-application`
   - **Description:** what the system does, plus the repo URL.
   - **Review owner:** your name/email.
   - **Environment:** *Production* or *Pre-production* (this project: *Pre-production* — a portfolio
     system, no real customers).
   - **Regions:** the regions it runs in (`us-east-1`, `us-west-2` for the DR replica).
   - Optional: architectural design link (the repo), industry, account IDs.
3. **Next → Apply profile** — skip (profiles prioritise questions for a business goal; optional).
4. **Lenses:** keep **AWS Well-Architected Framework** and add **Serverless Lens**.
5. **Define workload.**

### Step 2 — Start the review
Open the workload → **Start reviewing** → choose a lens (start with the Framework). The left
panel lists the pillars and their questions.

### Step 3 — Answer every question
For each question:
1. Read the question and the **Info** panel (it explains each best practice).
2. Tick the choices you **can prove** from your evidence (section 6). Tick **None of these** if
   none apply.
3. If the question doesn't apply, tick **Question does not apply to this workload** and give a
   reason (e.g. *"No EC2 instances — fully serverless"*).
4. Write **Notes** with the evidence: file and line, measurement, or why a practice is missing.
   Notes are what make the review useful later — and they appear in the PDF report.
5. **Save and continue.**

Repeat for the Serverless Lens. Expect roughly 1–3 hours for the Framework lens the first time.

### Step 4 — Read the results
- **Overview tab:** risk counts per pillar (high / medium / none / not applicable / unanswered).
- **Improvement plan tab:** the missing best practices, highest risk first, each with an AWS
  guidance link. This is your to-do list.

### Step 5 — Save a milestone
**Save milestone** → name it e.g. `v1.0-baseline`. A milestone can't be edited afterwards — it's
your "before" picture.

### Step 6 — Generate the report
**Generate report** on the lens page downloads a PDF of the answers, notes, risks and improvement
plan — the artifact you share with others.

### Step 7 — Fix, update, save a new milestone
After fixing issues (section 7), update the affected answers and save a second milestone, e.g.
`v1.1-after-fixes`. The **Milestones** tab compares risk counts between them.

## 5. The same steps with the AWS CLI

Everything in the console can be scripted with `aws wellarchitected`. That makes the review
**repeatable**: answers live in a file in the repository, next to the code they describe, and get
reviewed in pull requests like any other change.

> On this machine every command needs `--profile default` (the shell's default profile points to a
> different account) and `--region us-east-1`. Shown once here, omitted below:
> `export AWS_PROFILE=default AWS_REGION=us-east-1`

**List the available lenses** (find the Serverless Lens alias):
```bash
aws wellarchitected list-lenses \
  --query 'LensSummaries[].[LensAlias,LensName,LensVersion]' --output table
```

**Define the workload** (`--review-owner` and a region are required in practice, even though the
docs list them as optional):
```bash
aws wellarchitected create-workload \
  --workload-name aws-serverless-application \
  --description "Serverless Orders API (SAM). Repo: https://github.com/sriram-um/aws-serverless-application" \
  --environment PREPRODUCTION \
  --aws-regions us-east-1 us-west-2 \
  --review-owner "Sriram Penumatcha" \
  --architectural-design https://github.com/sriram-um/aws-serverless-application \
  --lenses wellarchitected serverless
# -> {"WorkloadId": "...", "WorkloadArn": "..."}
WORKLOAD_ID=<WorkloadId from the output>
```

> ⚠️ **The list commands return only 10 items unless told otherwise**, and the CLI does *not*
> page through the rest automatically for this service: a plain `list-answers` silently shows 10
> of 57 questions. Always ask for one pillar at a time with `--max-results 50` (no pillar has more
> than 13 questions), or follow `NextToken` yourself.

**List the questions** of a lens, pillar by pillar (IDs are needed to answer them):
```bash
for p in operationalExcellence security reliability performance costOptimization sustainability; do
  aws wellarchitected list-answers --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
    --pillar-id $p --max-results 50 \
    --query 'AnswerSummaries[].[PillarId,QuestionId,QuestionTitle]' --output text
done
```

**See the choices of one question:**
```bash
aws wellarchitected get-answer --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
  --question-id <QuestionId> \
  --query 'Answer.Choices[].[ChoiceId,Title]' --output table
```

**Answer a question** (selected choices + evidence in the notes):
```bash
aws wellarchitected update-answer --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
  --question-id <QuestionId> \
  --selected-choices <ChoiceId1> <ChoiceId2> \
  --notes "Per-function SAM policy templates scoped to one table: template.yaml#L113-L116"
```
Mark a whole question not applicable: `--no-is-applicable --reason OUT_OF_SCOPE --notes "..."`.

Mark single **choices** not applicable (e.g. "VPN to on-premises" in a serverless app). Use
`--choice-updates` instead of `--selected-choices`:
```bash
aws wellarchitected update-answer --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
  --question-id planning-network-topology \
  --choice-updates '{
    "rel_planning_network_topology_ha_conn_users": {"Status": "SELECTED"},
    "rel_planning_network_topology_ha_conn_private_networks": {"Status": "NOT_APPLICABLE",
      "Reason": "ARCHITECTURE_CONSTRAINTS", "Notes": "No on-premises network"}
  }'
```
This matters: the tool counts an unticked choice as *missing*. In this review, one question came
back **high risk** only because of three choices that can't exist in this architecture. With them
marked not applicable (and the reason written down), the same question had **no risk**.

**Risk counts** for a lens:
```bash
aws wellarchitected get-lens-review --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
  --query 'LensReview.{total:RiskCounts, pillars:PillarReviewSummaries[].[PillarName,RiskCounts]}'
```

**List the high risk issues** (per pillar, see the warning above):
```bash
for p in operationalExcellence security reliability performance costOptimization sustainability; do
  aws wellarchitected list-answers --workload-id "$WORKLOAD_ID" --lens-alias wellarchitected \
    --pillar-id $p --max-results 50 \
    --query 'AnswerSummaries[?Risk==`HIGH`].[PillarId,QuestionTitle]' --output text
done
```

**Improvement plan** (high and medium risks, each with a link to AWS guidance):
```bash
aws wellarchitected list-lens-review-improvements --workload-id "$WORKLOAD_ID" \
  --lens-alias wellarchitected --max-results 100 \
  --query 'ImprovementSummaries[].[Risk,PillarId,QuestionTitle,ImprovementPlanUrl]' --output text
```

**Save a milestone:**
```bash
aws wellarchitected create-milestone --workload-id "$WORKLOAD_ID" --milestone-name v1.0-baseline
```

**Download the PDF report** (the API returns it base64-encoded):
```bash
aws wellarchitected get-lens-review-report --workload-id "$WORKLOAD_ID" \
  --lens-alias wellarchitected \
  --query 'LensReviewReport.Base64String' --output text \
  | tr -d '[:space:]' | base64 -d > baseline-wellarchitected.pdf
```
(`tr` removes the line ending the CLI adds on Windows; without it `base64` fails with
*invalid input*.)

**Compare with a milestone later:** add `--milestone-number 1` to `get-lens-review`.

In this project these calls are wrapped in [`scripts/wa_review.py`](scripts/wa_review.py), which
reads the answers from [`answers/`](answers/) — see the [README](README.md).

## 6. How to answer from code, not from memory

The tool can only be as accurate as your answers. The method that works:

1. **Read the best practice, not just the question.** Open the Info panel / the linked AWS page:
   each choice describes a concrete practice ("Grant least privilege access").
2. **Find the proof** in the evidence from 3.2. Write down file + line or the measured number.
3. **Tick only what you can prove** for *this* workload. "We'd do that in production" is not done.
4. **Write the gap in the notes** when you don't tick something — that becomes the fix.
5. **Re-read as a reviewer:** for each ticked choice, ask "if someone asked for proof, could I show
   it in under a minute?"

### Worked example — Security: *How do you manage permissions for people and machines?*

| Best practice (choice) | Evidence in this repo | Tick? |
|---|---|---|
| Grant least privilege access | Each Lambda gets a SAM policy template scoped to one table, e.g. `DynamoDBWritePolicy` on the Orders table only ([`template.yaml`](../template.yaml#L113-L116)); API Gateway's direct integration role allows only `dynamodb:Query` on one table ([`template.yaml`](../template.yaml#L708-L731)) | ✅ |
| Define permission guardrails for your organization | No SCPs / permission boundaries — single account, out of scope | ❌ note it |
| Manage access based on lifecycle | Test users created by a script, deleted on teardown; no review process | partly → ❌, note it |
| Analyze public and cross-account access | Can't be proven from the repo — needs an account-level check | ❌ until proven, note it |
| *(related evidence)* Machines use temporary credentials | CI/CD uses a GitHub OIDC role restricted to this repo's `main` branch — no stored access keys ([`infra/github-oidc.yaml`](../infra/github-oidc.yaml)) | supports the ✅ choices above |

The result is honest: some good practices proven, some gaps with a written reason — and those
gaps are now concrete tasks.

### A quick map: which file answers which kind of question

| Topic | Look here |
|---|---|
| Compute sizing, architecture (arm64/x86), timeouts | `Globals` and per-function `MemorySize` in [`template.yaml`](../template.yaml#L33-L51); Power Tuning results in the [README](../README.md#lambda-optimization-measure-then-change-exercise-8) |
| Log retention, tracing | `AWS::Logs::LogGroup` resources, `Tracing: Active` |
| Monitoring and alerting | Dashboards (`AWS::CloudWatch::Dashboard`) vs. **alarms** (`AWS::CloudWatch::Alarm`) — a dashboard nobody watches is not alerting |
| Failure handling for async/stream work | Event source mapping settings: retries, bisect, `DestinationConfig` / DLQ ([`template.yaml`](../template.yaml#L635-L656)) |
| Backup and DR | `PointInTimeRecoveryEnabled`, global table replicas, rebuild scripts |
| Throttling / protecting from demand spikes | API Gateway `MethodSettings` throttling, WAF rules, Lambda reserved concurrency |
| Data protection | `SSESpecification`, TLS-only endpoints, token handling in code |
| Deployment safety | CI workflow: tests, lint, smoke test; aliases/canary (`DeploymentPreference`) |
| Cost awareness | Cost estimate doc, budgets/alerts, tags, on/off toggles for hourly resources |

## 7. After the review: from findings to pull requests

1. **Prioritise:** all HRIs first, then MRIs that are cheap to fix. Use your pillar priorities —
   for a personal project, *cost* and *security* usually come first.
2. **One issue → one small change.** Write the fix in the IaC/code, open a pull request, reference
   the question in the title (e.g. *"REL: add CloudWatch alarms on Lambda errors and DLQ depth"*).
3. **Verify the fix** the same way as any change (tests, deploy, check it in the console).
4. **Update the answer** in the tool (or in the answers file) with the new evidence.
5. **Save a new milestone** and compare risk counts with the baseline.
6. **Repeat regularly** — at least yearly, or after a big architecture change.

Not every risk must be fixed. Accepting a risk is a valid decision if it is written down with the
reason (e.g. *"single-node DAX: demo only, never production"*).

## 8. Pitfalls

| Pitfall | Why it's a problem | Do this instead |
|---|---|---|
| Answering from a generic checklist or a blog post | It guesses problems you may not have (e.g. "you probably use x86 and 128 MB") and misses the ones you do | Check every claim against the code before writing it down |
| Ticking choices to make the HRI count go down | The report looks good, the system isn't better — and a reviewer will ask for proof | Tick only what you can show; record gaps |
| Treating the tool as a scanner | It never looks at your account or code | The evidence step (3.2) is the real work |
| Confusing a dashboard with alerting | Dashboards need someone looking at them | Alarms with a notification target |
| Copying fixes that don't apply | e.g. `EventInvokeConfig` only affects **asynchronous** invocations; API Gateway calls are synchronous and stream triggers use event source mapping settings | Understand how each function is invoked first |
| Wrong lens alias in the CLI | `--lens-alias wellarchitected` only covers the Framework lens | Run commands per lens; get aliases from `list-lenses` |
| Wrong region/account | Workloads are regional; this machine has two AWS profiles | Pin `--region` and `--profile`; check `aws sts get-caller-identity` |
| Leaving impossible choices unticked | The tool reads them as missing best practices and inflates the risk (e.g. "load balancing" in an API Gateway app) | Mark the *choice* not applicable with a reason; never tick it as done |
| Marking real gaps "not applicable" to lower the count | Hides real risk — "we don't have a budget" is a gap, not N/A | N/A only when the thing can't exist in this architecture |
| Trusting a plain `list-answers` | Returns 10 items by default and the CLI doesn't auto-page this service — 47 of 57 questions silently missing | `--pillar-id` + `--max-results 50`; in boto3 follow `NextToken` by hand (there are **no paginators** for `wellarchitected`) — see `scripts/wa_review.py` |
| Reviewing only the repo | Questions about account security (root user, CloudTrail, GuardDuty, budgets) can't be answered from code | Run read-only checks: `aws iam get-account-summary`, `cloudtrail describe-trails`, `guardduty list-detectors`, `budgets describe-budgets` |
| One giant review session | Fatigue → "None of these" everywhere | One pillar at a time; save as you go |

## 9. Checklist

- [ ] Scope written down (3.1)
- [ ] Evidence collected, with file paths (3.2)
- [ ] Workload defined with the Framework lens + Serverless Lens
- [ ] Every question answered or marked not applicable with a reason
- [ ] Notes contain evidence for every ticked choice and the gap for every unticked one
- [ ] Baseline milestone saved; PDF reports downloaded
- [ ] HRIs turned into a prioritised improvement plan
- [ ] Fixes delivered as small pull requests, answers updated, new milestone saved

---

**Further reading:**
[AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/framework/welcome.html) ·
[Serverless Applications Lens](https://docs.aws.amazon.com/wellarchitected/latest/serverless-applications-lens/welcome.html) ·
[Well-Architected Tool user guide](https://docs.aws.amazon.com/wellarchitected/latest/userguide/intro.html) ·
[AWS CLI `wellarchitected` reference](https://docs.aws.amazon.com/cli/latest/reference/wellarchitected/)

Next: [the results of reviewing this repository](02-review-results.md).
