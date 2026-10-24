"""Run the Well-Architected review of this repo "as code" (AWS Well-Architected Tool, free).

    .venv/Scripts/python well-architected-review/scripts/wa_review.py <command>

Commands (all idempotent):
    questions          create the workload if needed; write every question + choice of each lens to
                       answers/questions-<lens>.json (reference used to fill in the answers)
    apply              push answers/<lens>.json to the tool (selected choices, notes, not-applicable)
    status             risk counts per pillar and the list of high risk issues, per lens
    milestone <name>   save a milestone (skipped if one with that name exists)
    report <prefix>    download the official PDF report of each lens to reports/<prefix>-<lens>.pdf
                       and the per-question risks to reports/<prefix>-risks.json
                       (add --milestone N to report on a saved milestone)

answers/<lens>.json format:
    {"questions": {"<QuestionId>": {"title": "...", "selected": ["<ChoiceId>", ...],
                                    "notes": "evidence ...", "not_applicable": "OUT_OF_SCOPE",
                                    "not_applicable_choices": {"<ChoiceId>": "why it can't apply"}}}}
"""
import argparse
import base64
import json
import sys
from pathlib import Path

import boto3

sys.stdout.reconfigure(encoding="utf-8")

REVIEW_DIR = Path(__file__).resolve().parent.parent
ANSWERS_DIR = REVIEW_DIR / "answers"
REPORTS_DIR = REVIEW_DIR / "reports"

PROFILE = "default"  # the shell's AWS_PROFILE points at a different account
REGION = "us-east-1"
WORKLOAD_NAME = "aws-serverless-application"
REPO_URL = "https://github.com/sriram-um/aws-serverless-application"
LENSES = ["wellarchitected", "serverless"]
NOTES_MAX = 2084  # UpdateAnswer limit

wa = boto3.Session(profile_name=PROFILE, region_name=REGION).client("wellarchitected")


def list_all(method, key, **kwargs):
    """boto3 has no paginators for wellarchitected - follow NextToken by hand."""
    items, token = [], None
    while True:
        page = method(**kwargs, **({"NextToken": token} if token else {}))
        items.extend(page[key])
        token = page.get("NextToken")
        if not token:
            return items


def find_workload_id():
    for w in list_all(wa.list_workloads, "WorkloadSummaries", WorkloadNamePrefix=WORKLOAD_NAME):
        if w["WorkloadName"] == WORKLOAD_NAME:
            return w["WorkloadId"]
    return None


def ensure_workload():
    workload_id = find_workload_id()
    if workload_id:
        return workload_id
    workload_id = wa.create_workload(
        WorkloadName=WORKLOAD_NAME,
        Description=(
            "Serverless Orders API: API Gateway, Lambda (Python 3.12, arm64), DynamoDB global "
            f"table, Cognito, WAF, optional DAX; AWS SAM + GitHub Actions OIDC. Repo: {REPO_URL}"
        ),
        Environment="PREPRODUCTION",
        AwsRegions=["us-east-1", "us-west-2"],
        ReviewOwner="Sriram Penumatcha",
        ArchitecturalDesign=REPO_URL,
        Lenses=LENSES,
        Tags={"project": "serverless-orders"},
    )["WorkloadId"]
    print(f"created workload {WORKLOAD_NAME}: {workload_id}")
    return workload_id


def list_answers(workload_id, lens, milestone=None):
    kwargs = {"WorkloadId": workload_id, "LensAlias": lens}
    if milestone:
        kwargs["MilestoneNumber"] = milestone
    return list_all(wa.list_answers, "AnswerSummaries", **kwargs)


def cmd_questions(_args):
    workload_id = ensure_workload()
    ANSWERS_DIR.mkdir(exist_ok=True)
    for lens in LENSES:
        questions = []
        for summary in list_answers(workload_id, lens):
            answer = wa.get_answer(
                WorkloadId=workload_id, LensAlias=lens, QuestionId=summary["QuestionId"]
            )["Answer"]
            questions.append({
                "pillar": summary["PillarId"],
                "questionId": answer["QuestionId"],
                "title": answer["QuestionTitle"],
                "description": answer.get("QuestionDescription", ""),
                "choices": [
                    {"choiceId": c["ChoiceId"], "title": c["Title"],
                     "description": c.get("Description", "")}
                    for c in answer["Choices"]
                ],
            })
        out = ANSWERS_DIR / f"questions-{lens}.json"
        out.write_text(json.dumps(questions, indent=2, ensure_ascii=False) + "\n",
                       encoding="utf-8", newline="\n")
        print(f"{lens}: {len(questions)} questions -> {out.relative_to(REVIEW_DIR)}")


