"""Markdown 转 PDF 工具。

把报告的 Markdown 源文件转成 HTML，再用本机 Chrome 的无头模式打印成 PDF。

之所以自带一个精简的 Markdown 转换器而不依赖第三方库：
本项目要求只用 Python 标准库即可运行，报告生成同样不引入额外依赖。

用法::

    python tools/md2pdf.py --input 实验报告.md --output 实验报告.pdf

支持的 Markdown 语法：ATX 标题、无序与有序列表、表格、围栏代码块、
行内代码、粗体、斜体、引用块、分隔线、图片与链接。
"""

from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional

CHROME_PATHS = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
)

STYLE = """
@page { size: A4; margin: 20mm 18mm 18mm 18mm; }
body {
    font-family: "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", sans-serif;
    font-size: 10.5pt; line-height: 1.75; color: #1f2328; max-width: 900px;
    margin: 0 auto; padding: 0 12px;
}
h1 { font-size: 20pt; border-bottom: 2px solid #d0d7de; padding-bottom: 8px; margin-top: 26px; }
h2 { font-size: 15.5pt; border-bottom: 1px solid #d8dee4; padding-bottom: 5px; margin-top: 22px; }
h3 { font-size: 13pt; margin-top: 18px; }
h4 { font-size: 11.5pt; margin-top: 15px; }
p { margin: 8px 0; text-align: justify; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 9.5pt; }
th, td { border: 1px solid #d0d7de; padding: 5px 8px; vertical-align: top; }
th { background: #f2f4f7; font-weight: 600; text-align: left; }
tr:nth-child(even) td { background: #fafbfc; }
code { font-family: "Cascadia Mono", Consolas, "Courier New", monospace;
       font-size: 9.5pt; background: #f2f4f7; padding: 1px 4px; border-radius: 3px; }
pre { background: #f6f8fa; border: 1px solid #d8dee4; border-radius: 6px;
      padding: 10px 12px; overflow-x: auto; line-height: 1.5; }
pre code { background: none; padding: 0; font-size: 9pt; }
blockquote { margin: 10px 0; padding: 6px 14px; border-left: 4px solid #d0d7de;
             background: #f7f8fa; color: #3b4148; }
ul, ol { padding-left: 26px; margin: 8px 0; }
li { margin: 3px 0; }
img { max-width: 100%; border: 1px solid #d0d7de; border-radius: 4px; }
hr { border: none; border-top: 1px solid #d8dee4; margin: 20px 0; }
strong { font-weight: 700; }
"""


def find_browser() -> Optional[str]:
    """查找本机可用的 Chromium 内核浏览器。

    :return: 可执行文件路径，都找不到时返回 ``None``。
    """
    for candidate in CHROME_PATHS:
        if Path(candidate).exists():
            return candidate
    for name in ("chrome", "msedge", "chromium"):
        found = shutil.which(name)
        if found:
            return found
    return None


def inline(text: str) -> str:
    """把行内 Markdown 转成 HTML。

    :param text: 行内文本。
    :return: 转义并替换后的 HTML 片段。
    """
    escaped = html.escape(text, quote=False)
    escaped = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)", r'<img alt="\1" src="\2">', escaped
    )
    escaped = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', escaped
    )
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    escaped = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"<em>\1</em>", escaped)
    return escaped


def split_row(line: str) -> List[str]:
    """拆分表格行。

    :param line: 表格行文本。
    :return: 单元格文本列表。
    """
    parts = line.strip().strip("|").split("|")
    return [part.strip() for part in parts]


def is_table_separator(line: str) -> bool:
    """判断一行是否为表格分隔行。

    :param line: 文本行。
    :return: 是分隔行时返回 ``True``。
    """
    cells = split_row(line)
    return bool(cells) and all(
        cell and set(cell) <= set("-: ") and "-" in cell for cell in cells
    )


