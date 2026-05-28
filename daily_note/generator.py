from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
import os
from pathlib import Path
import re
import subprocess


class DailyNoteError(Exception):
    """Base error for user-facing failures."""


@dataclass(frozen=True)
class Commit:
    sha: str
    author_name: str
    author_email: str
    committed_at: str
    subject: str
    files: tuple[str, ...]


@dataclass(frozen=True)
class DailyNote:
    path: Path
    index_path: Path
    created: bool
    index_updated: bool


@dataclass(frozen=True)
class RepoActivity:
    repo: Path
    name: str
    branch: str | None
    commits: tuple[Commit, ...]


TYPE_LABELS = {
    "feat": "実装",
    "fix": "修正",
    "test": "テスト",
    "docs": "ドキュメント",
    "refactor": "リファクタリング",
    "chore": "保守",
    "build": "ビルド",
    "ci": "CI",
    "perf": "改善",
    "style": "整形",
}

TICKET_PATTERN = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
CONVENTIONAL_PATTERN = re.compile(r"^(?P<type>[a-z]+)(?:\([^)]+\))?(!)?:\s*(?P<title>.+)$")
SKIP_SCAN_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}

NOTE_SECTION_HEADINGS = {
    "work": "## 今日やったこと",
    "learned": "## 学んだこと",
    "blocked": "## 詰まったこと・相談したいこと",
    "tomorrow": "## 明日やること",
}


def generate_note(
    repo: Path,
    target_date: date,
    output_dir: Path,
    *,
    force: bool = False,
) -> DailyNote:
    repo = repo.resolve()
    output_dir = output_dir if output_dir.is_absolute() else repo / output_dir
    output_dir = output_dir.resolve()
    ensure_git_repo(repo)

    author_email = get_git_value(repo, "config", "user.email")
    if not author_email:
        raise DailyNoteError("git config user.email が未設定です。先に Git の user.email を設定してください。")

    branch = get_git_value(repo, "rev-parse", "--abbrev-ref", "HEAD") or None
    if branch == "HEAD":
        branch = None

    commits = read_commits(repo, target_date, author_email)
    note_path = output_dir / f"{target_date.isoformat()}.md"
    index_path = output_dir / f"{target_date:%Y-%m}.md"
    output_dir.mkdir(parents=True, exist_ok=True)

    created = False
    if note_path.exists() and not force:
        created = False
    else:
        note_path.write_text(render_daily_markdown(target_date, commits, branch), encoding="utf-8")
        created = True

    update_month_index(output_dir, target_date)
    return DailyNote(path=note_path, index_path=index_path, created=created, index_updated=True)


def generate_workspace_note(
    workspace: Path,
    target_date: date,
    output_dir: Path,
    *,
    author_email: str | None = None,
    force: bool = False,
) -> DailyNote:
    workspace = workspace.resolve()
    output_dir = output_dir.resolve()
    if not workspace.exists():
        raise DailyNoteError(f"workspace が見つかりません: {workspace}")
    if not workspace.is_dir():
        raise DailyNoteError(f"workspace はディレクトリではありません: {workspace}")

    repos = find_git_repos(workspace)
    if not repos:
        raise DailyNoteError(f"workspace 配下に Gitリポジトリが見つかりません: {workspace}")

    activities: list[RepoActivity] = []
    for repo in repos:
        repo_author_email = author_email or get_git_value(repo, "config", "user.email")
        if not repo_author_email:
            continue
        branch = get_git_value(repo, "rev-parse", "--abbrev-ref", "HEAD") or None
        if branch == "HEAD":
            branch = None
        commits = tuple(read_commits(repo, target_date, repo_author_email))
        if commits:
            activities.append(RepoActivity(repo=repo, name=repo_name(repo, workspace), branch=branch, commits=commits))

    note_path = output_dir / f"{target_date.isoformat()}.md"
    index_path = output_dir / f"{target_date:%Y-%m}.md"
    output_dir.mkdir(parents=True, exist_ok=True)

    created = False
    if note_path.exists() and not force:
        created = False
    else:
        note_path.write_text(render_workspace_markdown(target_date, activities, workspace), encoding="utf-8")
        created = True

    update_month_index(output_dir, target_date)
    return DailyNote(path=note_path, index_path=index_path, created=created, index_updated=True)