def all_choices(lens, question_id):
    questions = json.loads((ANSWERS_DIR / f"questions-{lens}.json").read_text(encoding="utf-8"))
    return {c["choiceId"] for q in questions if q["questionId"] == question_id for c in q["choices"]}


def cmd_apply(_args):
    workload_id = ensure_workload()
    for lens in LENSES:
        path = ANSWERS_DIR / f"{lens}.json"
        if not path.exists():
            print(f"{lens}: no {path.name}, skipped")
            continue
        questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
        for question_id, a in questions.items():
            notes = a.get("notes", "")
            if len(notes) > NOTES_MAX:
                sys.exit(f"{lens}/{question_id}: notes are {len(notes)} chars (max {NOTES_MAX})")
            kwargs = {"WorkloadId": workload_id, "LensAlias": lens,
                      "QuestionId": question_id, "Notes": notes}
            if a.get("not_applicable"):
                kwargs.update(IsApplicable=False, Reason=a["not_applicable"], SelectedChoices=[])
            else:
                # Every choice gets an explicit status, so removing one from the file unselects it
                na = a.get("not_applicable_choices", {})
                kwargs.update(IsApplicable=True, ChoiceUpdates={
                    c: {"Status": "SELECTED"} for c in a["selected"]
                } | {
                    c: {"Status": "NOT_APPLICABLE", "Reason": "ARCHITECTURE_CONSTRAINTS", "Notes": why}
                    for c, why in na.items()
                } | {
                    c: {"Status": "UNSELECTED"}
                    for c in all_choices(lens, question_id) - set(a["selected"]) - set(na)
                })
            risk = wa.update_answer(**kwargs)["Answer"].get("Risk")
            print(f"{lens:16} {question_id:40} {risk}")


def cmd_status(_args):
    workload_id = ensure_workload()
    for lens in LENSES:
        review = wa.get_lens_review(WorkloadId=workload_id, LensAlias=lens)["LensReview"]
        print(f"\n== {review['LensName']} ({lens})  total: {review.get('RiskCounts', {})}")
        for p in review.get("PillarReviewSummaries", []):
            print(f"   {p['PillarName']:28} {p.get('RiskCounts', {})}")
        high = [a for a in list_answers(workload_id, lens) if a.get("Risk") == "HIGH"]
        for a in high:
            print(f"   HRI  {a['PillarId']:22} {a['QuestionTitle']}")


def cmd_milestone(args):
    workload_id = ensure_workload()
    for m in list_all(wa.list_milestones, "MilestoneSummaries", WorkloadId=workload_id):
        if m["MilestoneName"] == args.name:
            print(f"milestone {args.name} already exists (#{m['MilestoneNumber']})")
            return
    number = wa.create_milestone(WorkloadId=workload_id, MilestoneName=args.name)["MilestoneNumber"]
    print(f"saved milestone {args.name} (#{number})")


def cmd_report(args):
    workload_id = ensure_workload()
    REPORTS_DIR.mkdir(exist_ok=True)
    risks = {}
    for lens in LENSES:
        kwargs = {"WorkloadId": workload_id, "LensAlias": lens}
        if args.milestone:
            kwargs["MilestoneNumber"] = args.milestone
        report = wa.get_lens_review_report(**kwargs)["LensReviewReport"]
        out = REPORTS_DIR / f"{args.prefix}-{lens}.pdf"
        out.write_bytes(base64.b64decode(report["Base64String"]))
        print(f"{lens}: {out.relative_to(REVIEW_DIR)} ({out.stat().st_size // 1024} KB)")
        risks[lens] = [
            {"pillar": a["PillarId"], "questionId": a["QuestionId"],
             "title": a["QuestionTitle"], "risk": a.get("Risk")}
            for a in list_answers(workload_id, lens, args.milestone)
        ]
    # Per-question risks: input for scripts/risk_chart.py and for diffing milestones
    out = REPORTS_DIR / f"{args.prefix}-risks.json"
    out.write_text(json.dumps(risks, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8", newline="\n")
    print(f"risks: {out.relative_to(REVIEW_DIR)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("questions").set_defaults(func=cmd_questions)
    sub.add_parser("apply").set_defaults(func=cmd_apply)
    sub.add_parser("status").set_defaults(func=cmd_status)
    p = sub.add_parser("milestone")
    p.add_argument("name")
    p.set_defaults(func=cmd_milestone)
    p = sub.add_parser("report")
    p.add_argument("prefix")
    p.add_argument("--milestone", type=int)
    p.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)
