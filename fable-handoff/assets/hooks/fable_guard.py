#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""PreToolUse hook for a fable-handoff run.

Blocks two things, using the lists in fable/handoff.json:

1. A file write (Write, Edit, MultiEdit, NotebookEdit) to a protected path,
   or to a path outside the project.
2. A shell command (Bash) that matches a blocked pattern, or that would
   write to, move or delete a protected path.

Exit 0 lets the tool call proceed. Exit 2 blocks it, and the text written to
stderr is shown to the model. The hook does nothing when the project has no
fable/handoff.json.

The shell check reads the command as text. It is a second layer behind the
permission mode, not a shell parser and not a sandbox. Two refinements keep
it from blocking harmless work:

- A `cd` is followed. A command joined to it by && is checked against the
  new directory only. After any other separator the old directories count as
  well, because the cd may have failed.
- Quoted text that holds whitespace, and the body of a heredoc, are mentions.
  They are not matched against the blocked patterns, unless the command line
  hands text to something that runs it (see RUNS_TEXT).
"""
from __future__ import annotations

import json
import os
import re
import sys

# Tool name -> the key in tool_input that holds the path being written.
WRITE_TOOLS = {
    "Write": "file_path",
    "Edit": "file_path",
    "MultiEdit": "file_path",
    "NotebookEdit": "notebook_path",
}

# Shell tools. On Windows without Git Bash, Claude Code runs commands through
# PowerShell instead of Bash, with the same `command` field.
SHELL_TOOLS = {"Bash", "PowerShell"}

# Words that can stand in front of the real command name.
PREFIX_WORDS = {
    "env", "time", "nice", "nohup", "command", "builtin", "exec", "xargs",
    "if", "then", "else", "elif", "do", "while", "until", "!", "{",
}
# Commands whose every path argument is deleted or changed in place.
REMOVE_COMMANDS = {"rm", "rmdir", "unlink", "shred", "chmod", "chown", "chgrp"}
CHANGE_COMMANDS = {"truncate", "touch", "tee"}
# Commands that write only to their last path argument.
COPY_COMMANDS = {"cp", "ln", "install", "rsync", "scp"}
SHELLS = {"bash", "sh", "zsh", "dash", "ksh"}
# Commands that run text they are given: as shell commands, on another machine
# or as another user, or as SQL. On a command line that uses one of them,
# quoted text and heredoc bodies are checked as commands, not read as mentions.
RUNS_TEXT = SHELLS | {
    "eval", "trap", "watch", "ssh", "su",
    "psql", "mysql", "mariadb", "sqlite3", "sqlcmd", "duckdb",
}


# --------------------------------------------------------------- locating

def read_payload():
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def find_project(payload):
    """Return the first candidate directory that holds fable/handoff.json."""
    candidates = [os.environ.get("CLAUDE_PROJECT_DIR"), payload.get("cwd"), os.getcwd()]
    for candidate in candidates:
        if candidate and os.path.isfile(os.path.join(candidate, "fable", "handoff.json")):
            return os.path.realpath(candidate)
    return None


# --------------------------------------------------------------- messages

def block(reason, advice=""):
    lines = [
        "Blocked by the handoff guard: " + reason,
        "",
        "This is a deliberate limit that the project owner set before the run. It is not an",
        "error to fix. Do not look for another way to reach the same result, such as a",
        "different command, a script or another tool.",
    ]
    if advice:
        lines += ["", advice]
    lines += [
        "",
        "What to do now: if the mission cannot be completed without this action, note it in",
        'fable/DECISIONS.md under "Left for the owner" with what you needed and why. Then',
        "continue with the rest of the work.",
    ]
    sys.stderr.write("\n".join(lines) + "\n")
    sys.exit(2)


def block_broken_config(error):
    sys.stderr.write(
        "Blocked by the handoff guard: fable/handoff.json cannot be used (%s).\n"
        "\n"
        "Without it the guard cannot tell which paths and commands are protected, so it is\n"
        "blocking every file write and shell command. You cannot repair this from inside the\n"
        "run, because that file is protected and only the owner may change it.\n"
        "\n"
        "What to do now: stop working and end your turn. Say in your final message that the\n"
        "handoff configuration is broken and quote the error above.\n" % error
    )
    sys.exit(2)


# --------------------------------------------------------------- config

def translate_glob(glob):
    """Regex text for one glob: ** crosses directories, * and ? stay in a segment."""
    out, i = [], 0
    while i < len(glob):
        if glob.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif glob.startswith("**", i):
            out.append(".*")
            i += 2
        elif glob[i] == "*":
            out.append("[^/]*")
            i += 1
        elif glob[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(glob[i]))
            i += 1
    return "".join(out)


class Protected:
    """The protected globs from the config, compiled gitignore style.

    A pattern without a slash matches at any depth. A pattern with a slash is
    anchored at the project root. A match on a directory covers everything
    under it. Matching ignores case, because macOS and Windows file systems do.
    """

    def __init__(self, patterns):
        self.rules = []      # (pattern as written, compiled regex)
        self.samples = []    # one example path per pattern, for shell wildcards
        self.parents = set() # directories that contain an anchored protected path
        for pattern in patterns:
            if not isinstance(pattern, str):
                raise ValueError("protected_paths must be a list of strings")
            anchored = "/" in pattern.strip().rstrip("/")
            core = pattern.strip().strip("/")
            while core.endswith("/**"):
                core = core[:-3]
            if not core:
                continue
            prefix = "" if anchored else "(?:.*/)?"
            regex = re.compile("^" + prefix + translate_glob(core) + "(?:/.*)?$", re.IGNORECASE)
            self.rules.append((pattern, regex))
            sample = core.replace("**/", "").replace("*", "x").replace("?", "x").lower()
            self.samples.append((pattern, sample))
            if anchored:
                parts = sample.split("/")
                for depth in range(1, len(parts)):
                    self.parents.add("/".join(parts[:depth]))

    def match(self, rel, removes=False):
        """Return a phrase that says why `rel` is protected, or None when it is not.

        `rel` is a path relative to the project, with "/" separators. With
        `removes`, a directory that contains a protected path also counts,
        because deleting or moving the directory takes the path with it.
        """
        for pattern, regex in self.rules:
            if regex.match(rel):
                return "it matches %r in protected_paths" % pattern
        lowered = rel.lower()
        if "*" in rel or "?" in rel:
            # A shell wildcard such as fable/* or .env*: test it against examples.
            wildcard = re.compile("^" + translate_glob(lowered) + "$")
            for pattern, sample in self.samples:
                if wildcard.match(sample):
                    return "the wildcard can reach paths that match %r in protected_paths" % pattern
            if removes:
                for parent in self.parents:
                    if wildcard.match(parent):
                        return "the wildcard can reach %s/, which holds paths listed in protected_paths" % parent
        elif removes and (lowered in ("", ".") or lowered in self.parents):
            return "that directory holds paths listed in protected_paths"
        return None


COMPANION_ROOTS = []


def load_config(project):
    with open(os.path.join(project, "fable", "handoff.json"), encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("the file does not hold a JSON object")
    paths = config.get("protected_paths", [])
    patterns = config.get("blocked_bash_patterns", [])
    if not isinstance(paths, list) or not isinstance(patterns, list):
        raise ValueError("protected_paths and blocked_bash_patterns must be lists")
    blocked = []
    for pattern in patterns:
        try:
            blocked.append((pattern, re.compile(pattern, re.IGNORECASE)))
        except (re.error, TypeError) as error:
            raise ValueError("invalid regex %r in blocked_bash_patterns: %s" % (pattern, error))
    # Companion repositories: other git repositories one run works in on its
    # own branch (for example a firm's app beside its data repository). Writes
    # inside them are allowed; protected_paths apply inside them as well.
    companions = config.get("companion_repositories") or []
    if not isinstance(companions, list):
        raise ValueError("companion_repositories must be a list")
    COMPANION_ROOTS[:] = [os.path.realpath(os.path.expanduser(str(c.get("path")))) for c in companions if isinstance(c, dict) and c.get("path")]
    if config.get("allow_writes_outside_project", False) is True:
        return Protected(paths), blocked, True
    # Named files outside the project the owner's rules require the run to
    # write (for example a firm-wide task log). Exact files only, no globs.
    named = config.get("writable_outside_paths") or []
    if not isinstance(named, list):
        raise ValueError("writable_outside_paths must be a list of file paths")
    return Protected(paths), blocked, [os.path.realpath(os.path.expanduser(str(x))) for x in named if str(x).strip()]


# --------------------------------------------------------------- paths

def relative_to_project(project, path, base):
    """Project-relative form of `path`, or None when it lies outside the project."""
    full = os.path.realpath(os.path.join(base, path))
    if full == project:
        return ""
    if full.startswith(project + os.sep):
        return os.path.relpath(full, project).replace(os.sep, "/")
    return None


def check_file_write(project, protected, allow_outside, path, base):
    rel = relative_to_project(project, os.path.expanduser(path), base)
    if rel is None:
        if allow_outside is True:
            return
        full = os.path.realpath(os.path.join(base, os.path.expanduser(path)))
        if isinstance(allow_outside, list) and full in allow_outside:
            return
        for root in COMPANION_ROOTS:
            if full.startswith(root + os.sep):
                reason = protected.match(os.path.relpath(full, root).replace(os.sep, "/"))
                if reason:
                    block("%s is protected in the companion repository %s: %s of fable/handoff.json." % (path, root, reason))
                return
        block(
            "%s is outside the project, and this run may only write inside it." % path,
            "Keep new files, including scratch files, inside the project directory.",
        )
    reason = protected.match(rel)
    if reason:
        block("%s is protected: %s of fable/handoff.json." % (rel, reason))


# --------------------------------------------------------------- shell commands

def strip_heredocs(command):
    """Drop heredoc bodies. They are data for the command, not commands.

    Two kinds of body are kept and read as commands. One is a body fed to a
    shell (bash <<EOF), because the shell runs it. The other is a body with no
    closing tag, so that text which only looks like a heredoc cannot hide the
    lines after it.
    """
    lines = command.split("\n")
    kept, i = [], 0
    while i < len(lines):
        line = lines[i]
        kept.append(line)
        i += 1
        for found in re.finditer(r"(?<!<)<<(?!<)-?\s*(['\"]?)([A-Za-z_]\w*)\1", line):
            end = i
            while end < len(lines) and lines[end].strip() != found.group(2):
                end += 1
            if end == len(lines) or uses(line, SHELLS):
                break  # keep the body: the loop goes on to read it line by line
            i = end + 1  # skip the body and the closing tag
    return "\n".join(kept)


def split_commands(command):
    """Split a command line into simple commands.

    Returns a list of commands. Each command is a list of (kind, text) pairs,
    where kind is "word", "write" (an output redirect; the next word is its
    target) or "read" (an input redirect; the next word is not a write).
    Quotes are honored, so a quoted string stays one word.

    A command joined to the one before it by && starts with an ("and", "&&")
    pair: it runs only when that command worked, and in the same directory.
    The pair is left out after a ( ) group or a `...` substitution, because a
    cd inside the group ends with the group.
    """
    commands, tokens = [], []
    word = None  # None means "not inside a word"
    chained = False  # the command being read follows && in the same shell
    after_group = False  # a ( ) group or `...` closed since the last separator
    i, n = 0, len(command)

    def end_word():
        nonlocal word
        if word is not None:
            tokens.append(("word", word))
            word = None

    def end_command():
        nonlocal tokens, chained
        end_word()
        if tokens:
            commands.append(([("and", "&&")] if chained else []) + tokens)
            tokens, chained = [], False

    while i < n:
        char = command[i]
        if char == "\\" and i + 1 < n:
            if command[i + 1] != "\n":
                word = (word or "") + command[i + 1]
            i += 2
        elif char == "'":
            close = command.find("'", i + 1)
            close = n if close < 0 else close
            word = (word or "") + command[i + 1:close]
            i = close + 1
        elif char == '"':
            j, text = i + 1, ""
            while j < n and command[j] != '"':
                if command[j] == "\\" and j + 1 < n:
                    j += 1
                text += command[j]
                j += 1
            word = (word or "") + text
            i = j + 1
        elif char in " \t":
            end_word()
            i += 1
        elif char == "#" and word is None:
            while i < n and command[i] != "\n":
                i += 1
        elif char in ";\n()`":
            end_command()
            after_group = char in ")`"
            i += 1
        elif char == "|":
            end_command()
            after_group = False
            i += 2 if command[i:i + 2] in ("||", "|&") else 1
        elif char == "&" and command.startswith("&>", i):
            end_word()
            tokens.append(("write", "&>"))
            i += 3 if command.startswith("&>>", i) else 2
        elif char == "&":
            # && joins two commands only when a command stands in front of it.
            joins = command.startswith("&&", i) and not after_group and bool(tokens or word is not None)
            end_command()
            chained = joins
            after_group = False
            i += 2 if command.startswith("&&", i) else 1
        elif char == ">":
            if word is not None and word.isdigit():
                word = None  # a file descriptor number, as in 2>file
            end_word()
            j = i + 1
            if j < n and command[j] in ">|":
                j += 1
            if j < n and command[j] == "&":
                descriptor = re.match(r"(\d+|-)(?=[\s;|&)<>]|$)", command[j + 1:])
                if descriptor:  # 2>&1 or >&-: between descriptors, not a file
                    i = j + 1 + descriptor.end()
                    continue
                j += 1
            tokens.append(("write", ">"))
            i = j
        elif char == "<":
            if word is not None and word.isdigit():
                word = None
            end_word()
            tokens.append(("read", "<"))
            i += re.match(r"<<<|<<-?|<&|<", command[i:]).end()
        else:
            word = (word or "") + char
            i += 1
    end_command()
    return commands


def uses(text, names):
    """True when one of the command names in `names` is a word of its own in `text`."""
    for tokens in split_commands(text):
        for kind, word in tokens:
            if kind == "word" and os.path.basename(word) in names:
                return True
    return False


def hide_quoted_text(command):
    """Empty every quoted string that holds whitespace. Such text is a mention.

    A commit message or a grep pattern can name a forbidden command without
    running it. Quoted text stays in place where the shell may still run it:
    a single word such as "main", the value of a variable (CMD="..."), and a
    double-quoted string with a command substitution in it. From such a
    string onward the rest of the command stays as it is, because nested
    quotes can no longer be told apart. The same holds for an unclosed quote
    and for the $'...' form.
    """
    out, i, n = [], 0, len(command)
    while i < n:
        char = command[i]
        if char == "\\":
            out.append(command[i:i + 2])
            i += 2
        elif char == "#" and (i == 0 or command[i - 1] in " \t\n;&|()"):
            # A comment runs to the end of the line. Quotes in it do not count.
            end = command.find("\n", i)
            end = n if end < 0 else end
            out.append(command[i:end])
            i = end
        elif char in "'\"":
            close = i + 1
            while close < n and command[close] != char:
                close += 2 if char == '"' and command[close] == "\\" else 1
            text = command[i + 1:close]
            substitution = char == '"' and ("$(" in text or "`" in text)
            if close >= n or substitution or command[i - 1:i] == "$":
                out.append(command[i:])
                break
            is_value = re.search(r"(?:^|[\s;&|(])[A-Za-z_]\w*\+?=\S*$", command[:i])
            if re.search(r"\s", text) and not is_value:
                text = ""
            out.append(char + text + char)
            i = close + 1
        else:
            out.append(char)
            i += 1
    return "".join(out)


def positional(args):
    """Arguments that are not flags. Everything after "--" counts."""
    out = []
    for index, arg in enumerate(args):
        if arg == "--":
            return out + args[index + 1:]
        if not arg.startswith("-") or arg == "-":
            out.append(arg)
    return out


def value_after(args, flags):
    for index, arg in enumerate(args[:-1]):
        if arg in flags:
            return args[index + 1]
    return None


def write_targets(tokens, depth=0):
    """Paths that one simple command would write, move or delete.

    Returns (path, removes) pairs. `removes` is True when the command deletes
    or moves the path, so that a parent directory of a protected file counts.
    """
    targets, words = [], []
    previous = "word"
    for kind, text in tokens:
        if kind == "and":
            continue  # the && marker says how the command is joined, not what it writes
        if kind == "word":
            if previous == "write":
                targets.append((text, False))
            elif previous == "word":
                words.append(text)
        previous = kind

    while words and (re.match(r"^[A-Za-z_]\w*=", words[0]) or words[0] in PREFIX_WORDS):
        words = words[1:]
    if not words:
        return targets
    name, args = os.path.basename(words[0]), words[1:]
    paths = positional(args)

    if name in REMOVE_COMMANDS:
        targets += [(path, True) for path in paths]
    elif name in CHANGE_COMMANDS:
        targets += [(path, False) for path in paths]
    elif name == "mv":
        directory = value_after(args, ("-t", "--target-directory"))
        if directory:
            targets += [(path, True) for path in paths if path != directory] + [(directory, False)]
        elif len(paths) >= 2:
            targets += [(path, True) for path in paths[:-1]] + [(paths[-1], False)]
    elif name in COPY_COMMANDS:
        directory = value_after(args, ("-t", "--target-directory"))
        if directory:
            targets.append((directory, False))
        elif len(paths) >= 2:
            targets.append((paths[-1], False))
    elif name in ("sed", "perl"):
        in_place = any(re.match(r"^-[A-Za-z]*i", arg) or arg.startswith("--in-place") for arg in args)
        if in_place:
            # The script is the word after -e or -f, or else the first plain word.
            scripts = [args[k + 1] for k, arg in enumerate(args[:-1]) if arg in ("-e", "-f", "--expression", "--file")]
            files = [path for path in paths if path not in scripts] if scripts else paths[1:]
            targets += [(path, False) for path in files]
    elif name == "dd":
        targets += [(arg[3:], False) for arg in args if arg.startswith("of=")]
    elif name == "git":
        k = 0
        while k < len(args) and args[k].startswith("-"):
            k += 2 if args[k] in ("-C", "-c", "--git-dir", "--work-tree") else 1
        subcommand = args[k] if k < len(args) else ""
        rest = positional(args[k + 1:])
        if subcommand in ("rm", "mv"):
            targets += [(path, True) for path in rest]
        elif subcommand in ("checkout", "restore"):
            targets += [(path, False) for path in rest]
    elif name in SHELLS and depth < 3:
        script = value_after(args, ("-c",))
        if script:
            for inner in split_commands(strip_heredocs(script)):
                targets += write_targets(inner, depth + 1)
    elif name == "eval" and depth < 3:
        for inner in split_commands(" ".join(args)):
            targets += write_targets(inner, depth + 1)
    return targets


def expand(path, project, cwd):
    home = os.path.expanduser("~")
    for variable, value in (("CLAUDE_PROJECT_DIR", project), ("HOME", home), ("PWD", cwd)):
        path = path.replace("${%s}" % variable, value).replace("$" + variable, value)
    return os.path.expanduser(path)


def plain_words(tokens):
    """The words of one command, without the targets of its redirects."""
    words, previous = [], "word"
    for kind, text in tokens:
        if kind == "word" and previous not in ("write", "read"):
            words.append(text)
        previous = kind
    return words


def cd_target(words, project, cwd):
    """The directory that a cd, pushd or popd command goes to, or None when the text does not say."""
    paths = positional(words[1:])
    if words[0] == "popd" or len(paths) != 1:
        return None
    target = expand(paths[0], project, cwd)
    # "cd -", "pushd +1", and a variable or wildcard that is still in the path.
    if target[:1] in ("-", "+", "~") or re.search(r"[$`*?\[{]", target):
        return None
    return target


def check_bash(project, protected, blocked, command, cwd):
    # Heredoc bodies and quoted text only mention things, so they are taken
    # out before the patterns are tried. A command line that hands text to
    # something that runs it (bash -c, eval, psql) is checked whole instead.
    code = strip_heredocs(command)
    checked = command if uses(code, RUNS_TEXT) else hide_quoted_text(code)
    for pattern, regex in blocked:
        found = regex.search(checked)
        if found:
            block(
                "the command contains `%s`, which matches the pattern `%s` in blocked_bash_patterns of fable/handoff.json."
                % (found.group(0).strip()[:80], pattern),
                "If the command only mentions this text, reword it, send the mention in a command of\n"
                "its own, or write the file with the Write tool. A mention inside a quoted message or\n"
                "a heredoc body passes, except on a command line that also runs a shell, eval or a\n"
                "database client, in the value of a variable, and in a string that holds a command\n"
                "substitution. If the command would really do this, it is forbidden for this run.",
            )

    # `seen` holds every directory a command might run in: the session
    # directory, the project root and every directory the command changes
    # into. A relative path is tried against all of them and any hit counts,
    # because a cd can fail. The exception is a command joined to a cd by &&.
    # It runs only when the cd worked, so only the new directory counts.
    seen = [cwd]
    if project not in seen:
        seen.append(project)
    bases = list(seen)
    for tokens in split_commands(code):
        if tokens[0][0] != "and":
            bases = list(seen)
        for path, removes in write_targets(tokens):
            expanded = expand(path, project, cwd)
            for base in bases:
                full = os.path.realpath(os.path.join(base, expanded))
                if removes and project.startswith(full.rstrip(os.sep) + os.sep):
                    block("the command would delete or move %s, which contains this project." % path)
                rel = relative_to_project(project, expanded, base)
                if rel is None:
                    for root in COMPANION_ROOTS:
                        crel = relative_to_project(root, expanded, base)
                        if crel is not None and protected.match(crel, removes):
                            block("the command would write to, move or delete %s, which is protected in the companion repository %s." % (path, root),
                                  "Reading a protected file or copying it elsewhere is allowed. Changing it is not.")
                    continue
                reason = protected.match(rel, removes)
                if reason:
                    block(
                        "the command would write to, move or delete %s. That is protected: %s of fable/handoff.json."
                        % (path, reason),
                        "Reading a protected file or copying it elsewhere is allowed. Changing it is not.",
                    )
        words = plain_words(tokens)
        if words and words[0] in ("cd", "pushd", "popd"):
            target = cd_target(words, project, cwd)
            if target is None:
                bases = list(seen)  # it could be any directory seen so far
                continue
            # dict.fromkeys drops duplicates and keeps the order.
            bases = list(dict.fromkeys(os.path.normpath(os.path.join(base, target)) for base in bases))
            for base in bases:
                if base not in seen and len(seen) < 12:
                    seen.append(base)


def main():
    payload = read_payload()
    project = find_project(payload)
    if project is None:
        return 0
    tool = payload.get("tool_name")
    if tool not in SHELL_TOOLS and tool not in WRITE_TOOLS:
        return 0
    try:
        protected, blocked, allow_outside = load_config(project)
    except (OSError, ValueError) as error:
        block_broken_config(error)

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        tool_input = {}
    cwd = payload.get("cwd") or project
    if tool in SHELL_TOOLS:
        command = tool_input.get("command")
        if isinstance(command, str) and command.strip():
            check_bash(project, protected, blocked, command, cwd)
    else:
        # NotebookEdit's field is not in the hooks reference, so accept either name.
        path = tool_input.get(WRITE_TOOLS[tool]) or tool_input.get("file_path")
        if isinstance(path, str) and path:
            check_file_write(project, protected, allow_outside, path, cwd)
    return 0


if __name__ == "__main__":
    sys.exit(main())
