from __future__ import annotations

import argparse
from datetime import date, timedelta
from pathlib import Path
import re
import sys

from .generator import DailyNoteError, append_daily_sections, generate_note, generate_workspace_note, update_month_index

DATE_PATTERN = re.compile(r"\d{4}[-/]\d{2}[-/]\d{2}")
RELATIVE_DATE_TERMS = (
    ("一昨日", -2),
    ("おととい", -2),
    ("昨日", -1),
    ("今日", 0),
    ("本日", 0),
    ("明日", 1),
)
FORCE_TERMS = ("上書き", "再生成", "作り直し", "force")
WORKSPACE_TERMS = ("workspace", "ワークスペース", "全体", "全部", "まとめて", "全リポジトリ")
INTERACTIVE_TERMS = ("入力", "記入", "書き込み", "書き込む", "追記", "対話", "interactive")
SECTION_PROMPTS = (
    ("work", "今日やったこと"),
    ("learned", "学んだこと"),
    ("blocked", "詰まったこと・相談したいこと"),
    ("tomorrow", "明日やること"),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a daily Markdown note from git log.")
    parser.add_argument("-d", "--date", dest="target_date", type=parse_date, help="Target date in YYYY-MM-DD.")
    parser.add_argument("-r", "--repo", type=Path, default=Path.cwd(), help="Single Git repository path. Defaults to current directory.")
    parser.add_argument("-w", "--workspace", type=Path, help="Scan Git repositories under this directory and create one central note.")
    parser.add_argument(
        "-o",
        "--dir",
        "--output-dir",
        dest="output_dir",
        type=Path,
        default=Path("daily"),
        help="Output directory. In repo mode, relative paths are created under the repo. In workspace mode, relative paths are created from the current directory.",
    )
    parser.add_argument("-a", "--author-email", help="Author email to use when scanning a workspace. Defaults to each repository's git config user.email.")
    parser.add_argument("-f", "--force", action="store_true", help="Overwrite an existing daily note.")
    input_group = parser.add_mutually_exclusive_group()
    input_group.add_argument("-i", "--interactive", action="store_true", help="Prompt for manual entries after creating or finding the note.")
    input_group.add_argument("--no-interactive", "--no-input", dest="no_interactive", action="store_true", help="Create or update the note without prompting.")
    parser.add_argument("--work", "--done", dest="work", action="append", help="Add a bullet under 今日やったこと. Repeatable.")
    parser.add_argument("--learned", action="append", help="Add a bullet under 学んだこと. Repeatable.")
    parser.add_argument("--blocked", "--stuck", dest="blocked", action="append", help="Add a bullet under 詰まったこと・相談したいこと. Repeatable.")
    parser.add_argument("--tomorrow", "--next", dest="tomorrow", action="append", help="Add a bullet under 明日やること. Repeatable.")
    parser.add_argument("request", nargs="*", help='Natural request such as "今日の日報", "昨日の日報 上書き", or "全体の日報".')
    return parser


def parse_args(argv: list[str] | None = None, *, today: date | None = None) -> argparse.Namespace:
    parser = build_parser()
    args = parser.parse_args(argv)
    apply_natural_request(args, today=today or date.today())
    return args


def apply_natural_request(args: argparse.Namespace, *, today: date) -> None:
    request = " ".join(args.request).strip()
    if args.target_date is None:
        args.target_date = date_from_request(request, today=today) or today
    if request and not args.force and any(term in request for term in FORCE_TERMS):
        args.force = True
    if request and args.workspace is None and any(term.lower() in request.lower() for term in WORKSPACE_TERMS):
        args.workspace = args.repo
    if request and not args.no_interactive and not args.interactive and any(term.lower() in request.lower() for term in INTERACTIVE_TERMS):
        args.interactive = True


def date_from_request(request: str, *, today: date) -> date | None:
    match = DATE_PATTERN.search(request)
    if match:
        return parse_date(match.group(0).replace("/", "-"))

    for term, offset_days in RELATIVE_DATE_TERMS:
        if term in request:
            return today + timedelta(days=offset_days)
    return None


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def section_items_from_args(args: argparse.Namespace) -> dict[str, list[str]]:
    return {
        "work": list(args.work or []),
        "learned": list(args.learned or []),
        "blocked": list(args.blocked or []),
        "tomorrow": list(args.tomorrow or []),
    }


def prompt_section_items() -> dict[str, list[str]]:
    print("日報に追記する内容を入力してください。")
    print("各項目は1行ずつ入力し、空行で次の項目へ進みます。何も入力しない項目はスキップします。")
    items = {section_key: [] for section_key, _ in SECTION_PROMPTS}
    for section_key, label in SECTION_PROMPTS:
        print(f"\n{label}")
        while True:
            try:
                value = input("> ").strip()
            except EOFError:
                print()
                return items
            if not value:
                break
            items[section_key].append(value)
    return items


def merge_section_items(base: dict[str, list[str]], extra: dict[str, list[str]]) -> None:
    for section_key, items in extra.items():
        base.setdefault(section_key, []).extend(items)


def has_section_items(section_items: dict[str, list[str]]) -> bool:
    return any(section_items.values())


def should_prompt_for_manual_entries(args: argparse.Namespace, section_items: dict[str, list[str]]) -> bool:
    if args.no_interactive:
        return False
    if args.interactive:
        return True
    if has_section_items(section_items):
        return False
    return sys.stdin.isatty()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    manual_updated = False

    try:
        if args.workspace:
            result = generate_workspace_note(
                args.workspace,
                args.target_date,
                args.output_dir,
                author_email=args.author_email,
                force=args.force,
            )
        else:
            result = generate_note(args.repo, args.target_date, args.output_dir, force=args.force)

        section_items = section_items_from_args(args)
        if should_prompt_for_manual_entries(args, section_items):
            merge_section_items(section_items, prompt_section_items())
        if has_section_items(section_items):
            manual_updated = append_daily_sections(result.path, section_items)
            if manual_updated:
                update_month_index(result.path.parent, args.target_date)
    except DailyNoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result.created:
        print(f"created: {result.path}")
    else:
        print(f"skipped existing daily note: {result.path}")
    if manual_updated:
        print(f"updated daily note: {result.path}")
    if result.index_updated:
        print(f"updated: {result.index_path}")
    return 0
