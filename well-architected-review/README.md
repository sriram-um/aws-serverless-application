# Well-Architected review — aws-serverless-application

How to run an **AWS Well-Architected review** against a real repository, and what happened when
this one ([sriram-um/aws-serverless-application](https://github.com/sriram-um/aws-serverless-application))
was reviewed with the **Well-Architected Framework** lens and the **Serverless Lens**.

## Read in this order

| # | Document | What it is | Status |
|---|---|---|---|
| 1 | [How to do a review](01-how-to-do-a-review.md) | Step-by-step process guide: concepts, console, CLI, answering from code, pitfalls | ✅ |
| 2 | [Review results](02-review-results.md) | Risk counts, what's done well, gaps found, improvement plan | ✅ |

Every document exists as Markdown (for GitHub) and HTML (to open in a browser or share).

## Folder layout

| Path | Contents |
|---|---|
| `*.md` / `*.html` | The documents above (HTML is generated from Markdown) |
| [`answers/`](answers/) | The review answers as code: per question, the selected best practices and notes with evidence from the repo |
| [`scripts/wa_review.py`](scripts/wa_review.py) | Creates/updates the workload in the Well-Architected Tool from `answers/`, saves a milestone, prints risk counts, downloads the PDF reports |
| [`scripts/risk_chart.py`](scripts/risk_chart.py) | Draws the risk-per-pillar chart (`images/<milestone>-risks.png`) from `reports/<milestone>-risks.json` |
| [`scripts/build_html.py`](scripts/build_html.py) | Regenerates the HTML files from the Markdown |
| [`reports/`](reports/) | Risk counts and per-question risks of each milestone. The official PDF reports are written here too but are git-ignored: they include private account findings |
| [`images/`](images/) | Charts (and console screenshots) |

## Rebuild the chart and HTML

```bash
.venv/Scripts/python -m pip install markdown matplotlib   # once (docs only - not needed by CI)
.venv/Scripts/python well-architected-review/scripts/risk_chart.py baseline   # chart
.venv/Scripts/python well-architected-review/scripts/build_html.py           # HTML
```
