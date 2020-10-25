#!/usr/bin/env python3

"""Unit tests for edit-filenames."""

import contextlib
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


the_fake_file_table = FakeFileTable()


class FakePath(pathlib.Path):
    def __init__(self, raw_path):
        super().__init__(raw_path)
        self.raw_path = raw_path

    def exists(self):
        return os.path.exists(self.raw_path)

    def is_dir(self):
        return os.path.is_dir(self.raw_path)


def fake_print(original_print):
    def helper(*args, **kwargs):
        file = kwargs.get('file')
        if file is not None and file != sys.stdout:
            original_print(*args, **kwargs)
    return helper


def fake_move(source_path, destination_path):
    if not the_fake_file_table.exists(source_path):
        raise OSError(errno.ENOENT, f"{source_path} not found.", source_path)
    if the_fake_file_table.exists(destination_path):
        raise OSError(errno.EEXIST, f"{destination_path} already exists",
                      destination_path)
    if the_fake_file_table.is_dir(source_path):
        the_fake_file_table.add_directories([destination_path])
    else:
        the_fake_file_table.add_files([destination_path])
    the_fake_file_table.remove_paths([source_path])


@contextlib.contextmanager
def default_patches(original_filename_list, new_filenames):
    the_fake_file_table.add_files(original_filename_list)
    with unittest.mock.patch("edit_filenames.run_editor",
                             fake_run_editor(new_filenames)), \
         unittest.mock.patch("shutil.move", side_effect=fake_move) as mock_move, \
         unittest.mock.patch("os.path.lexists", the_fake_file_table.exists), \
         unittest.mock.patch("pathlib.Path", FakePath), \
         unittest.mock.patch("builtins.print", fake_print(print)):

         yield mock_move


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""

    def setUp(self):
        the_fake_file_table = FakeFileTable()

    def tearDown(self):
        pass

    def test_edit_move_basic(self):
        """Basic tests `edit_filenames.edit_move`."""
        original_filename_list = ["bar", "baz", "foo", "qux"]
        new_filenames = "bar.ext\nbaz.ext\nfoo.ext\nqux.ext\n"

        # TODO: Verify that trailing newlines in editor output don't matter.
        for original_order in (True, False):
            the_fake_file_table.clear()

            if not original_order:
                # Verify that order of the original file paths does not matter.
                original_filename_list.reverse()

            with default_patches(original_filename_list,
                                 new_filenames) as mock_move:
                # debug_prompt()
                exit_code = edit_filenames.edit_move(original_filename_list,
                                                     interactive=False)
                mock_move.assert_has_calls([
                    unittest.mock.call("bar", "bar.ext"),
                    unittest.mock.call("baz", "baz.ext"),
                    unittest.mock.call("foo", "foo.ext"),
                    unittest.mock.call("qux", "qux.ext"),
                ])

    def test_edit_move_rotate_left(self):
        """Tests `edit_filenames.edit_move`."""
        original_filename_list = ["foo.1", "foo.2", "foo.3", "foo.4"]
        new_filenames = "foo.2\nfoo.3\nfoo.4\nfoo.1\n"

        with default_patches(original_filename_list,
                             new_filenames) as mock_move:
            exit_code = edit_filenames.edit_move(original_filename_list,
                                                 interactive=False)
            mock_move.assert_has_calls([
                unittest.mock.call("foo.4", "edit_filenames-0.tmp"),
                unittest.mock.call("foo.3", "foo.4"),
                unittest.mock.call("foo.2", "foo.3"),
                unittest.mock.call("foo.1", "foo.2"),
                unittest.mock.call("edit_filenames-0.tmp", "foo.1"),
            ])

    def test_edit_move_rotate_right(self):
        """Tests `edit_filenames.edit_move`."""
        original_filename_list = ["foo.1", "foo.2", "foo.3", "foo.4"]
        new_filenames = "foo.4\nfoo.1\nfoo.2\nfoo.3\n"

        with default_patches(original_filename_list,
                             new_filenames) as mock_move:
            exit_code = edit_filenames.edit_move(original_filename_list,
                                                 interactive=False)
            mock_move.assert_has_calls([
                unittest.mock.call("foo.2", "edit_filenames-0.tmp"),
                unittest.mock.call("foo.3", "foo.2"),
                unittest.mock.call("foo.4", "foo.3"),
                unittest.mock.call("foo.1", "foo.4"),
                unittest.mock.call("edit_filenames-0.tmp", "foo.1"),
            ])


def main(argv):
    unittest.main()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
