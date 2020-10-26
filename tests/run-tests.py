#!/usr/bin/env python3

"""Unit tests for edit-filenames."""

import errno
import os
import stat
import sys
import typing
import unittest
import unittest.mock

import edit_filenames


class FakeFileTable:
    existing_files: typing.Set[str]
    existing_directories: typing.Set[str]

    def __init__(self) -> None:
        self.existing_files = set()
        self.existing_directories = set()

    def add_files(self, paths: typing.Iterable[str]) -> None:
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.update(paths)
        self.add_directories((os.path.dirname(path) for path in paths))

    def remove_paths(self, paths: typing.Iterable[str]) -> None:
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.difference_update(paths)
        self.existing_directories.difference_update(paths)

    def add_directories(self, paths: typing.Iterable[str]) -> None:
        for path in paths:
            while True:
                assert path not in self.existing_files
                if path in self.existing_directories:
                    break
                self.existing_directories.add(path)
                path = os.path.dirname(path)

    def stat(self, path: os.PathLike, *,
             dir_fd=None, follow_symlinks=True) -> os.stat_result:
        path = os.path.abspath(path)

        result = [0 for i in range(10)]
        if path in self.existing_files:
            result[stat.ST_MODE] = stat.S_IFREG
        elif path in self.existing_directories:
            result[stat.ST_MODE] = stat.S_IFDIR
        else:
            raise OSError(errno.ENOENT, "No such file or directory", path)

        result[stat.ST_MODE] |= stat.S_IRUSR | stat.S_IWUSR

        return os.stat_result(tuple(result))

    def lstat(self, path: os.PathLike, *, dir_fd=None) -> os.stat_result:
        return self.stat(path, dir_fd=dir_fd, follow_symlinks=False)


class TestContext:
    original_filename_list: typing.List[str]
    new_filenames: str
    fake_file_table: FakeFileTable

    def __init__(self) -> None:
        self.original_filename_list = []
        self.new_filenames = ""
        self.fake_file_table = FakeFileTable()


_original_print = print


def fake_print(*args, **kwargs) -> None:
    file = kwargs.get('file')
    if file is not None and file != sys.stdout and file != sys.stderr:
        _original_print(*args, **kwargs)


def fake_move(test_ctx: TestContext) -> typing.Callable:
    def helper(source_path: str, destination_path: str) -> None:
        if not os.path.exists(source_path):
            raise OSError(errno.ENOENT, f"{source_path} not found.", source_path)
        if os.path.exists(destination_path):
            raise OSError(errno.EEXIST, f"{destination_path} already exists",
                          destination_path)
        if os.path.isdir(source_path):
            test_ctx.fake_file_table.add_directories([destination_path])
        else:
            test_ctx.fake_file_table.add_files([destination_path])
        test_ctx.fake_file_table.remove_paths([source_path])
    return helper


def fake_run_editor(mock_contents: str) -> typing.Callable:
    def run_editor(file_path: str, **_kwargs) -> None:
        with open(file_path, "w") as file:
            print(mock_contents, file=file, end="")
    return run_editor


def expect_edit_move(test_case: unittest.TestCase,
                     original_filename_list: typing.List[str],
                     new_filenames: str,
                     expected_move_calls: typing.List,
                     test_ctx: TestContext = None,
                     raises: typing.Any = None) -> None:
    test_ctx = test_ctx or TestContext()
    test_ctx.original_filename_list = original_filename_list
    test_ctx.new_filenames = new_filenames

    test_ctx.fake_file_table.add_files(test_ctx.original_filename_list)

    with unittest.mock.patch("os.stat", test_ctx.fake_file_table.stat), \
         unittest.mock.patch("os.lstat", test_ctx.fake_file_table.lstat), \
         unittest.mock.patch("builtins.print", fake_print), \
         unittest.mock.patch("edit_filenames.run_editor",
                             fake_run_editor(test_ctx.new_filenames)), \
         unittest.mock.patch("shutil.move",
                             side_effect=fake_move(test_ctx),
                             autospec=True) as mock_move:

        try:
            edit_filenames.edit_move(test_ctx.original_filename_list,
                                     interactive=False)
        except Exception as e:
            if raises:
                test_case.assertIsInstance(e, raises)
                for filename in original_filename_list:
                    test_case.assertTrue(os.path.exists(filename))
            else:
                raise

        mock_move.assert_has_calls(expected_move_calls)


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""
    def test_edit_move_basic(self) -> None:
        """Tests basic renaming."""
        original_filename_list = ["bar", "baz", "foo", "qux"]
        new_filenames = "bar.ext\nbaz.ext\nfoo.ext\nqux.ext\n"
        expected_calls = [
            unittest.mock.call("bar", "bar.ext"),
            unittest.mock.call("baz", "baz.ext"),
            unittest.mock.call("foo", "foo.ext"),
            unittest.mock.call("qux", "qux.ext")
        ]

        expect_edit_move(self,
                         original_filename_list,
                         new_filenames,
                         expected_calls)

        # Verify that order of the original file paths does not matter.
        expect_edit_move(self,
                         list(reversed(original_filename_list)),
                         new_filenames,
                         expected_calls)

        # Verify that renames work if there is no terminating newline.
        expect_edit_move(self,
                         original_filename_list,
                         new_filenames.rstrip(),
                         expected_calls)

        # Verify that renames work if there are extra trailing newlines.
        expect_edit_move(self,
                         original_filename_list,
                         new_filenames + "\n\n",
                         expected_calls)

    def test_edit_move_no_op(self) -> None:
        """Tests nothing to do."""
        expect_edit_move(
            self,
            ["bar", "baz", "foo"],
            "bar\nbaz\nfoo\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_move_duplicate_destination(self) -> None:
        expect_edit_move(
            self,
            ["bar", "foo"],
            "baz\nbaz\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_move_existing_destination(self) -> None:
        test_ctx = TestContext()
        test_ctx.fake_file_table.add_files(["qux"])
        expect_edit_move(
            self,
            ["bar", "foo"],
            "baz\nqux\n",
            [],
            test_ctx=test_ctx,
            raises=edit_filenames.AbortError)

    def test_edit_added_lines(self) -> None:
        expect_edit_move(
            self,
            ["bar", "foo"],
            "bar\nbaz\nfoo\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_removed_lines(self) -> None:
        expect_edit_move(
            self,
            ["bar", "foo"],
            "foo\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_move_rotate_left(self) -> None:
        """Tests renaming files by rotating filenames left."""
        expect_edit_move(
            self,
            ["foo.1", "foo.2", "foo.3", "foo.4"],
            "foo.2\nfoo.3\nfoo.4\nfoo.1\n",
            [
                unittest.mock.call("foo.4", "edit_filenames-0.tmp"),
                unittest.mock.call("foo.3", "foo.4"),
                unittest.mock.call("foo.2", "foo.3"),
                unittest.mock.call("foo.1", "foo.2"),
                unittest.mock.call("edit_filenames-0.tmp", "foo.1"),
            ])

    def test_edit_move_rotate_right(self) -> None:
        """Tests renaming files by rotating filenames right."""
        expect_edit_move(
            self,
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
