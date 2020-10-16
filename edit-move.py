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
"""
Renames or moves files using a text editor.

Allows paths to a large number of files to be edited using features of a text
editor, such as search and replace or multi-cursor editing.
"""

import contextlib
import errno
import getopt
import os
import pathlib
import readline  # pylint: disable=unused-import  # noqa: F401  # Imported for side-effect.
import shlex
import shutil
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
    An exception that represents a request to restart the editor.  The editor's
    contents will be initialized to the specified paths.
    """
    def __init__(self, paths_to_edit):
        super().__init__()
        self.paths_to_edit = paths_to_edit


def prompt(message, choices, default=None):
    """
    Prompts the user to choose from a list of choices.

    Returns the selected choice.

    Raises an `AbortError` if the user cancels the prompt by sending EOF.
    """
    assert choices
    assert not default or default in choices
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

    1. The explicitly specified editor.
    2. The `VISUAL` environment variable.
    3. The `EDITOR` environment variable.
    4. Hard-coded paths to common editors.

    Raises an `AbortError` if an editor cannot be determined.
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
            default_editor = "/usr/bin/editor"
            if pathlib.Path(default_editor).exists():
                editor = default_editor
            else:
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
    """Parses and returns the list of file paths from the edited file."""
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
    Opens the list of paths in the editor.

    If no editor is specified, one will be determined automatically. (See
    `run_editor`.)

    Raises an `AbortError` if we fail to execute the editor.
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
        file = tempfile.NamedTemporaryFile(mode="w", prefix=f"{__name__}-",
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


def sanitized_path(s):
    """
    Returns a sanitized version of the specified file path.

    Carriage return and linefeed characters will be replaced with a single
    space, and all other control characters will be removed.
    """
    def replacement_char(c):
        if c in "\r\n":
            return " "
        elif ord(c) < ord(" "):
            # Remove control characters.
            return ""
        else:
            return c

    return "".join((replacement_char(c) for c in s))


def move_file(original_path, new_path):
    """
    Moves the specified file from `original_path` to `new_path`.

    Raises an `OSError` on failure.
    """
    def undo_mkdir(path):
        return lambda: os.rmdir(path)

    undo_stack = []

    parts = new_path.parent.parts
    ancestor_path = pathlib.Path()
    for part in parts:
        ancestor_path /= part
        if not ancestor_path.exists():
            os.mkdir(ancestor_path)
            undo_stack.append(undo_mkdir(ancestor_path))

    if os.path.lexists(new_path):
        raise OSError(errno.EEXIST, f"\"{new_path}\" already exists.", new_path)
    shutil.move(original_path, new_path)
    operation = ("Renamed"
                 if original_path.parent == new_path.parent
                 else "Moved")
    print(f"{operation}: \"{original_path}\" => \"{new_path}\"")
    undo_stack.append(lambda: os.rename(new_path, original_path))
    return undo_stack


class EditMoveContext:
    """Context for `edit_move` and its helper functions."""
    def __init__(self):
        self.original_paths = None
        self.previous_paths = None
        self.new_paths = None
        self.source_destination_list = None


def check_whitespace(ctx):
    """
    Helper function to `check_paths` that checks the list of edited paths for
    trailing whitespace, prompting the user to take action if necessary.

    Raises `RestartEdit` if the user chooses to re-edit the paths.  Raises an
    `AbortError` if the user chooses to quit.
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
    Helper function to `check_paths` that sanity-checks for destination file
    path collisions, prompting the user to take action if necessary.

    Raises `RestartEdit` if the user chooses to re-edit the paths.  Raises an
    `AbortError` if the user chooses to quit.
    """
    found_collision = False
    destination_paths = set()
    for (_, new_path) in ctx.source_destination_list:
        if new_path not in destination_paths:
            destination_paths.add(new_path)
        else:
            found_collision = True
            print(f"\"{new_path}\" already used as a destination.",
                  file=sys.stderr)

    if found_collision:
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

    for (_, new_path) in ctx.source_destination_list:
        if os.path.lexists(new_path):
            found_collision = True
            print(f"\"{new_path}\" already exists.")

    if found_collision:
        response = prompt("e: Edit (default)\n"
                          "q: Quit\n"
                          "? [e] ",
                          ("edit", "quit"),
                          default="edit")
        if response == "edit":
            raise RestartEdit(ctx.new_paths)
        else:
            assert response == "quit"
            raise AbortError(cancelled=True)


def check_paths(ctx):
    """
    Runs various sanity-checks on the edited file paths, prompting the user to
    take action if necessary.

    Raises `RestartEdit` if the user chooses to re-edit the paths.  Raises an
    `AbortError` if the user chooses to quit.
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
        (pathlib.Path(original_path), pathlib.Path(new_path))
        for (original_path, new_path) in zip(ctx.original_paths, ctx.new_paths)
        if original_path != new_path
    ]

    if not ctx.source_destination_list:
        print("Nothing to do.", file=sys.stderr)
        raise AbortError(cancelled=True)

    check_collisions(ctx)


