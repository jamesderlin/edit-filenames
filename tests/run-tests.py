#!/usr/bin/env python3

"""Unit tests for edit-filenames."""

import os
import pathlib
import shutil
import subprocess
import sys
import unittest
import unittest.mock

import edit_filenames


def debug_prompt():
    """Starts an interactive Python prompt."""
    # pylint: disable=import-outside-toplevel
    import code
    import inspect
    previous_frame = inspect.currentframe().f_back
    code.interact(local=dict(**previous_frame.f_globals,
                             **previous_frame.f_locals))


def fake_run_editor(mock_contents: str):
    def run_editor(file_path: str, **kwargs):
        with open(file_path, "w") as file:
            print(mock_contents, file=file, end="")
    return run_editor


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""

    def setUp(self):
        pass

    def test_edit_move(self):
        """Tests `edit_filenames.edit_move`."""
        original_filename_list = ["foo", "bar", "baz", "qux"]
        new_filenames = "foo.ext\nbar.ext\nbaz.ext\nqux.ext\n"
        edit_filenames.run_editor = fake_run_editor(new_filenames)

        def fake_exists(path):
            lst = original_filename_list + [os.path.abspath(p) for p in original_filename_list]
            return str(path) in lst

        class FakePath(pathlib.Path):
            def __init__(self, raw_path):
                super().__init__(raw_path)
                self.raw_path = raw_path

            def exists(self):
                return fake_exists(self.raw_path)

            def is_dir(self):
                return False

        with unittest.mock.patch("shutil.move") as mock_move, \
             unittest.mock.patch("os.path.lexists", fake_exists), \
             unittest.mock.patch("pathlib.Path", FakePath) as mock_path:

            # debug_prompt()
            exit_code = edit_filenames.edit_move(original_filename_list,
                                                 interactive=False)

def main(argv):
    unittest.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
