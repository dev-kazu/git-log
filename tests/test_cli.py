from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from daily_note.cli import (
    build_parser,
    default_output_dir,
    enable_prompt_line_editing,
    main,
    parse_args,
    prompt_section_items,
    section_items_from_args,
    should_prompt_for_manual_entries,
)
from daily_note.generator import DailyNote


class CliTest(unittest.TestCase):
    def test_default_output_dir_uses_app_data_directory(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch("daily_note.cli.Path.home", return_value=Path("/home/test")):
            self.assertEqual(default_output_dir(), Path("/home/test/.local/share/daily-note"))

    def test_default_output_dir_can_be_configured_with_env(self) -> None:
        with patch.dict(os.environ, {"DAILY_NOTE_DIR": "/tmp/daily-notes"}, clear=True):
            self.assertEqual(default_output_dir(), Path("/tmp/daily-notes"))

    def test_default_output_dir_uses_xdg_data_home(self) -> None:
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg-data"}, clear=True):
            self.assertEqual(default_output_dir(), Path("/tmp/xdg-data/daily-note"))

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

    def test_no_interactive_option_disables_natural_interactive_input(self) -> None:
        args = parse_args(["--no-interactive", "今日の日報", "入力"], today=date(2026, 5, 28))

        self.assertFalse(args.interactive)
        self.assertTrue(args.no_interactive)

    def test_default_prompt_starts_for_tty_without_manual_items(self) -> None:
        args = parse_args(["今日の日報"], today=date(2026, 5, 28))
        section_items = section_items_from_args(args)

        with patch("daily_note.cli.sys.stdin") as stdin:
            stdin.isatty.return_value = True
            self.assertTrue(should_prompt_for_manual_entries(args, section_items))

    def test_default_prompt_skips_non_tty_or_manual_items(self) -> None:
        args = parse_args(["今日の日報"], today=date(2026, 5, 28))
        section_items = section_items_from_args(args)

        with patch("daily_note.cli.sys.stdin") as stdin:
            stdin.isatty.return_value = False
            self.assertFalse(should_prompt_for_manual_entries(args, section_items))

        args = parse_args(["今日の日報", "--work", "CLI入力を追加"], today=date(2026, 5, 28))
        section_items = section_items_from_args(args)

        with patch("daily_note.cli.sys.stdin") as stdin:
            stdin.isatty.return_value = True
            self.assertFalse(should_prompt_for_manual_entries(args, section_items))

    def test_prompt_line_editing_imports_readline_for_tty(self) -> None:
        imported: list[str] = []
        real_import = __import__

        def fake_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            if name == "readline":
                imported.append(name)
                raise ImportError("readline unavailable")
            return real_import(name, globals, locals, fromlist, level)

        with (
            patch("daily_note.cli.PROMPT_LINE_EDITING_CONFIGURED", False),
            patch("daily_note.cli.sys.stdin") as stdin,
            patch("builtins.__import__", side_effect=fake_import),
        ):
            stdin.isatty.return_value = True
            enable_prompt_line_editing()

        self.assertEqual(imported, ["readline"])

    def test_prompt_section_items_accepts_multiple_lines_per_section(self) -> None:
        inputs = ["作業1", "作業2", "", "学び", "", "", "明日1", ""]

        with patch("builtins.input", side_effect=inputs), redirect_stdout(io.StringIO()):
            items = prompt_section_items()

        self.assertEqual(items["work"], ["作業1", "作業2"])
        self.assertEqual(items["learned"], ["学び"])
        self.assertEqual(items["blocked"], [])
        self.assertEqual(items["tomorrow"], ["明日1"])

    def test_main_displays_note_preview_before_interactive_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "daily"
            output_dir.mkdir()
            note_path = output_dir / "2026-05-28.md"
            note_path.write_text("# 日報 2026-05-28\n\n## 今日やったこと\n- 実装: add preview\n", encoding="utf-8")
            result = DailyNote(path=note_path, index_path=output_dir / "2026-05.md", created=True, index_updated=True)

            def prompt() -> dict[str, list[str]]:
                print("PROMPT START")
                return {}

            with (
                patch("daily_note.cli.generate_note", return_value=result),
                patch("daily_note.cli.sys.stdin") as stdin,
                patch("daily_note.cli.prompt_section_items", side_effect=prompt),
                redirect_stdout(io.StringIO()) as stdout,
            ):
                stdin.isatty.return_value = True
                exit_code = main(["--date", "2026-05-28", "--repo", "repo", "--dir", str(output_dir)])

            output = stdout.getvalue()
            self.assertEqual(exit_code, 0)
            self.assertIn("=== git log まとめ ===", output)
            self.assertIn("- 実装: add preview", output)
            self.assertLess(output.index("=== git log まとめ ==="), output.index("PROMPT START"))

    def test_main_prints_workbook_update_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory) / "daily"
            output_dir.mkdir()
            note_path = output_dir / "2026-05-28.md"
            note_path.write_text("# 日報 2026-05-28\n", encoding="utf-8")
            result = DailyNote(
                path=note_path,
                index_path=output_dir / "2026-05.md",
                created=True,
                index_updated=True,
                workbook_path=output_dir / "2026.xlsx",
                workbook_updated=True,
            )

            with (
                patch("daily_note.cli.generate_note", return_value=result),
                patch("daily_note.cli.sys.stdin") as stdin,
                redirect_stdout(io.StringIO()) as stdout,
            ):
                stdin.isatty.return_value = False
                exit_code = main(["--date", "2026-05-28", "--repo", "repo", "--dir", str(output_dir)])

            self.assertEqual(exit_code, 0)
            self.assertIn(f"updated: {output_dir / '2026.xlsx'}", stdout.getvalue())

    def test_natural_request_for_workspace_mode(self) -> None:
        args = parse_args(["--repo", "workspace", "全体の日報"], today=date(2026, 5, 28))

        self.assertEqual(args.workspace, Path("workspace"))


if __name__ == "__main__":
    unittest.main()
