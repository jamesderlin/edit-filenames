#!/usr/bin/env python3

# edit-move
# Copyright (C) 2020 James D. Lin <jameslin@cal.berkeley.edu>
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
"""TODO"""

import contextlib
import getopt
import os
import readline  # pylint: disable=unused-import  # noqa: F401  # Imported for side-effect.
import shlex
import string
import subprocess
import sys
import tempfile


class AbortError(Exception):
    """
    A simple exception class to abort program execution.

    If `cancelled` is True, no error message should be printed.
    """
    def __init__(self, message=None, cancelled=False, exit_code=1):
        super().__init__(message or ("Cancelled."
                                     if cancelled
                                     else "Unknown error"))
        assert exit_code != 0
        self.cancelled = cancelled
        self.exit_code = exit_code


class RestartEdit(Exception):
    """
    TODO
    """
    def __init__(self, paths_to_edit):
        super().__init__()
        self.paths_to_edit = paths_to_edit


def prompt(message, choices, default=None):
    """
    TODO
    """
    assert choices
    choices = [(choice.strip().lower(), choice) for choice in choices]

    while True:
        try:
            response = input(message)
            response = (response.strip().lower(), response)
        except EOFError:
            print()
            raise AbortError(cancelled=True) from None

        if not response[0]:
            if default:
                return default
            continue

        if response[0] == "?":
            continue

        selected_choices = []
        for choice in choices:
            if choice[0].startswith(response[0]):
                selected_choices.append(choice)

        if not selected_choices:
            print(f"Invalid choice: {response[1]}", file=sys.stderr)
        elif len(selected_choices) == 1:
            return selected_choices[0][1]
        else:
            print(f"Ambiguous choice: {response[1]}", file=sys.stderr)


def run_editor(file_path, line_number=None, editor=None):
    """
    Open the specified file in an editor at the specified line number, if
    provided.

    The launched editor will be chosen from, in order:

    1. Command-line option.
    2. The `VISUAL` environment variable.
    3. The `EDITOR` environment variable.
    4. Hard-coded paths to common editors.
    """
    options = []
    use_posix_style = True

    if not editor:
        editor = (os.environ.get("VISUAL")
                  or os.environ.get("EDITOR"))

    if editor:
        (editor, *options) = shlex.split(editor, posix=(os.name == 'posix'))

    if not editor:
        if os.name == "posix":
            editor = "vi"
        elif os.name == "nt":
            editor = "notepad.exe"
            line_number = None
            use_posix_style = False
        else:
            raise AbortError("Unable to determine what text editor to use.  "
                             "Set the EDITOR environment variable.")

    if line_number:
        editor_name = os.path.basename(editor)
        if editor_name in ("sublime_text", "code"):
            file_path = f"{file_path}:{line_number}"
        else:
            options.append(f"+{line_number}")
    if use_posix_style and file_path.startswith("-"):
        options.append("--")

    subprocess.run((editor, *options, file_path), check=True)


def extract_file_paths(lines):
    """
    TODO
    """
    # Ignore trailing blank lines.
    for last_line in reversed(range(len(lines))):
        if lines[last_line].strip():
            break
    else:
        last_line = 0

    # Ignore instructions.
    for first_line in reversed(range(last_line)):
        if not lines[first_line].strip():
            first_line += 1
            break
    else:
        first_line = 0

    return [lines[i].rstrip("\n") for i in range(first_line, last_line + 1)]


def edit_paths(paths, *, editor=None):
    """
    TODO
    """
    horizontal_rule = "*" * 70
    instructions = [
        horizontal_rule,
        "* INSTRUCTIONS:",
        "*",
        "* Edit file paths below to move or rename the corresponding files.",
        "*",
        "* Do NOT add or remove any lines.",
        "*",
        horizontal_rule,
        "",
    ]

    with contextlib.ExitStack() as exitStack:
        file = tempfile.NamedTemporaryFile(mode="w", prefix="edit-move-",
                                           delete=False, encoding="utf8")
        exitStack.callback(lambda: os.remove(file.name))

        for line in instructions:
            print(line, file=file)

        for path in paths:
            print(path, file=file)
        file.close()

        try:
            run_editor(file.name, line_number=len(instructions) + 1,
                       editor=editor)
        except subprocess.CalledProcessError as e:
            raise AbortError(f"Failed to execute editor: {e.cmd}",
                             exit_code=e.returncode) from e

        with open(file.name, "r", encoding="utf8") as f:
            return extract_file_paths(f.readlines())