def find_git_repos(workspace: Path) -> list[Path]:
    workspace = workspace.resolve()
    repos: list[Path] = []
    for current, dirnames, filenames in os.walk(workspace):
        current_path = Path(current)
        if ".git" in dirnames or ".git" in filenames:
            repos.append(current_path)
            dirnames[:] = []
            continue
        dirnames[:] = [dirname for dirname in dirnames if dirname not in SKIP_SCAN_DIRS]
    return sorted(repos)


def ensure_git_repo(repo: Path) -> None:
    result = run_git(repo, "rev-parse", "--is-inside-work-tree", check=False)
    if result.returncode != 0 or result.stdout.strip() != "true":
        raise DailyNoteError(f"Gitリポジトリではありません: {repo}")


def get_git_value(repo: Path, *args: str) -> str:
    result = run_git(repo, *args, check=False)
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def read_commits(repo: Path, target_date: date, author_email: str) -> list[Commit]:
    if not has_commits(repo):
        return []

    since = datetime.combine(target_date, time.min).isoformat(timespec="seconds")
    until = datetime.combine(target_date, time.max).replace(microsecond=0).isoformat(timespec="seconds")
    result = run_git(
        repo,
        "log",
        "--date=iso-strict",
        f"--since={since}",
        f"--until={until}",
        f"--author={author_email}",
        "--reverse",
        "--pretty=format:%x1e%H%x1f%an%x1f%ae%x1f%ad%x1f%s",
        "--name-only",
    )
    return parse_git_log(result.stdout)


def has_commits(repo: Path) -> bool:
    result = run_git(repo, "rev-parse", "--verify", "HEAD", check=False)
    return result.returncode == 0


def parse_git_log(output: str) -> list[Commit]:
    commits: list[Commit] = []
    for raw_entry in output.split("\x1e"):
        entry = raw_entry.strip()
        if not entry:
            continue

        lines = entry.splitlines()
        header = lines[0]
        fields = header.split("\x1f")
        if len(fields) != 5:
            continue

        files = tuple(line.strip() for line in lines[1:] if line.strip())
        commits.append(
            Commit(
                sha=fields[0],
                author_name=fields[1],
                author_email=fields[2],
                committed_at=fields[3],
                subject=fields[4],
                files=files,
            )
        )
    return commits


def render_workspace_markdown(target_date: date, activities: list[RepoActivity], workspace: Path) -> str:
    commits = [commit for activity in activities for commit in activity.commits]
    sections = [
        f"# 日報 {target_date.isoformat()}",
        "",
        "## 今日やったこと",
        *render_workspace_work_items(activities),
        "",
        "## 対象リポジトリ",
        *render_repo_items(activities),
        "",
        "## 変更した主な領域",
        *render_area_items(commits),
        "",
        "## 学んだこと",
        "- ",
        "",
        "## 詰まったこと・相談したいこと",
        "- ",
        "",
        "## 明日やること",
        "- ",
    ]

    related_items = render_workspace_related_items(activities)
    if related_items:
        sections.extend(["", "## 関連チケット・ブランチ", *related_items])

    sections.extend(["", "## 集計元", f"- `{workspace}`"])
    return "\n".join(sections).rstrip() + "\n"


def render_daily_markdown(target_date: date, commits: list[Commit], branch: str | None) -> str:
    sections = [
        f"# 日報 {target_date.isoformat()}",
        "",
        "## 今日やったこと",
        *render_work_items(commits),
        "",
        "## 変更した主な領域",
        *render_area_items(commits),
        "",
        "## 学んだこと",
        "- ",
        "",
        "## 詰まったこと・相談したいこと",
        "- ",
        "",
        "## 明日やること",
        "- ",
    ]

    related_items = render_related_items(commits, branch)
    if related_items:
        sections.extend(["", "## 関連チケット・ブランチ", *related_items])

    return "\n".join(sections).rstrip() + "\n"


