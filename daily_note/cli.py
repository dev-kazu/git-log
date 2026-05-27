from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path
import sys

from .generator import DailyNoteError, generate_note, generate_workspace_note


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a daily Markdown note from git log.")
    parser.add_argument("--date", dest="target_date", type=parse_date, default=date.today(), help="Target date in YYYY-MM-DD.")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Single Git repository path. Defaults to current directory.")
    parser.add_argument("--workspace", type=Path, help="Scan Git repositories under this directory and create one central note.")
    parser.add_argument(
        "--dir",
        dest="output_dir",
        type=Path,
        default=Path("daily"),
        help="Output directory. In repo mode, relative paths are created under the repo. In workspace mode, relative paths are created from the current directory.",
    )
    parser.add_argument("--author-email", help="Author email to use when scanning a workspace. Defaults to each repository's git config user.email.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing daily note.")
    return parser


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

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
    except DailyNoteError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if result.created:
        print(f"created: {result.path}")
    else:
        print(f"skipped existing daily note: {result.path}")
    if result.index_updated:
        print(f"updated: {result.index_path}")
    return 0
