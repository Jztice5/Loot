#!/usr/bin/env python3
"""Validate Loot's repository-backed context management structure."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
QUARTER_PATTERN = re.compile(r"^\d{4}-Q[1-4]$")
DATE_PREFIX_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}-.+\.md$")
DATE_SUFFIX_PATTERN = re.compile(r"^.+-\d{4}-\d{2}-\d{2}\.md$")
LINK_PATTERN = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
REQUIREMENT_HEADING_PATTERN = re.compile(r"^### (REQ-\d+)[：:].*$", re.MULTILINE)
REQUIREMENT_STATE_PATTERN = re.compile(
    r"^状态：(Planned|In Progress|Blocked|Done|Rejected|Superseded|Deferred)\s*$",
    re.MULTILINE,
)
QUEUE_SECTION_PATTERN = re.compile(
    r"^## 阶段与执行队列\s*$\n(.*?)(?=^## |\Z)",
    re.MULTILINE | re.DOTALL,
)
QUEUE_ROW_PATTERN = re.compile(r"^\|\s*\d+\s*\|\s*`(REQ-\d+)`", re.MULTILINE)
QUEUED_REQUIREMENT_STATES = {"Planned", "In Progress", "Blocked"}
IGNORED_PARTS = {".git", ".venv", "node_modules", "build", "dist"}

REQUIRED_PATHS = (
    "README.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/development/memory.md",
    "docs/architecture/README.md",
    "docs/architecture/context/temporal-context-model-v0.1.md",
    "docs/planning/README.md",
    "docs/reviews/README.md",
    "docs/development/log/README.md",
    "docs/runbooks/context-health-check.md",
    "docs/skills/vibe-context-manager/SKILL.md",
)

TEMPORAL_CONTEXT_FILES = (
    "AGENTS.md",
    "docs/README.md",
    "docs/architecture/context/temporal-context-model-v0.1.md",
    "docs/skills/vibe-context-manager/SKILL.md",
)
TEMPORAL_CONTEXT_MARKERS = (
    "过去式上下文",
    "现在进行时上下文",
    "未来规划上下文",
)


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


def markdown_files() -> list[Path]:
    return sorted(
        path
        for path in ROOT.rglob("*.md")
        if not IGNORED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def link_target(raw_target: str) -> str:
    target = raw_target.strip()
    if target.startswith("<") and ">" in target:
        return target[1 : target.index(">")]
    return target.split(maxsplit=1)[0]


def check_required_paths(report: Report) -> None:
    for relative_path in REQUIRED_PATHS:
        if not (ROOT / relative_path).exists():
            report.error(f"missing required context path: {relative_path}")


def check_root_readme(report: Report) -> None:
    content = (ROOT / "README.md").read_text(encoding="utf-8")
    if "docs/development/memory.md" not in content:
        report.error("root README must link to docs/development/memory.md")
    if re.search(r"^## (当前状态|当前阶段|下一步)\s*$", content, re.MULTILINE):
        report.error("root README duplicates volatile project status; keep it in memory/planning")


def check_temporal_context_model(report: Report) -> None:
    for relative_path in TEMPORAL_CONTEXT_FILES:
        path = ROOT / relative_path
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for marker in TEMPORAL_CONTEXT_MARKERS:
            if marker not in content:
                report.error(f"temporal context marker missing in {relative_path}: {marker}")


def check_dynamic_source_boundaries(report: Report) -> None:
    memory_path = ROOT / "docs/development/memory.md"
    memory = memory_path.read_text(encoding="utf-8")
    for heading in ("关键历史索引", "未完成", "下一步"):
        if re.search(rf"^## {heading}\s*$", memory, re.MULTILINE):
            report.error(
                f"memory duplicates log or planning with forbidden section: {heading}"
            )

    for quarter_dir in quarter_directories(ROOT / "docs/planning"):
        overview = quarter_dir / f"规划总览-{quarter_dir.name}.md"
        if not overview.exists():
            continue
        content = overview.read_text(encoding="utf-8")
        if re.search(r"^## (当前阶段|当前焦点|执行队列)\s*$", content, re.MULTILINE):
            report.error(
                "planning overview duplicates volatile requirement state: "
                f"{overview.relative_to(ROOT)}"
            )


def check_requirement_queue_content(report: Report, label: str, content: str) -> None:
    matches = list(REQUIREMENT_HEADING_PATTERN.finditer(content))
    states: dict[str, str] = {}
    for index, match in enumerate(matches):
        requirement_id = match.group(1)
        section_end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
        section = content[match.end() : section_end]
        state_match = REQUIREMENT_STATE_PATTERN.search(section)
        if requirement_id in states:
            report.error(f"duplicate requirement heading in {label}: {requirement_id}")
            continue
        if state_match is None:
            report.error(f"requirement has no recognized state in {label}: {requirement_id}")
            continue
        states[requirement_id] = state_match.group(1)

    queue_section_match = QUEUE_SECTION_PATTERN.search(content)
    if queue_section_match is None:
        report.error(f"missing requirement queue section in {label}")
        queue = []
    else:
        queue = QUEUE_ROW_PATTERN.findall(queue_section_match.group(1))
    duplicate_queue_ids = sorted(
        requirement_id for requirement_id in set(queue) if queue.count(requirement_id) > 1
    )
    if duplicate_queue_ids:
        report.error(
            f"duplicate requirement queue entries in {label}: {', '.join(duplicate_queue_ids)}"
        )

    expected = {
        requirement_id
        for requirement_id, state in states.items()
        if state in QUEUED_REQUIREMENT_STATES
    }
    actual = set(queue)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing or extra:
        details = []
        if missing:
            details.append(f"missing={','.join(missing)}")
        if extra:
            details.append(f"extra={','.join(extra)}")
        report.error(f"requirement queue/status mismatch in {label}: {' '.join(details)}")

    in_progress = sorted(
        requirement_id for requirement_id, state in states.items() if state == "In Progress"
    )
    if len(in_progress) > 1:
        report.error(
            f"multiple In Progress requirements in {label}: {', '.join(in_progress)}"
        )


def check_current_requirement_queue(report: Report) -> None:
    planning_quarters = quarter_directories(ROOT / "docs/planning")
    if not planning_quarters:
        return
    current_quarter = max(planning_quarters, key=lambda path: path.name)
    requirements_path = current_quarter / f"需求管理-{current_quarter.name}.md"
    if not requirements_path.exists():
        return
    check_requirement_queue_content(
        report,
        str(requirements_path.relative_to(ROOT)),
        requirements_path.read_text(encoding="utf-8"),
    )


def check_local_links(report: Report, files: list[Path]) -> int:
    checked = 0
    for path in files:
        content = path.read_text(encoding="utf-8")
        for match in LINK_PATTERN.finditer(content):
            raw_target = link_target(match.group(1))
            path_part = raw_target.split("#", 1)[0]
            if not path_part or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", path_part):
                continue
            checked += 1
            resolved = (path.parent / unquote(path_part)).resolve()
            if not resolved.exists():
                line = content.count("\n", 0, match.start()) + 1
                relative = path.relative_to(ROOT)
                report.error(f"broken local link: {relative}:{line} -> {raw_target}")
    return checked


def quarter_directories(base: Path) -> list[Path]:
    if not base.exists():
        return []
    return sorted(
        path
        for path in base.iterdir()
        if path.is_dir() and QUARTER_PATTERN.match(path.name)
    )


def check_quarter_layout(report: Report) -> None:
    planning_base = ROOT / "docs/planning"
    log_base = ROOT / "docs/development/log"
    review_base = ROOT / "docs/reviews"
    planning_quarters = quarter_directories(planning_base)
    log_quarters = quarter_directories(log_base)
    review_quarters = quarter_directories(review_base)
    planning_index = (planning_base / "README.md").read_text(encoding="utf-8")
    log_index = (log_base / "README.md").read_text(encoding="utf-8")
    review_index = (review_base / "README.md").read_text(encoding="utf-8")

    for quarter_dir in planning_quarters:
        if quarter_dir.name not in planning_index:
            report.error(f"planning index does not reference quarter: {quarter_dir.name}")
        required = {
            f"规划总览-{quarter_dir.name}.md",
            f"需求管理-{quarter_dir.name}.md",
        }
        present = {path.name for path in quarter_dir.glob("*.md")}
        for missing in sorted(required - present):
            missing_path = quarter_dir.relative_to(ROOT) / missing
            report.error(f"missing quarterly planning file: {missing_path}")
        for redundant_plan in sorted(quarter_dir.glob("开发计划-*.md")):
            report.error(
                "quarterly development plan duplicates requirements, memory, and log: "
                f"{redundant_plan.relative_to(ROOT)}"
            )

    for quarter_dir in log_quarters:
        if quarter_dir.name not in log_index:
            report.error(f"development log index does not reference quarter: {quarter_dir.name}")
        overview = quarter_dir / f"开发过程总览-{quarter_dir.name}.md"
        if not overview.exists():
            report.error(f"missing development overview: {overview.relative_to(ROOT)}")
            overview_content = ""
        else:
            overview_content = overview.read_text(encoding="utf-8")
        for path in quarter_dir.glob("*.md"):
            if path == overview:
                continue
            if not DATE_PREFIX_PATTERN.match(path.name):
                report.error(f"invalid dated development log name: {path.relative_to(ROOT)}")
            if path.name not in overview_content:
                report.error(f"development overview does not reference: {path.relative_to(ROOT)}")
            content = path.read_text(encoding="utf-8")
            if re.search(r"^## (下一步|后续|下一环节)\s*$", content, re.MULTILINE):
                report.error(
                    "development log uses a live planning heading; label it as a historical snapshot: "
                    f"{path.relative_to(ROOT)}"
                )

    for quarter_dir in review_quarters:
        if quarter_dir.name not in review_index:
            report.error(f"review index does not reference quarter: {quarter_dir.name}")
        overview = quarter_dir / f"评审记录总览-{quarter_dir.name}.md"
        if not overview.exists():
            report.error(f"missing review overview: {overview.relative_to(ROOT)}")
            overview_content = ""
        else:
            overview_content = overview.read_text(encoding="utf-8")
        for path in quarter_dir.glob("*.md"):
            if path == overview:
                continue
            if not DATE_SUFFIX_PATTERN.match(path.name):
                report.error(f"invalid dated review name: {path.relative_to(ROOT)}")
            if path.name not in overview_content:
                report.error(f"review overview does not reference: {path.relative_to(ROOT)}")

    quarter_names = {
        path.name for path in planning_quarters + log_quarters + review_quarters
    }
    if quarter_names:
        current_quarter = max(quarter_names)
        docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        memory = (ROOT / "docs/development/memory.md").read_text(encoding="utf-8")
        if f"planning/{current_quarter}/" not in docs_index:
            report.error(f"docs index does not reference current quarter: {current_quarter}")
        if f"planning/{current_quarter}/" not in memory:
            report.error(f"memory does not reference current quarter: {current_quarter}")


def check_size_budgets(report: Report) -> tuple[int, int]:
    memory_path = ROOT / "docs/development/memory.md"
    skill_path = ROOT / "docs/skills/vibe-context-manager/SKILL.md"
    memory_lines = len(memory_path.read_text(encoding="utf-8").splitlines())
    skill_lines = len(skill_path.read_text(encoding="utf-8").splitlines())
    if memory_lines > 150:
        report.warn(f"memory.md has {memory_lines} lines; slim it below the 150-line budget")
    if skill_lines > 400:
        report.warn(
            f"vibe-context-manager has {skill_lines} lines; "
            "consider moving detail to references"
        )
    return memory_lines, skill_lines


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_skill_mirror(report: Report) -> str:
    source = ROOT / "docs/skills/vibe-context-manager/SKILL.md"
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    target = codex_home / "skills/vibe-context-manager/SKILL.md"
    if not target.exists():
        report.warn(f"global skill mirror is not installed: {target}")
        return "missing"
    if sha256(source) != sha256(target):
        report.error(f"global skill mirror differs from project source: {target}")
        return "mismatch"
    return "match"


def check_git_whitespace(report: Report) -> None:
    for args in (("git", "diff", "--check"), ("git", "diff", "--cached", "--check")):
        result = subprocess.run(
            args,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if result.returncode:
            report.error(result.stdout.strip() or result.stderr.strip() or "git diff check failed")


def check_text_whitespace(report: Report, markdown: list[Path]) -> None:
    paths = {
        *markdown,
        ROOT / "Makefile",
        ROOT / "pyproject.toml",
        *ROOT.glob("scripts/**/*.py"),
    }
    for path in sorted(paths):
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(content.splitlines(keepends=True), start=1):
            body = line.rstrip("\r\n")
            if body.endswith((" ", "\t")):
                relative = path.relative_to(ROOT)
                report.error(f"trailing whitespace: {relative}:{line_number}")
        if content and not content.endswith("\n"):
            report.error(f"missing final newline: {path.relative_to(ROOT)}")


def main() -> int:
    report = Report()
    files = markdown_files()
    check_required_paths(report)
    check_root_readme(report)
    check_temporal_context_model(report)
    check_dynamic_source_boundaries(report)
    check_current_requirement_queue(report)
    links_checked = check_local_links(report, files)
    check_quarter_layout(report)
    memory_lines, skill_lines = check_size_budgets(report)
    mirror_state = check_skill_mirror(report)
    check_text_whitespace(report, files)
    check_git_whitespace(report)

    for warning in report.warnings:
        print(f"WARN {warning}")
    for error in report.errors:
        print(f"ERROR {error}")

    print(
        "context_summary "
        f"markdown_files={len(files)} "
        f"local_links={links_checked} "
        f"memory_lines={memory_lines} "
        f"skill_lines={skill_lines} "
        f"skill_mirror={mirror_state}"
    )
    if report.errors:
        print(f"context check failed with {len(report.errors)} error(s)")
        return 1
    print("context check passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
