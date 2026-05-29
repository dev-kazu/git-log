# git-log

Generate daily Markdown work notes from git log.

By default, notes are written outside the repository:

```sh
~/.local/share/daily-note/
```

Set `DAILY_NOTE_DIR` to use a shared location for generated notes and future analysis tools:

```sh
export DAILY_NOTE_DIR="$HOME/daily-notes"
./gitlog 今日の日報
```

Use `--dir` when you need a one-off output directory.
