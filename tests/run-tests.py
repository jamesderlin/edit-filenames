#!/usr/bin/env python3

"""Unit tests for edit-filenames."""

import errno
import os
import pathlib
import sys
import unittest
import unittest.mock

import edit_filenames


def fake_run_editor(mock_contents: str):
    def run_editor(file_path: str, **_kwargs):
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

    def remove_paths(self, paths):
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.difference_update(paths)
        self.existing_directories.difference_update(paths)

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


class TestContext:
    def __init__(self):
        self.original_filename_list = []
        self.new_filenames = ""
        self.fake_file_table = FakeFileTable()


class FakePath(pathlib.Path):
    def __init__(self, raw_path):
        super().__init__(raw_path)
        self.raw_path = raw_path

    def exists(self):
        return os.path.exists(self.raw_path)

    def is_dir(self):
        return os.path.isdir(self.raw_path)


def fake_print(original_print):
    def helper(*args, **kwargs):
        file = kwargs.get('file')
        if file is not None and file != sys.stdout:
            original_print(*args, **kwargs)
    return helper


def fake_move(test_ctx):
    def helper(source_path, destination_path):
        if not test_ctx.fake_file_table.exists(source_path):
            raise OSError(errno.ENOENT, f"{source_path} not found.", source_path)
        if test_ctx.fake_file_table.exists(destination_path):
            raise OSError(errno.EEXIST, f"{destination_path} already exists",
                          destination_path)
        if test_ctx.fake_file_table.is_dir(source_path):
            test_ctx.fake_file_table.add_directories([destination_path])
        else:
            test_ctx.fake_file_table.add_files([destination_path])
        test_ctx.fake_file_table.remove_paths([source_path])
    return helper


def expect_edit_move(original_filename_list,
                     new_filenames,
                     expected_move_calls):
    test_ctx = TestContext()
    test_ctx.original_filename_list = original_filename_list
    test_ctx.new_filenames = new_filenames

    test_ctx.fake_file_table.add_files(test_ctx.original_filename_list)

    with unittest.mock.patch("os.path.lexists",
                             test_ctx.fake_file_table.exists), \
         unittest.mock.patch("pathlib.Path", FakePath), \
         unittest.mock.patch("builtins.print", fake_print(print)), \
         unittest.mock.patch("edit_filenames.run_editor",
                             fake_run_editor(test_ctx.new_filenames)), \
         unittest.mock.patch("shutil.move",
                             side_effect=fake_move(test_ctx),
                             autospec=True) as mock_move:

        edit_filenames.edit_move(test_ctx.original_filename_list,
                                 interactive=False)
        mock_move.assert_has_calls(expected_move_calls)


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_edit_move_basic(self):
        """Tests basic renaming."""

        original_filename_list = ["bar", "baz", "foo", "qux"]
        new_filenames = "bar.ext\nbaz.ext\nfoo.ext\nqux.ext\n"
        expected_calls = [
            unittest.mock.call("bar", "bar.ext"),
            unittest.mock.call("baz", "baz.ext"),
            unittest.mock.call("foo", "foo.ext"),
            unittest.mock.call("qux", "qux.ext")
        ]

        expect_edit_move(original_filename_list,
                         new_filenames,
                         expected_calls)

        # Verify that order of the original file paths does not matter.
        expect_edit_move(list(reversed(original_filename_list)),
                         new_filenames,
                         expected_calls)

        # Verify that renames work if there is no terminating newline.
        expect_edit_move(original_filename_list,
                         new_filenames.rstrip(),
                         expected_calls)

        # Verify that renames work if there are extra trailing newlines.
        expect_edit_move(original_filename_list,
                         new_filenames + "\n\n",
                         expected_calls)

    def test_edit_move_rotate_left(self):
        """Tests renaming files by rotating filenames left."""
        expect_edit_move(
            ["foo.1", "foo.2", "foo.3", "foo.4"],
            "foo.2\nfoo.3\nfoo.4\nfoo.1\n",
            [
                unittest.mock.call("foo.4", "edit_filenames-0.tmp"),
                unittest.mock.call("foo.3", "foo.4"),
                unittest.mock.call("foo.2", "foo.3"),
                unittest.mock.call("foo.1", "foo.2"),
                unittest.mock.call("edit_filenames-0.tmp", "foo.1"),
            ])

    def test_edit_move_rotate_right(self):
        """Tests renaming files by rotating filenames right."""
        expect_edit_move(
            ["foo.1", "foo.2", "foo.3", "foo.4"],
            "foo.4\nfoo.1\nfoo.2\nfoo.3\n",
            [
                unittest.mock.call("foo.2", "edit_filenames-0.tmp"),
                unittest.mock.call("foo.3", "foo.2"),
                unittest.mock.call("foo.4", "foo.3"),
                unittest.mock.call("foo.1", "foo.4"),
                unittest.mock.call("edit_filenames-0.tmp", "foo.1"),
            ])


if __name__ == "__main__":
    unittest.main()