def to_printable(s):
    """Returns a printable version of the specified string."""
    def replacement_char(c):
        if c in "\r\n":
            return " "
        elif ord(c) < ord(" "):
            # Remove control characters.
            return ""
        else:
            return c

    return "".join((replacement_char(c) for c in s))


def directory_components(path):
    """
    Splits a path into individual directory components.

    Example:
    directory_components("/foo/bar/baz") => ["/", "foo", "bar", "baz"]
    """
    components = []
    head = path
    while head:
        (head, tail) = os.path.split(head)
        if not tail:
            # Root directory.
            components.append(head)
            break
        components.append(tail)
    components.reverse()
    return components


def move_file(original_path, new_path):
    """
    TODO
    """
    def undo_mkdir(path):
        return lambda: os.rmdir(path)

    undo_stack = []

    components = directory_components(os.path.dirname(new_path))
    ancestor_path = ""
    for component in components:
        ancestor_path = os.path.join(ancestor_path, component)
        if not os.path.exists(ancestor_path):
            os.mkdir(ancestor_path)
            undo_stack.append(undo_mkdir(ancestor_path))

    os.rename(original_path, new_path)
    undo_stack.append(lambda: os.rename(new_path, original_path))
    return undo_stack


class EditMoveContext:
    """
    TODO
    """
    def __init__(self):
        self.original_paths = None
        self.previous_paths = None
        self.new_paths = None
        self.source_destination_list = None


def check_whitespace(ctx):
    """
    TODO
    """
    whitespace_characters = tuple(string.whitespace)
    has_trailing_whitespace = any((path.endswith(whitespace_characters)
                                   for path in ctx.new_paths))

    if not has_trailing_whitespace:
        return

    print("Lines with trailing whitespace detected.", file=sys.stderr)
    response = prompt("s: Strip trailing whitespace (default)\n"
                      "p: Preserve all whitespace\n"
                      "e: Edit\n"
                      "q: Quit\n"
                      "? [s] ",
                      ("strip", "preserve", "edit", "quit"),
                      default="strip")
    if response == "strip":
        ctx.new_paths = [path.rstrip() for path in ctx.new_paths]
    elif response == "edit":
        raise RestartEdit(ctx.new_paths)
    elif response == "quit":
        raise AbortError(cancelled=True)
    else:
        assert response == "preserve"


def check_collisions(ctx):
    """
    TODO
    """
    destination_paths = set()
    for (_, new_path) in ctx.source_destination_list:
        if new_path not in destination_paths:
            destination_paths.add(new_path)
        else:
            print(f"\"{new_path}\" already used as a destination.",
                  file=sys.stderr)

    if len(destination_paths) == len(ctx.source_destination_list):
        return

    response = prompt("r: Restart (default)\n"
                      "q: Quit\n"
                      "? [r] ",
                      ("restart", "quit"),
                      default="restart")
    if response == "restart":
        raise RestartEdit(ctx.previous_paths)
    else:
        assert response == "quit"
        raise AbortError(cancelled=True)


def check_paths(ctx):
    """
    TODO
    """
    if not ctx.new_paths:
        raise AbortError("Cancelling due to an empty file list.")

    if len(ctx.original_paths) != len(ctx.new_paths):
        print("Lines added or removed.", file=sys.stderr)
        response = prompt("r: Restart (default)\n"
                          "q: Quit\n"
                          "? [r] ",
                          ("restart", "quit"),
                          default="restart")
        if response == "quit":
            raise AbortError(cancelled=True)
        else:
            assert response == "restart"
            raise RestartEdit(ctx.previous_paths)

    check_whitespace(ctx)

    # Filter out unchanged paths.
    ctx.source_destination_list = [
        (original_path, new_path)
        for (original_path, new_path) in zip(ctx.original_paths, ctx.new_paths)
        if original_path != new_path
    ]

    if not ctx.source_destination_list:
        print("Nothing to do.", file=sys.stderr)
        raise AbortError(cancelled=True)

    check_collisions(ctx)


def preview_renames(ctx):
    """
    TODO
    """
    print("The following files will be moved/renamed:")
    for (original, new_path) in ctx.source_destination_list:
        print(f"  \"{original}\" => \"{new_path}\"")
    response = prompt("p: Proceed (default)\n"
                      "e: Edit\n"
                      "q: Quit\n"
                      "? [p] ",
                      ("proceed", "edit", "quit"),
                      default="proceed")
    if response == "quit":
        raise AbortError(cancelled=True)
    elif response == "edit":
        raise RestartEdit(ctx.new_paths)
    else:
        assert response == "proceed"