def append_daily_sections(note_path: Path, section_items: Mapping[str, Iterable[str]]) -> bool:
    if not note_path.exists():
        raise DailyNoteError(f"日報ファイルが見つかりません: {note_path}")

    content = note_path.read_text(encoding="utf-8")
    lines = content.splitlines()

    for section_key, items in section_items.items():
        heading = NOTE_SECTION_HEADINGS.get(section_key)
        if heading is None:
            raise DailyNoteError(f"未対応の日報項目です: {section_key}")
        bullets = normalize_bullet_items(items)
        if bullets:
            lines = append_bullets_to_section(lines, heading, bullets)

    new_content = "\n".join(lines).rstrip() + "\n"
    if new_content == content:
        return False

    note_path.write_text(new_content, encoding="utf-8")
    return True


def normalize_bullet_items(items: Iterable[str]) -> list[str]:
    bullets: list[str] = []
    for item in items:
        for raw_line in item.splitlines():
            line = raw_line.strip()
            if line.startswith("- "):
                line = line[2:].strip()
            if line and line != "-":
                bullets.append(line)
    return bullets


def append_bullets_to_section(lines: list[str], heading: str, bullets: list[str]) -> list[str]:
    heading_index = next((index for index, line in enumerate(lines) if line.strip() == heading), None)
    bullet_lines = [f"- {bullet}" for bullet in bullets]

    if heading_index is None:
        new_lines = list(lines)
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.extend([heading, *bullet_lines])
        return new_lines

    section_end = len(lines)
    for index in range(heading_index + 1, len(lines)):
        if lines[index].startswith("## "):
            section_end = index
            break

    section_lines = [line for line in lines[heading_index + 1 : section_end] if line.strip() != "-"]
    insert_at = len(section_lines)
    while insert_at > 0 and not section_lines[insert_at - 1].strip():
        insert_at -= 1

    new_section_lines = section_lines[:insert_at] + bullet_lines + section_lines[insert_at:]
    return lines[: heading_index + 1] + new_section_lines + lines[section_end:]


def render_workspace_work_items(activities: list[RepoActivity]) -> list[str]:
    if not activities:
        return ["- 本日のGitコミットはありません。"]

    items: list[str] = []
    for activity in activities:
        for commit in activity.commits:
            items.append(f"- `{activity.name}`: {commit_label(commit.subject)}: {commit_title(commit.subject)}")
    return items


def render_repo_items(activities: list[RepoActivity]) -> list[str]:
    if not activities:
        return ["- 今日のコミットがあるリポジトリはありません。"]

    items: list[str] = []
    for activity in activities:
        branch = f" / `{activity.branch}`" if activity.branch else ""
        items.append(f"- `{activity.name}`: {len(activity.commits)}コミット{branch}")
    return items


def render_work_items(commits: list[Commit]) -> list[str]:
    if not commits:
        return ["- 本日のGitコミットはありません。"]

    return [f"- {commit_label(commit.subject)}: {commit_title(commit.subject)}" for commit in commits]


def render_area_items(commits: list[Commit]) -> list[str]:
    if not commits:
        return ["- 未記載"]

    areas: dict[str, int] = {}
    top_paths: dict[str, int] = {}
    for commit in commits:
        for file_path in commit.files:
            area = classify_file(file_path)
            areas[area] = areas.get(area, 0) + 1
            top = top_level_path(file_path)
            top_paths[top] = top_paths.get(top, 0) + 1

    if not areas:
        return ["- 未記載"]

    area_text = "、".join(f"{name} {count}件" for name, count in sorted(areas.items(), key=lambda item: (-item[1], item[0])))
    path_text = "、".join(f"`{name}`" for name, _ in sorted(top_paths.items(), key=lambda item: (-item[1], item[0]))[:5])
    if path_text:
        return [f"- {area_text}", f"- 主な変更先: {path_text}"]
    return [f"- {area_text}"]


