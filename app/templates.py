"""Jinja2 通知模板（对齐 MoviePilot 的「字典字面量 + Jinja2 字段」语法）。

模板格式（与 MoviePilot 一致）：
  {"text": "{{ title }} 更新到 S{{ season }}E{{ episode }}", "image": "{{ poster }}"}

事件类型：feed_new / show_new / library_update / done / sub_added。
用户可在 Web UI 编辑；没配模板时退回内置排版。

模板文件 config/notify_templates.txt，用「=== 事件名 ===」分段
（避开 YAML 的 {{ }} 花括号冲突）。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

from jinja2 import Environment

from .log import log


def parse_template_content(template_content: str) -> dict[str, Any]:
    """把模板字符串解析成 dict（字段→原始 Jinja2 字符串）。

    用 ast.literal_eval 安全解析，避免 eval 任意代码。
    """
    content = (template_content or "").strip()
    if not content:
        return {}
    try:
        parsed = ast.literal_eval(content)
    except Exception as e:
        raise ValueError('模板必须是字典字面量（形如 {"title": "..."}）') from e
    if not isinstance(parsed, dict):
        raise ValueError('模板必须是字典字面量（形如 {"title": "..."}）')
    return parsed


def render_dict_template(template_content: str, context: dict[str, Any]) -> dict[str, str]:
    """渲染字典模板，返回解析后的 dict。"""
    parsed = parse_template_content(template_content)
    env = Environment(autoescape=False)
    result: dict[str, str] = {}
    for key, tpl in parsed.items():
        try:
            result[key] = env.from_string(str(tpl)).render(**context)
        except Exception as e:
            log.warning("模板字段 %s 渲染失败：%s", key, e)
            result[key] = str(tpl)
    return result


def render_with_context(template_content: str, context: dict[str, Any]) -> str:
    """渲染纯文本 Jinja2 模板（不含字典外层）。"""
    env = Environment(autoescape=False)
    try:
        return env.from_string(template_content or "").render(**context)
    except Exception as e:
        log.warning("模板渲染失败：%s", e)
        return template_content


# --------------------------------------------------------------------------
# 模板文件读写
# --------------------------------------------------------------------------

def load_templates(path: Path | None) -> dict[str, str]:
    if not path or not path.exists():
        return {}
    templates: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("===") and stripped.endswith("==="):
            if current is not None:
                templates[current] = "\n".join(buf).strip()
            current = stripped.strip("=").strip()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        templates[current] = "\n".join(buf).strip()
    return templates


def save_templates(path: Path | None, templates: dict[str, str]) -> None:
    if not path:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for event, content in templates.items():
        lines.append(f"=== {event} ===")
        lines.append(content or "")
        lines.append("")
    path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
