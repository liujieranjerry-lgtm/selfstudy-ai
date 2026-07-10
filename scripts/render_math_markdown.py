#!/Users/liujieran/.codex-python/bin/python
"""Render Markdown with LaTeX math to browser-friendly HTML."""

from __future__ import annotations

import argparse
import re
from html import escape
from pathlib import Path

import markdown
from latex2mathml.converter import convert


DISPLAY_MATH = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)
INLINE_MATH = re.compile(r"(?<!\\)\$(?!\$)(.+?)(?<!\\)\$(?!\$)")


def render_math(source: str) -> str:
    def display(match: re.Match[str]) -> str:
        latex = match.group(1).strip()
        mathml = convert(latex, display="block")
        return f'\n<div class="math-display">{mathml}</div>\n'

    source = DISPLAY_MATH.sub(display, source)

    def inline(match: re.Match[str]) -> str:
        latex = match.group(1).strip()
        mathml = convert(latex, display="inline")
        return f'<span class="math-inline">{mathml}</span>'

    return INLINE_MATH.sub(inline, source)


def render_document(source_path: Path, output_path: Path, stylesheet: str) -> None:
    source = source_path.read_text(encoding="utf-8")
    title_match = re.search(r"^#\s+(.+)$", source, re.MULTILINE)
    title = title_match.group(1) if title_match else source_path.stem
    source_with_math = render_math(source)
    body = markdown.markdown(
        source_with_math,
        extensions=["fenced_code", "tables", "toc", "md_in_html"],
        output_format="html5",
    )

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <link rel="stylesheet" href="{escape(stylesheet)}">
</head>
<body>
<main>
  <nav class="document-nav" aria-label="文档导航">
    <a href="01-从文本到token再到向量.md">上一篇 Markdown</a>
    <a href="02-从9个参数的小模型看懂算法与参数.md">查看源 Markdown</a>
  </nav>
{body}
</main>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--stylesheet", default="assets/lesson.css")
    args = parser.parse_args()
    render_document(args.source, args.output, args.stylesheet)


if __name__ == "__main__":
    main()
