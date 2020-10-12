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
    2. Configuration file setting. (TODO)
    3. The `VISUAL` environment variable.
    4. The `EDITOR` environment variable.
    5. Hard-coded paths to common editors.
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


def to_printable(s):
    """Returns a printable version of the specified string."""
    return s.replace("\n", " ").replace("\0", " ")


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
                                           delete=False)
        exitStack.callback(lambda: os.remove(file.name))

        for line in instructions:
            print(line, file=file)

        for path in paths:
            print(to_printable(path), file=file)
        file.close()

        try:
            run_editor(file.name, line_number=len(instructions) + 1,
                       editor=editor)
        except subprocess.CalledProcessError as e:
            raise AbortError(f"Failed to execute editor: {e.cmd}",
                             exit_code=e.returncode) from e

        with open(file.name, "r") as f:
            return extract_file_paths(f.readlines())


def edit_move(original_paths, *, editor=None, use_absolute_paths=False,
              show_preview=True):
    """
    TODO
    """
    # TODO: Verify that all paths exist.
    # What to do about directories?
    # * Moving directories along with all of their contents should be okay.
    # * Unclear what to do if directory is renamed separately from a file
    #   within it.
    # * Maybe check if any renamed files are within a renamed directory and
    #   fail?
    # * Need to preserve ownership/permissions.

    if use_absolute_paths:
        original_paths = [os.path.abspath(path) for path in original_paths]

    # TODO: If any of the file paths contain embedded newlines or NUL bytes,
    # prompt to continue using sanitized names or abort.

    paths_to_edit = original_paths
    while True:
        assert len(paths_to_edit) == len(original_paths)
        new_paths = edit_paths(paths_to_edit, editor=editor)

        if not new_paths:
            raise AbortError("Cancelling due to an empty file list.")

        if len(original_paths) != len(new_paths):
            print("Lines added or removed.", file=sys.stderr)
            response = prompt("s: Start over (default)\n"
                              "q: Quit\n"
                              "? [s] ",
                              ("s", "quit"),
                              default="s")
            if response == "quit":
                raise AbortError(cancelled=True)
            paths_to_edit = original_paths
            continue

        whitespace_characters = tuple(string.whitespace)
        has_trailing_whitespace = any((path.endswith(whitespace_characters)
                                       for path in new_paths))

        if has_trailing_whitespace:
            print("Lines with trailing whitespace detected.",
                  file=sys.stderr)
            response = prompt("s: Strip trailing whitespace (default)\n"
                              "p: Preserve all whitespace\n"
                              "e: Edit\n"
                              "q: Quit\n"
                              "? [s] ",
                              ("strip", "preserve", "edit", "quit"),
                              default="strip")
            if response == "strip":
                new_paths = [path.rstrip() for path in new_paths]
            elif response == "edit":
                paths_to_edit = new_paths
                continue
            elif response == "quit":
                raise AbortError(cancelled=True)

        # Filter out unchanged paths.
        source_destination_list = [
            (original_path, new_path)
            for (original_path, new_path) in zip(original_paths, new_paths)
            if original_path != new_path
        ]

        if not source_destination_list:
            print("Nothing to do.", file=sys.stderr)
            raise AbortError(cancelled=True)

        # TODO: Sanity-check new file paths to ensure that there are no
        # collisions with existing files and that the new paths don't collide
        # with each other.  On failure, prompt to edit, start over, or quit.

        if show_preview:
            print("The following files will be moved/renamed:")
            for (original, new_path) in source_destination_list:
                print(f"  \"{original}\" => \"{new_path}\"")
            response = prompt("p: Proceed\n"
                              "e: Edit\n"
                              "q: Quit\n"
                              "? [p] ", ("proceed", "edit", "quit"), default="proceed")
            if response == "quit":
                raise AbortError(cancelled=True)
            elif response == "edit":
                paths_to_edit = new_paths
                continue

        # Apply renames.
        for (original_path, new_path) in source_destination_list:
            os.rename(original_path, new_path)

        # TODO: On failure, prompt, offering to revert changes, continue, or stop.
        break


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
    # Command-line options:
    # -e/--editor=EDITOR
    # --absolute Use absolute paths.
    # --no-preview

    # Does not support file paths that contain embedded newlines.
    # Does not support file paths that contain emedded NUL bytes.
    # Leading and trailing whitespace is removed from renamed files.

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