def render_related_items(commits: list[Commit], branch: str | None) -> list[str]:
    tickets = sorted(
        {
            ticket
            for text in [branch or "", *(commit.subject for commit in commits)]
            for ticket in TICKET_PATTERN.findall(text)
        }
    )

    items: list[str] = []
    if branch:
        items.append(f"- ブランチ: `{branch}`")
    if tickets:
        items.append("- チケット: " + "、".join(f"`{ticket}`" for ticket in tickets))
    return items


def render_workspace_related_items(activities: list[RepoActivity]) -> list[str]:
    tickets = sorted(
        {
            ticket
            for activity in activities
            for text in [activity.branch or "", *(commit.subject for commit in activity.commits)]
            for ticket in TICKET_PATTERN.findall(text)
        }
    )

    branches = [f"`{activity.name}`: `{activity.branch}`" for activity in activities if activity.branch]
    items: list[str] = []
    if branches:
        items.append("- ブランチ: " + "、".join(branches))
    if tickets:
        items.append("- チケット: " + "、".join(f"`{ticket}`" for ticket in tickets))
    return items


def commit_label(subject: str) -> str:
    match = CONVENTIONAL_PATTERN.match(subject)
    if not match:
        return "作業"
    return TYPE_LABELS.get(match.group("type"), "作業")


def commit_title(subject: str) -> str:
    match = CONVENTIONAL_PATTERN.match(subject)
    if not match:
        return subject
    return match.group("title")


def classify_file(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    lower = normalized.lower()
    name = Path(normalized).name.lower()

    if "/test/" in lower or lower.startswith("test/") or lower.startswith("tests/"):
        return "テスト"
    if name.startswith("test_") or ".test." in name or ".spec." in name:
        return "テスト"
    if lower.startswith("docs/") or name == "readme.md" or lower.endswith(".md"):
        return "ドキュメント"
    if lower.startswith(".github/") or lower.endswith((".yml", ".yaml")):
        return "CI/設定"
    if lower.startswith(("src/", "app/", "server/", "daily_note/")):
        return "実装"
    if lower.endswith((".toml", ".json", ".ini", ".cfg", ".conf")):
        return "設定"
    return "その他"


def top_level_path(file_path: str) -> str:
    normalized = file_path.replace("\\", "/")
    parts = [part for part in normalized.split("/") if part]
    if not parts:
        return file_path
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]}/"


def repo_name(repo: Path, workspace: Path) -> str:
    try:
        return repo.relative_to(workspace).as_posix() or repo.name
    except ValueError:
        return repo.name


def update_month_index(output_dir: Path, target_date: date) -> None:
    month = target_date.strftime("%Y-%m")
    daily_files = sorted(output_dir.glob(f"{month}-??.md"))
    index_path = output_dir / f"{month}.md"

    lines = [f"# {month} の開発記録", ""]
    if not daily_files:
        lines.append("- 日報はまだありません。")
    for daily_file in daily_files:
        day = daily_file.stem
        content = daily_file.read_text(encoding="utf-8")
        work = first_bullet_after(content, "## 今日やったこと") or "未記入"
        learned = first_bullet_after(content, "## 学んだこと") or "未記入"
        blocked = first_bullet_after(content, "## 詰まったこと・相談したいこと") or "未記入"
        lines.extend(
            [
                f"## {day}",
                f"- [日報を見る](./{daily_file.name})",
                f"- やったこと: {work}",
                f"- 学んだこと: {learned}",
                f"- 詰まったこと: {blocked}",
                "",
            ]
        )

    index_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def first_bullet_after(content: str, heading: str) -> str | None:
    in_section = False
    for line in content.splitlines():
        if line.startswith("## "):
            if in_section:
                return None
            in_section = line.strip() == heading
            continue
        if not in_section:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            value = stripped[2:].strip()
            if value:
                return value
    return None


def run_git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "git command failed"
        raise DailyNoteError(message)
    return result
