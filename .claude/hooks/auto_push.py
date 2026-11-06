#!/usr/bin/env python3
"""Claude Code Stop hook: commit and push changes on main to origin.

Refuses to commit if a secret could be included, and never prints a secret: only the
name of the variable or pattern and the file are reported. Never force-pushes.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
ENV_FILES = ("backend/.env", "frontend/.env.local")
SECRET_VAR = re.compile(r"KEY|TOKEN|SECRET|CHAT_ID|WEBHOOK|PASSWORD")
PATTERNS = {
    "Telegram bot token": re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "API key in a URL": re.compile(r"apiKey=[A-Za-z0-9]{10,}"),
}
FORBIDDEN_PATH = re.compile(r"(^|/)\.env(\.local)?$|\.db(-shm|-wal)?$|\.sqlite3?$|(^|/)logs/|\.pem$")
TRAILER = "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0",
           "GIT_SSH_COMMAND": "ssh -o BatchMode=yes -o ConnectTimeout=15"}


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, env=GIT_ENV, capture_output=True, text=True, errors="replace")


def say(message):
    print(json.dumps({"systemMessage": f"GitHub auto-push: {message}"}))
    sys.exit(0)


def secret_values():
    values = {}
    for name in ENV_FILES:
        try:
            lines = open(os.path.join(ROOT, name)).read().splitlines()
        except OSError:
            continue
        for line in lines:
            m = re.match(r"\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.+?)\s*$", line)
            if m and SECRET_VAR.search(m[1]):
                value = m[2].strip("\"'")
                if len(value) >= 5:
                    values[m[1]] = value
    return values


def find_problem(paths):
    for path in paths:
        if FORBIDDEN_PATH.search(path) and not path.endswith(".env.example"):
            return f"{path} must not be committed"
    values = secret_values()
    current = "?"
    for line in git("diff", "--cached", "--text", "--unified=0").stdout.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
        elif line.startswith("+"):
            for name, value in values.items():
                if value in line:
                    return f"the value of {name} appears in {current}"
            for name, pattern in PATTERNS.items():
                if pattern.search(line):
                    return f"a possible {name} appears in {current}"
    return None


def main():
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        sys.exit(0)
    if git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() != "main":
        sys.exit(0)  # only main is pushed automatically
    git_dir = git("rev-parse", "--absolute-git-dir").stdout.strip()
    if any(os.path.exists(os.path.join(git_dir, p)) for p in ("MERGE_HEAD", "rebase-merge", "rebase-apply", "CHERRY_PICK_HEAD")):
        say("skipped because a merge or rebase is in progress.")

    git("add", "-A")
    paths = [p for p in git("diff", "--cached", "--name-only").stdout.splitlines() if p]
    if paths:
        problem = find_problem(paths)
        if problem:
            git("reset", "-q")
            say(f"NOT committed or pushed: {problem}. Your files are unchanged.")
        shown = ", ".join(paths[:5]) + (f" and {len(paths) - 5} more" if len(paths) > 5 else "")
        message = f"Update {len(paths)} file{'s' if len(paths) != 1 else ''}: {shown}"[:200]
        done = git("commit", "-q", "-m", message, "-m", TRAILER)
        if done.returncode != 0:
            git("reset", "-q")
            say("commit failed, so nothing was pushed.")

    if git("rev-list", "--count", "@{u}..HEAD").stdout.strip() == "0":
        sys.exit(0)  # nothing new to push
    push = git("push", "origin", "main")
    if push.returncode != 0:
        say("push failed. The commit is saved locally and will be retried next time.")
    head = git("rev-parse", "--short", "HEAD").stdout.strip()
    say(f"pushed {head} to origin/main.")


if __name__ == "__main__":
    main()
