from __future__ import annotations

from datetime import date
from pathlib import Path
import unittest

from daily_note.cli import build_parser, parse_args


class CliTest(unittest.TestCase):
    def test_short_options_for_single_repo_mode(self) -> None:
        args = build_parser().parse_args(["-d", "2026-05-27", "-r", "repo", "-o", "notes", "-f"])

        self.assertEqual(args.target_date, date(2026, 5, 27))
        self.assertEqual(args.repo, Path("repo"))
        self.assertEqual(args.output_dir, Path("notes"))
        self.assertTrue(args.force)

    def test_short_options_for_workspace_mode(self) -> None:
        args = build_parser().parse_args(["-w", "workspace", "-a", "me@example.com", "--output-dir", "daily"])

        self.assertEqual(args.workspace, Path("workspace"))
        self.assertEqual(args.author_email, "me@example.com")
        self.assertEqual(args.output_dir, Path("daily"))

    def test_natural_request_for_today(self) -> None:
        args = parse_args(["今日の日報"], today=date(2026, 5, 28))

        self.assertEqual(args.target_date, date(2026, 5, 28))

    def test_natural_request_for_yesterday_and_force(self) -> None:
        args = parse_args(["昨日の日報", "上書き"], today=date(2026, 5, 28))

        self.assertEqual(args.target_date, date(2026, 5, 27))
        self.assertTrue(args.force)

    def test_natural_request_for_explicit_date(self) -> None:
        args = parse_args(["2026/05/27", "の日報"], today=date(2026, 5, 28))

        self.assertEqual(args.target_date, date(2026, 5, 27))

    def test_explicit_date_option_wins_over_natural_request(self) -> None:
        args = parse_args(["--date", "2026-05-20", "昨日の日報"], today=date(2026, 5, 28))

        self.assertEqual(args.target_date, date(2026, 5, 20))

    def test_manual_entry_options(self) -> None:
        args = parse_args(
            [
                "今日の日報",
                "--work",
                "CLI入力を追加",
                "--learned",
                "argparse の append を使った",
                "--blocked",
                "特になし",
                "--tomorrow",
                "テストを追加する",
            ],
            today=date(2026, 5, 28),
        )

        self.assertEqual(args.work, ["CLI入力を追加"])
        self.assertEqual(args.learned, ["argparse の append を使った"])
        self.assertEqual(args.blocked, ["特になし"])
        self.assertEqual(args.tomorrow, ["テストを追加する"])

    def test_natural_request_for_interactive_input(self) -> None:
        args = parse_args(["今日の日報", "入力"], today=date(2026, 5, 28))

        self.assertTrue(args.interactive)

    def test_natural_request_for_workspace_mode(self) -> None:
        args = parse_args(["--repo", "workspace", "全体の日報"], today=date(2026, 5, 28))

        self.assertEqual(args.workspace, Path("workspace"))


if __name__ == "__main__":
    unittest.main()