def convert(markdown: str) -> str:
    """把 Markdown 文本转换成 HTML。

    :param markdown: Markdown 源文本。
    :return: HTML 正文片段。
    """
    lines = markdown.splitlines()
    output: List[str] = []
    index = 0
    total = len(lines)

    while index < total:
        line = lines[index]
        stripped = line.strip()

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            index += 1
            code_lines: List[str] = []
            while index < total and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1
            attr = f' class="language-{html.escape(language)}"' if language else ""
            output.append(
                f"<pre><code{attr}>{html.escape(chr(10).join(code_lines))}</code></pre>"
            )
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            level = len(heading.group(1))
            output.append(f"<h{level}>{inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            output.append("<hr>")
            index += 1
            continue

        if "|" in stripped and index + 1 < total and is_table_separator(lines[index + 1]):
            header = split_row(stripped)
            index += 2
            rows: List[List[str]] = []
            while index < total and "|" in lines[index] and lines[index].strip():
                rows.append(split_row(lines[index]))
                index += 1
            parts = ["<table><thead><tr>"]
            for cell in header:
                parts.append(f"<th>{inline(cell)}</th>")
            parts.append("</tr></thead><tbody>")
            for row in rows:
                parts.append("<tr>")
                for cell in row:
                    parts.append(f"<td>{inline(cell)}</td>")
                parts.append("</tr>")
            parts.append("</tbody></table>")
            output.append("".join(parts))
            continue

        if stripped.startswith(">"):
            quote_lines: List[str] = []
            while index < total and lines[index].strip().startswith(">"):
                quote_lines.append(lines[index].strip().lstrip(">").strip())
                index += 1
            output.append(f"<blockquote>{inline(' '.join(quote_lines))}</blockquote>")
            continue

        ordered = re.match(r"^(\d+)\.\s+(.*)$", stripped)
        if ordered:
            items: List[str] = []
            while index < total:
                match = re.match(r"^\s*(\d+)\.\s+(.*)$", lines[index])
                if not match:
                    break
                items.append(f"<li>{inline(match.group(2))}</li>")
                index += 1
            output.append("<ol>" + "".join(items) + "</ol>")
            continue

        if re.match(r"^[-*+]\s+", stripped):
            items = []
            while index < total and re.match(r"^\s*[-*+]\s+", lines[index]):
                match = re.match(r"^\s*[-*+]\s+(.*)$", lines[index])
                items.append(f"<li>{inline(match.group(1))}</li>")
                index += 1
            output.append("<ul>" + "".join(items) + "</ul>")
            continue

        paragraph: List[str] = []
        while index < total and lines[index].strip():
            current = lines[index].strip()
            if (
                current.startswith("#")
                or current.startswith("```")
                or current.startswith(">")
                or re.match(r"^[-*+]\s+", current)
                or re.match(r"^\d+\.\s+", current)
            ):
                break
            paragraph.append(current)
            index += 1
        if paragraph:
            output.append(f"<p>{inline(' '.join(paragraph))}</p>")
        else:
            index += 1

    return "\n".join(output)


def build_html(body: str, title: str) -> str:
    """拼装完整 HTML 页面。

    :param body: 正文 HTML。
    :param title: 页面标题。
    :return: 完整 HTML 文档。
    """
    return (
        "<!DOCTYPE html>\n<html lang=\"zh-CN\">\n<head>\n"
        '<meta charset="utf-8">\n'
        f"<title>{html.escape(title)}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n{body}\n</body>\n</html>\n"
    )


def html_to_pdf(browser: str, html_path: Path, pdf_path: Path) -> None:
    """用浏览器无头模式把 HTML 打印成 PDF。

    :param browser: 浏览器可执行文件路径。
    :param html_path: HTML 文件路径。
    :param pdf_path: 输出的 PDF 路径。
    """
    profile = Path(tempfile.gettempdir()) / "mavis_md2pdf_profile"
    command = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-first-run",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    result = subprocess.run(
        command, capture_output=True, text=True, timeout=180, check=False
    )
    if not pdf_path.exists():
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"PDF 生成失败：{message}")


def main() -> int:
    """命令行入口。

    :return: 进程退出码。
    """
    parser = argparse.ArgumentParser(description="Markdown 转 PDF")
    parser.add_argument("--input", required=True, help="Markdown 输入文件")
    parser.add_argument("--output", required=True, help="PDF 输出文件")
    parser.add_argument(
        "--html-only", action="store_true", help="只生成 HTML，不生成 PDF"
    )
    args = parser.parse_args()

    source = Path(args.input).resolve()
    target = Path(args.output).resolve()
    markdown = source.read_text(encoding="utf-8")

    title = "报告"
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    body = convert(markdown)
    html_text = build_html(body, title)
    html_path = source.with_suffix(".html")
    html_path.write_text(html_text, encoding="utf-8")
    print(f"HTML 已生成：{html_path}")

    if args.html_only:
        return 0

    browser = find_browser()
    if browser is None:
        print("未找到 Chrome 或 Edge，无法生成 PDF，已保留 HTML 文件。", file=sys.stderr)
        return 2
    html_to_pdf(browser, html_path, target)
    print(f"PDF 已生成：{target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