def rename_files(ctx):
    """
    TODO
    """
    undo_stack = []
    failures = []
    for (original_path, new_path) in ctx.source_destination_list:
        try:
            undo_stack += move_file(original_path, new_path)
        except OSError as e:
            failures.append((original_path, new_path, e))

    if not failures:
        return

    for (original_path, new_path, e) in failures:
        print(f"Failed to move \"{original_path}\" to \"{new_path}\": "
              f"{e.strerror} (error code: {e.errno})",
              file=sys.stderr)

    if not undo_stack:
        return

    response = prompt("k: Keep successful changes (default)\n"
                      "u: Undo all changes\n"
                      "? [k] ",
                      ("undo", "keep"),
                      default="keep")
    if response == "keep":
        return

    assert response == "undo"
    undo_failed = False
    while undo_stack:
        callback = undo_stack.pop()
        try:
            callback()
        except OSError as e:
            print(str(e))
            undo_failed = True
    if undo_failed:
        raise AbortError("Failed to undo changes.")


def edit_move(original_paths, *, editor=None, use_absolute_paths=False,
              show_preview=True, always_sanitize_paths=False):
    """
    TODO
    """
    # Normalize paths.
    if use_absolute_paths:
        original_paths = [os.path.abspath(path) for path in original_paths]
    else:
        original_paths = [os.path.normpath(path) for path in original_paths]

    original_paths = list(set(original_paths))
    original_paths.sort()

    # Verify that all paths exist.
    for path in original_paths:
        # TODO: What to do about directories?
        # * Moving directories along with all of their contents should be okay.
        # * Unclear what to do if directory is renamed separately from a file
        #   within it.
        # * Maybe check if any renamed files are within a renamed directory and
        #   fail?
        # * Need to preserve ownership/permissions.
        if not os.path.exists(path):
            raise AbortError(f"\"{path}\" not found.")

    ctx = EditMoveContext()
    ctx.original_paths = original_paths

    sanitized_paths = [to_printable(path) for path in ctx.original_paths]
    if not always_sanitize_paths and sanitized_paths != ctx.original_paths:
        print("Non-printable characters found in paths.",
              file=sys.stderr)
        response = prompt("r: Replace non-printable characters (default)\n"
                          "q: Quit\n"
                          "? [r] ",
                          ("replace", "quit"),
                          default="replace")
        if response == "quit":
            raise AbortError(cancelled=True)
        else:
            assert response == "replace"

    paths_to_edit = sanitized_paths
    while True:
        try:
            assert len(paths_to_edit) == len(original_paths)
            ctx.previous_paths = paths_to_edit
            ctx.new_paths = edit_paths(paths_to_edit, editor=editor)
            ctx.new_paths = [os.path.normpath(path) for path in ctx.new_paths]

            check_paths(ctx)

            if show_preview:
                preview_renames(ctx)

            rename_files(ctx)
            break

        except RestartEdit as e:
            paths_to_edit = e.paths_to_edit
            continue


def usage(full=False, file=sys.stdout):
    """
    TODO
    """
    print(f"Usage: {__name__} [OPTIONS] FILE [FILE ...]\n",
          file=file, end="")
    if full:
        # TODO
        pass


def main(argv):
    try:
        (opts, args) = getopt.getopt(argv[1:],
                                     "he:",
                                     ("help",
                                      "editor=",
                                      "absolute",
                                      "preview",
                                      "no-preview",
                                      "sanitize"))
    except getopt.GetoptError as e:
        print(str(e), file=sys.stderr)
        usage(file=sys.stderr)
        return 1

    editor = None
    show_preview = True
    use_absolute_paths = False
    always_sanitize_paths = False

    for (o, a) in opts:
        if o in ("-h", "--help"):
            usage(full=True)
            return 0
        elif o in ("-e", "--editor"):
            editor = a
        elif o == "--absolute":
            use_absolute_paths = True
        elif o == "--preview":
            show_preview = True
        elif o == "--no-preview":
            show_preview = False
        elif o == "--sanitize":
            always_sanitize_paths = True

    edit_move(args,
              editor=editor,
              use_absolute_paths=use_absolute_paths,
              show_preview=show_preview,
              always_sanitize_paths=always_sanitize_paths)
    return 0


if __name__ == "__main__":
    __name__ = os.path.basename(__file__)  # pylint: disable=redefined-builtin

    try:
        sys.exit(main(sys.argv))
    except AbortError as e:
        if not e.cancelled:
            print(f"{__name__}: {e}", file=sys.stderr)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        sys.exit(1)