def preview_renames(ctx):
    """
    Prints a preview of the actions that will be performed and prompts the user
    for confirmation.

    Raises `RestartEdit` if the user chooses to re-edit the paths.  Raises an
    `AbortError` if the user chooses to quit.
    """
    print("The following files will be moved or renamed:")
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


def apply_moves(ctx):
    """
    Applies the move operations, prompting the user to take action if there are
    any failures.
    """
    undo_stack = []
    failures = []
    for (original_path, new_path) in ctx.source_destination_list:
        try:
            undo_stack += move_file(original_path, new_path)
        except OSError as e:
            failures.append((original_path, new_path,
                             f"{e.strerror} (error code: {e.errno})"))
        except Exception as e:  # pylint: disable=broad-except
            failures.append((original_path, new_path, str(e)))

    if not failures:
        return

    for (original_path, new_path, reason) in failures:
        print(f"Failed to move \"{original_path}\" to \"{new_path}\": {reason}",
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
              show_preview=True):
    """
    Opens the specified paths in an editor, sanity-checks the move operations,
    and applies the moves.

    If no editor is specified, one will be determined automatically. (See
    `run_editor`.)

    If `use_absolute_paths` is `True`, the file paths will be opened in the
    editor using absolute paths.

    If `show_preview` is `True`, prompts the user for confirmation before
    applying the moves.

    Raises an `AbortError` on failure or if the user chooses to quit.
    """
    # Normalize paths.
    if use_absolute_paths:
        original_paths = [os.path.abspath(path) for path in original_paths]
    else:
        original_paths = [os.path.normpath(path) for path in original_paths]

    original_paths = list(set(original_paths))
    original_paths.sort()

    # Verify that all paths exist.
    directories_to_move = []
    for path in original_paths:
        # TODO: What to do about directories?
        # * Moving directories along with all of their contents should be okay.
        # * Unclear what to do if directory is renamed separately from a file
        #   within it.
        # * Maybe check if any renamed files are within a renamed directory and
        #   fail?
        # * Need to preserve ownership/permissions.
        path = pathlib.Path(os.path.abspath(path))

        ancestor_path = path
        while True:
            next_parent = ancestor_path.parent
            if next_parent == ancestor_path:
                break
            ancestor_path = next_parent

            if ancestor_path in directories_to_move:
                raise AbortError(f"\"{path}\" and \"{ancestor_path}\" cannot "
                                 f"be moved together.")

        if path.is_dir():
            directories_to_move.append(path)
        elif not os.path.lexists(path):
            raise AbortError(f"\"{path}\" not found.")

    ctx = EditMoveContext()
    ctx.original_paths = original_paths

    sanitized_paths = [sanitized_path(path) for path in ctx.original_paths]
    if sanitized_paths != ctx.original_paths:
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

            apply_moves(ctx)
            break

        except RestartEdit as e:
            paths_to_edit = e.paths_to_edit
            continue


def usage(full=False, file=sys.stdout):
    """Prints usage information."""
    print(f"Usage: {__name__} [OPTIONS] FILE [FILE ...]\n"
          f"       {__name__} --help\n",
          file=file,
          end="")
    if full:
        print(f"\n"
              f"{__doc__.strip()}\n"
              f"\n"
              f"Options:\n"
              f"    -e EDITOR, --editor=EDITOR\n"
              f"        The path to the editor to use, along with any desired command-line\n"
              f"        options.  If not specified, the editor will be automatically chosen\n"
              f"        from the `EDITOR` or `VISUAL` environment variables.\n"
              f"\n"
              f"    --absolute\n"
              f"        Use absolute file paths.\n"
              f"\n"
              f"    --no-preview\n"
              f"        Disables showing a preview and asking for confirmation before\n"
              f"        performing any rename or move operations.\n"
              f"\n",
              file=file,
              end="")


def main(argv):
    try:
        (opts, args) = getopt.getopt(argv[1:],
                                     "he:",
                                     ("help",
                                      "editor=",
                                      "absolute",
                                      "preview",
                                      "no-preview"))
    except getopt.GetoptError as e:
        print(str(e), file=sys.stderr)
        usage(file=sys.stderr)
        return 1

    editor = None
    show_preview = True
    use_absolute_paths = False

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

    edit_move(args,
              editor=editor,
              use_absolute_paths=use_absolute_paths,
              show_preview=show_preview)
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
