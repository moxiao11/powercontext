#!/usr/bin/env python3
"""Assemble a self-contained Qoder Sites showcase with docs and real screenshots."""

import argparse
import html
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-url", default="")
    args = parser.parse_args()
    config_path = ROOT / "submission.local.json"
    config = (
        json.loads(config_path.read_text(encoding="utf-8-sig"))
        if config_path.exists()
        else {}
    )
    repository = args.repository_url or config.get("repository_url", "")
    if repository:
        parsed = urlparse(repository)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise SystemExit("Repository URL must be HTTPS and contain no credentials.")
    destination = ROOT / "dist/site"
    shutil.copytree(ROOT / "site", destination, dirs_exist_ok=True)
    shutil.copytree(ROOT / "docs", destination / "docs", dirs_exist_ok=True)
    shutil.copytree(
        ROOT / "sample-data", destination / "sample-data", dirs_exist_ok=True
    )
    links = '<div class="grid g2">'
    for name, label in [
        ("SUBMISSION", "比赛提交清单"),
        ("SETUP", "完整运行说明"),
        ("VERIFICATION", "本轮真实验证"),
        ("TECH_INTEGRATION", "指定技术集成"),
        ("QODER_DEVELOPMENT_LOG", "Qoder 记录状态"),
        ("QODER_SITES_PROMPT", "Qoder Sites 发布与更新"),
        ("CODEX_COMPLETION_LOG", "本轮工程补全"),
    ]:
        links += f'<a class="btn" href="docs/{name}.md">{label}（Markdown）</a>'
    links += '</div><p style="margin-top:18px">'
    if repository:
        links += f'<a class="btn primary" href="{html.escape(repository, quote=True)}" target="_blank" rel="noopener">完整代码仓库</a>'
    else:
        links += (
            '<span class="pill warn">比赛私有仓库 URL 待提供，尚未添加源码链接</span>'
        )
    links += "</p>"
    index = destination / "index.html"
    index.write_text(
        index.read_text(encoding="utf-8").replace("<!-- DELIVERABLE_LINKS -->", links),
        encoding="utf-8",
    )
    print(destination)
    print(
        "Preview only; publish this directory through your personal Qoder Sites account."
    )


if __name__ == "__main__":
    main()
