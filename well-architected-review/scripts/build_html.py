"""Render the review's Markdown files to self-contained HTML (inline CSS, no external assets).

    .venv/Scripts/python well-architected-review/scripts/build_html.py

README.md becomes index.html. Links to other .md files in the folder are rewritten to .html;
links to repository files (../...) point to GitHub so the HTML works when shared on its own.
"""
import html
import re
import sys
from pathlib import Path

import markdown

sys.stdout.reconfigure(encoding="utf-8")

REVIEW_DIR = Path(__file__).resolve().parent.parent
REPO_URL = "https://github.com/sriram-um/aws-serverless-application"
REVIEW_URL = f"{REPO_URL}/blob/main/well-architected-review"

CSS = """
body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       line-height: 1.6; color: #1f2328; max-width: 980px; margin: 0 auto; padding: 2rem 1.5rem; }
h1, h2, h3 { line-height: 1.25; }
h1 { border-bottom: 2px solid #ff9900; padding-bottom: .3em; }
h2 { border-bottom: 1px solid #d0d7de; padding-bottom: .3em; margin-top: 2em; }
a { color: #0969da; text-decoration: none; } a:hover { text-decoration: underline; }
code { background: #f3f4f6; padding: .1em .35em; border-radius: 4px; font-size: 90%; }
pre { background: #161b22; color: #e6edf3; padding: 1em; border-radius: 6px; overflow-x: auto; }
pre code { background: none; padding: 0; color: inherit; }
table { border-collapse: collapse; width: 100%; margin: 1em 0; display: block; overflow-x: auto; }
th, td { border: 1px solid #d0d7de; padding: .45em .7em; vertical-align: top; text-align: left; }
th { background: #f6f8fa; }
tr:nth-child(even) td { background: #fafbfc; }
blockquote { margin: 1em 0; padding: .5em 1em; border-left: 4px solid #ff9900; background: #fff8ec; }
blockquote p { margin: .3em 0; }
img { max-width: 100%; border: 1px solid #d0d7de; border-radius: 4px; }
footer { margin-top: 3em; font-size: 85%; color: #656d76; border-top: 1px solid #d0d7de; padding-top: 1em; }
"""


def rewrite_link(target: str) -> str:
    if re.match(r"^[a-z]+:|^#", target):
        return target
    if target.startswith("../"):
        return f"{REPO_URL}/blob/main/{target[3:]}"
    path, _, anchor = target.partition("#")
    if path.endswith(".md"):
        path = "index.html" if path == "README.md" else path[:-3] + ".html"
    elif not path.endswith((".html", ".png", ".jpg", ".svg", ".pdf")):
        # scripts/answers: link to GitHub so the files render (a local .py/.json opens as raw text)
        path = f"{REVIEW_URL}/{path}"
    return path + (f"#{anchor}" if anchor else "")


def render(md_file: Path) -> Path:
    text = md_file.read_text(encoding="utf-8")
    text = text.replace("- [ ] ", "- ☐ ").replace("- [x] ", "- ☑ ")
    text = re.sub(r"\]\(([^)\s]+)\)", lambda m: f"]({rewrite_link(m.group(1))})", text)
    body = markdown.markdown(text, extensions=["tables", "fenced_code", "toc", "sane_lists"])
    title_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = html.escape(title_match.group(1) if title_match else md_file.stem)
    out = md_file.with_name("index.html" if md_file.name == "README.md" else md_file.stem + ".html")
    out.write_text(
        f"<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
        f"<title>{title}</title>\n<style>{CSS}</style>\n</head>\n<body>\n{body}\n"
        f"<footer>Generated from <a href=\"{REVIEW_URL}/{md_file.name}\">{md_file.name}</a> · "
        f"<a href=\"{REPO_URL}\">sriram-um/aws-serverless-application</a></footer>\n"
        f"</body>\n</html>\n",
        encoding="utf-8",
    )
    return out


if __name__ == "__main__":
    for md in sorted(REVIEW_DIR.glob("*.md")):
        if md.name == "post.md":
            continue  # the post is meant to be copied into LinkedIn, not published as a page
        print(f"{md.name} -> {render(md).name}")
