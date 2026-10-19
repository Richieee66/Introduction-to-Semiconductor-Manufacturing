#!/usr/bin/env python3
"""檢查全書的連結、章節結構與提示框格式。

Check the whole book for broken links, chapter structure and box format.

用法 / Usage:
    python3 scripts/check_book.py

發現錯誤時回傳 1，只有警告時回傳 0。
Exits with 1 if any error is found; warnings alone exit with 0.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
SOURCE_LANG = "zh-TW"
SKIP_DIRS = {".git", "node_modules", "templates"}

LINK_RE = re.compile(r"!?\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
IMG_TAG_RE = re.compile(r"<img\b[^>]*\bsrc=\"([^\"]+)\"", re.IGNORECASE)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
GITHUB_ROUTE_RE = re.compile(r"^(\.\./)+(issues|pulls|discussions|wiki|releases|actions)(/|$)")
CHAPTER_RE = re.compile(r"^([a-z]{2,3}(?:-[A-Za-z0-9]+)?)/\d-[a-z0-9-]+/(\d{2})-[a-z0-9-]+/README\.md$")
ALERT_RE = re.compile(r"^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$")
LIST_ITEM_RE = re.compile(r"^(\s*)([-*+]|\d+[.)])\s+")

# 各語言的章節必備元素 / Required parts of a chapter, per language.
CHAPTER_RULES = {
    "zh-TW": {
        "title": "# 第 {n} 章",
        "required": {
            "📍 **晶圓位置**": "晶圓位置",
            "## 本章重點": "本章重點",
            "## 延伸閱讀": "延伸閱讀",
            "[目錄](../../README.md)": "導覽列",
        },
    },
    "en": {
        "title": "# Chapter {n}:",
        "required": {
            "📍 **Where the wafer is**": "Where the wafer is",
            "## Key takeaways": "Key takeaways",
            "## Further reading": "Further reading",
            "[Contents](../../README.md)": "navigation bar",
        },
    },
    "ja": {
        "title": "# 第 {n} 章",
        "required": {
            "📍 **ウェーハの現在地**": "ウェーハの現在地",
            "## この章のポイント": "この章のポイント",
            "## 参考文献": "参考文献",
            "[目次](../../README.md)": "ナビゲーション",
        },
    },
    "ko": {
        "title": "# 제{n}장",
        "required": {
            "📍 **웨이퍼의 현재 위치**": "웨이퍼의 현재 위치",
            "## 이 장의 핵심": "이 장의 핵심",
            "## 참고 자료": "참고 자료",
            "[목차](../../README.md)": "내비게이션",
        },
    },
}

# 台灣用語檢查：常見的非台灣用語（只發出警告）。
# Terminology check for the Traditional Chinese text (warnings only).
DISCOURAGED_TERMS = {
    "芯片": "晶片",
    "晶體管": "電晶體",
    "光刻": "微影",
    "刻蝕": "蝕刻",
    "離子注入": "離子佈植",
    "納米": "奈米",
    "閾值電壓": "臨界電壓",
    "軟件": "軟體",
    "硬件": "硬體",
    "接口": "介面",
    "內存": "記憶體",
    "網絡": "網路",
}

# 常見的簡體字（只發出警告）。只收錄在台灣的繁體中文裡幾乎不會出現的字。
# Common Simplified Chinese characters (warnings only).
SIMPLIFIED_CHARS = set(
    "们这个为与说时过发现会对产业电导体层门线术设计础规质检测试结构样书读写图标题录页问错误单联关开"
    "经语译视频网络专务简态选择应运动输环节约织组济阶处获辆军伤长东乐车马鸟鱼龙风飞广庆库张弹强归"
    "忆怀总战户挂损换摄数断无旧显晓暂杂权条来极构枪树桥档梦检楼汉汤沟没泪泽洁浅测济浓润涨渐温湿满滤"
    "灭灯灵灾炉炼烂烦烧热爱牵状独狮猎猪献环现画畅疗盐监盖盘矿码砖确碍礼祸离种积称税稳穷窃竞笔筑签"
    "简类粮紧纠红级纪纤纯纳纵纷纸纹纺纽练细终绍结绕绘给络绝统继绩续维综绿缓编缘缩缴罗罚职肃肠肤肿胀"
    "胆脑脚脱脸舰艺芜苍苏药获营虑虚补装见观规视览觉触计订认讨让训议讯记讲许论访证评识诉词试话询该详"
    "误请诸读课谁调谈谢贝负贡财责败货贩购贯费资赋赏赔赚赛赞赢赶趋跃践轨转轮软轰轻载较辅辉输边达迁迟"
    "适选递逻遗邮释钉钟钢钱铁铜铝铭银链销锁锅锋锡键镜闭闯闲间闻阀阅队阳阴阵际陆陈险随隐难静顶项顺须"
    "顾领颗颜额饭馆驱驶驾验骑鲜鸡麦黄齐齿龄掺杂兴举义乐习书买乱亏亚亲亿仅从仓优伟传伤价众优员"
)


def iter_markdown_files() -> list[Path]:
    files = []
    for path in sorted(ROOT.rglob("*.md")):
        rel = path.relative_to(ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        files.append(path)
    return files


def strip_code(lines: list[str]) -> list[str]:
    """把程式碼區塊與行內程式碼換成空白，保留行號。"""
    out, in_fence = [], False
    for line in lines:
        if FENCE_RE.match(line):
            in_fence = not in_fence
            out.append("")
            continue
        out.append("" if in_fence else INLINE_CODE_RE.sub("", line))
    return out


def check_links(path: Path, lines: list[str], errors: list[str]) -> None:
    rel = path.relative_to(ROOT).as_posix()
    for no, line in enumerate(lines, 1):
        targets = LINK_RE.findall(line) + IMG_TAG_RE.findall(line)
        for target in targets:
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.IGNORECASE) or target.startswith("#"):
                continue
            if GITHUB_ROUTE_RE.match(target):
                continue
            clean = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not clean:
                continue
            if not (path.parent / clean).resolve().exists():
                errors.append(f"{rel}:{no}: 連結失效 broken link -> {target}")


def check_boxes(path: Path, lines: list[str], errors: list[str]) -> None:
    """引用區塊裡連續兩行一般文字，在 GitHub 上會被合併成同一段。"""
    rel = path.relative_to(ROOT).as_posix()
    prev_text = False
    for no, line in enumerate(lines, 1):
        if not line.startswith(">"):
            prev_text = False
            continue
        content = re.sub(r"^>\s?", "", line)
        if content.strip() == "" or LIST_ITEM_RE.match(content):
            prev_text = False
            continue
        if content.startswith("[!"):
            if not ALERT_RE.match(content.strip()):
                errors.append(f"{rel}:{no}: 不支援的提示框類型 unsupported alert type -> {content.strip()}")
            prev_text = False
            continue
        if prev_text:
            errors.append(
                f"{rel}:{no}: 引用區塊中連續兩行文字會被合併，請改用清單或空行 "
                f"consecutive lines in a blockquote will be merged"
            )
        prev_text = True


def check_chapter(path: Path, text: str, errors: list[str]) -> None:
    rel = path.relative_to(ROOT).as_posix()
    match = CHAPTER_RE.match(rel)
    if not match:
        return
    lang, number = match.group(1), int(match.group(2))
    rules = CHAPTER_RULES.get(lang)
    if rules is None:
        if "](../../README.md)" not in text:
            errors.append(f"{rel}: missing navigation link to ../../README.md")
        return
    title = rules["title"].format(n=number)
    first_heading = next((l for l in text.splitlines() if l.startswith("# ")), "")
    if not first_heading.startswith(title):
        errors.append(f"{rel}: 標題應以「{title}」開頭 title should start with \"{title}\"")
    for marker, name in rules["required"].items():
        if marker not in text:
            errors.append(f"{rel}: 缺少「{name}」 missing section")


def check_language(path: Path, lines: list[str], warnings: list[str]) -> None:
    """只檢查繁體中文原文與根目錄的專案文件。"""
    rel = path.relative_to(ROOT)
    first = rel.parts[0]
    if rel.as_posix() in {"STYLE_GUIDE.md", "README.md"}:
        return
    if len(rel.parts) > 1 and first != SOURCE_LANG and re.match(r"^[a-z]{2,3}(-[A-Za-z0-9]+)?$", first):
        return
    for no, line in enumerate(lines, 1):
        for term, preferred in DISCOURAGED_TERMS.items():
            if term in line:
                warnings.append(f"{rel.as_posix()}:{no}: 建議用「{preferred}」取代「{term}」")
        found = sorted({ch for ch in line if ch in SIMPLIFIED_CHARS})
        if found:
            warnings.append(f"{rel.as_posix()}:{no}: 可能是簡體字 possible Simplified Chinese -> {''.join(found)}")


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []
    files = iter_markdown_files()
    for path in files:
        text = path.read_text(encoding="utf-8")
        lines = strip_code(text.splitlines())
        check_links(path, lines, errors)
        check_boxes(path, lines, errors)
        check_chapter(path, text, errors)
        check_language(path, lines, warnings)

    for message in warnings:
        print(f"WARNING {message}")
    for message in errors:
        print(f"ERROR   {message}")
    print(f"\n檢查了 {len(files)} 個檔案：{len(errors)} 個錯誤，{len(warnings)} 個警告。")
    print(f"Checked {len(files)} files: {len(errors)} errors, {len(warnings)} warnings.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
