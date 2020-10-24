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


class FakeFileTable:
    def __init__(self):
        self.existing_files = set()
        self.existing_directories = set()

    def clear(self):
        self.existing_files.clear()
        self.existing_directories.clear()

    def add_files(self, paths):
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.update(paths)
        self.add_directories((os.path.dirname(path) for path in paths))

    def add_directories(self, paths):
        for path in paths:
            while True:
                assert path not in self.existing_files
                if path in self.existing_directories:
                    break
                self.existing_directories.add(path)
                path = os.path.dirname(path)

    def exists(self, path):
        return self.is_file(path) or self.is_dir(path)

    def is_file(self, path):
        return os.path.abspath(path) in self.existing_files

    def is_dir(self, path):
        return os.path.abspath(path) in self.existing_directories


theFakeFileTable = FakeFileTable()


class FakePath(pathlib.Path):
    def __init__(self, raw_path):
        super().__init__(raw_path)
        self.raw_path = raw_path

    def exists(self):
        return os.path.exists(self.raw_path)

    def is_dir(self):
        return os.path.is_dir(self.raw_path)


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""

    def setUp(self):
        theFakeFileTable = FakeFileTable()

    def tearDown(self):
        pass

    def test_edit_move(self):
        """Tests `edit_filenames.edit_move`."""
        original_filename_list = ["foo", "bar", "baz", "qux"]
        new_filenames = "foo.ext\nbar.ext\nbaz.ext\nqux.ext\n"

        fake_file_table = FakeFileTable()
        fake_file_table.add_files(original_filename_list)

        with unittest.mock.patch("edit_filenames.run_editor",
                                 fake_run_editor(new_filenames)), \
             unittest.mock.patch("shutil.move") as mock_move, \
             unittest.mock.patch("os.path.lexists", fake_file_table.exists), \
             unittest.mock.patch("pathlib.Path", FakePath):

            # debug_prompt()
            exit_code = edit_filenames.edit_move(original_filename_list,
                                                 interactive=False)

def main(argv):
    unittest.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
