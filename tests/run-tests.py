#!/usr/bin/env python3

"""Unit tests for edit-filenames."""

import errno
import itertools
import os
import pathlib
import stat
import sys
import typing
import unittest
import unittest.mock

import edit_filenames


# Mocked autospec functions are buggy in some versions of Python:
# <https://stackoverflow.com/q/56367526/>
if sys.version_info < (3, 7, 5) or (3, 8) < sys.version_info < (3, 8, 2):
    print("Python 3.8.2 or later is required.", file=sys.stderr)
    sys.exit(1)


class FakeFileTable:
    """
    Provides fake versions of common file system operations and tracks the
    existence of faked files.
    """

    existing_files: typing.Set[str]
    existing_directories: typing.Set[str]

    def __init__(self) -> None:
        self.existing_files = set()
        self.existing_directories = set()

    def add_files(self, paths: typing.Iterable[str]) -> None:
        """
        Adds files and their parent directories to the fake file system to
        treat them as existing.
        """
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.update(paths)
        self.add_directories((os.path.dirname(path) for path in paths))

    def remove_paths(self, paths: typing.Iterable[str]) -> None:
        """
        Removes the specified paths to files or to directories from the fake
        file system so that they are no longer considered to exist.
        """
        paths = [os.path.abspath(path) for path in paths]
        self.existing_files.difference_update(paths)
        self.existing_directories.difference_update(paths)

    def add_directories(self, paths: typing.Iterable[str]) -> None:
        """
        Adds the specified  directories to the fake file system to treat them
        as existing.
        """
        for path in paths:
            while True:
                assert path not in self.existing_files
                if path in self.existing_directories:
                    break
                self.existing_directories.add(path)
                path = os.path.dirname(path)

    def mkdir(self,
              path: typing.Union[str, os.PathLike],
              mode: int = 511,  # pylint: disable=unused-argument
              *,
              dir_fd: typing.Optional[int] = None) -> None:  # pylint: disable=unused-argument
        """Fake version of `os.mkdir`."""
        original_path = path
        path = os.path.abspath(path)
        if os.path.dirname(path) not in self.existing_directories:
            raise OSError(errno.ENOENT, "No such file or directory",
                          original_path)
        self.existing_directories.add(path)

    def stat(self,
             path: typing.Union[str, os.PathLike],
             *,
             dir_fd: typing.Optional[int] = None,  # pylint: disable=unused-argument
             follow_symlinks: bool = True) -> os.stat_result:  # pylint: disable=unused-argument
        """Fake version of `os.stat`."""
        original_path = path
        path = os.path.abspath(path)

        parent = os.path.dirname(path)
        if parent != path and not os.path.isdir(parent):
            raise OSError(errno.ENOENT, "No such file or directory", path)

        result = [0] * 10
        if path in self.existing_files:
            result[stat.ST_MODE] = stat.S_IFREG
        elif path in self.existing_directories:
            result[stat.ST_MODE] = stat.S_IFDIR
        else:
            raise OSError(errno.ENOENT, "No such file or directory",
                          original_path)

        result[stat.ST_MODE] |= stat.S_IRUSR | stat.S_IWUSR

        return os.stat_result(tuple(result))

    def lstat(self,
              path: os.PathLike,
              *,
              dir_fd: typing.Optional[int] = None) -> os.stat_result:
        """Fake version of `os.lstat`."""
        return self.stat(path, dir_fd=dir_fd, follow_symlinks=False)


class TestContext:
    """Context for storing test parameters and state."""

    original_filename_list: typing.List[str]
    new_filenames: str
    fake_file_table: FakeFileTable

    def __init__(self) -> None:
        self.original_filename_list = []
        self.new_filenames = ""
        self.fake_file_table = FakeFileTable()


_original_print = print


def fake_print(*args: typing.Any, **kwargs: typing.Any) -> None:
    """
    Fake version of `print` that swallows output to `sys.stdout` and to
    `sys.stderr`.
    """
    file = kwargs.get('file')
    if file is not None and file != sys.stdout and file != sys.stderr:
        _original_print(*args, **kwargs)


def fake_move(test_ctx: TestContext) -> typing.Callable:
    """Returns a fake version of `shutil.move`."""
    def helper(source_path: str, destination_path: str) -> None:
        if not os.path.exists(source_path):
            raise OSError(errno.ENOENT, "No such file or directory", source_path)

        if not os.path.isdir(os.path.dirname(destination_path)):
            raise OSError(errno.ENOENT, "No such file or directory", destination_path)

        if os.path.isdir(source_path):
            test_ctx.fake_file_table.add_directories([destination_path])
        else:
            test_ctx.fake_file_table.add_files([destination_path])
        test_ctx.fake_file_table.remove_paths([source_path])
    return helper


def fake_edit_temporary(mock_contents: str) -> typing.Callable:
    """Returns a fake version of `spawneditor.edit_file`."""
    def edit_temporary(*_args: typing.Any,
                       **_kwargs: typing.Any) -> typing.Iterator[str]:
        yield from mock_contents.splitlines(keepends=True)
    return edit_temporary


def expect_edit_move(test_case: unittest.TestCase,
                     original_filename_list: typing.List[str],
                     new_filenames: str,
                     expected_calls: typing.List,
                     test_ctx: typing.Optional[TestContext] = None,
                     raises: typing.Any = None) -> None:
    """
    Verifies the behavior of `edit_filenames.edit_move`, setting up necessary
    mocks.
    """
    test_ctx = test_ctx or TestContext()
    test_ctx.original_filename_list = original_filename_list
    test_ctx.new_filenames = new_filenames

    test_ctx.fake_file_table.add_files(test_ctx.original_filename_list)

    with unittest.mock.patch("os.stat", test_ctx.fake_file_table.stat), \
         unittest.mock.patch("os.lstat", test_ctx.fake_file_table.lstat), \
         unittest.mock.patch("builtins.print", fake_print), \
         unittest.mock.patch("spawneditor.edit_temporary",
                             fake_edit_temporary(test_ctx.new_filenames)), \
         unittest.mock.patch("os.mkdir",
                             side_effect=test_ctx.fake_file_table.mkdir,
                             autospec=True) as mock_mkdir, \
         unittest.mock.patch("shutil.move",
                             side_effect=fake_move(test_ctx),
                             autospec=True) as mock_move:

        mock_manager = unittest.mock.Mock()
        mock_manager.attach_mock(mock_mkdir, "mkdir")
        mock_manager.attach_mock(mock_move, "move")

        try:
            edit_filenames.edit_move(test_ctx.original_filename_list,
                                     interactive=False)
        except Exception as e:  # pylint: disable=broad-except
            if raises:
                test_case.assertIsInstance(e, raises)
                for filename in original_filename_list:
                    test_case.assertTrue(os.path.exists(filename))
            else:
                raise

        mock_manager.assert_has_calls(expected_calls)


class TestEditFilenames(unittest.TestCase):
    """Tests functions from `edit-filenames`."""
    def test_edit_move_basic(self) -> None:
        """Tests basic renaming."""
        original_filename_list = ["bar", "baz", "foo", "qux"]
        new_filenames = "bar.ext\nbaz.ext\nfoo.ext\nqux.ext\n"
        expected_calls = [
            unittest.mock.call.move("bar", "bar.ext"),
            unittest.mock.call.move("baz", "baz.ext"),
            unittest.mock.call.move("foo", "foo.ext"),
            unittest.mock.call.move("qux", "qux.ext")
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

    def test_makes_directories(self) -> None:
        """Tests that destination directories are automatically created."""
        original_filename_list = ["bar", "foo"]
        new_filenames = "dir1/bar\ndir2/dir3/dir4/foo\n"
        expected_calls = [
            unittest.mock.call.mkdir(pathlib.Path("dir1")),
            unittest.mock.call.move("bar", "dir1/bar"),
            unittest.mock.call.mkdir(pathlib.Path("dir2")),
            unittest.mock.call.mkdir(pathlib.Path("dir2/dir3")),
            unittest.mock.call.mkdir(pathlib.Path("dir2/dir3/dir4")),
            unittest.mock.call.move("foo", "dir2/dir3/dir4/foo"),
        ]

        expect_edit_move(self,
                         original_filename_list,
                         new_filenames,
                         expected_calls)

    def test_edit_move_existing_destination(self) -> None:
        """Tests that renames fail if the destination already exists."""
        test_ctx = TestContext()
        test_ctx.fake_file_table.add_files(["qux"])
        expect_edit_move(
            self,
            ["bar", "foo"],
            "baz\nqux\n",
            [],
            test_ctx=test_ctx,
            raises=edit_filenames.AbortError)

    def test_edit_move_duplicate_destination(self) -> None:
        """
        Tests that renames fail if multiple files are renamed to the same
        destination.
        """
        expect_edit_move(
            self,
            ["bar", "foo"],
            "baz\nbaz\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_added_lines(self) -> None:
        """Tests that renames fail if lines were added in the editor."""
        expect_edit_move(
            self,
            ["bar", "foo"],
            "bar\nbaz\nfoo\n",
            [],
            raises=edit_filenames.AbortError)

    def test_edit_removed_lines(self) -> None:
        """Tests that renames fail if lines were removed in the editor."""
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
                unittest.mock.call.move("foo.4", "edit_filenames-0.tmp"),
                unittest.mock.call.move("foo.3", "foo.4"),
                unittest.mock.call.move("foo.2", "foo.3"),
                unittest.mock.call.move("foo.1", "foo.2"),
                unittest.mock.call.move("edit_filenames-0.tmp", "foo.1"),
            ])

    def test_edit_move_rotate_right(self) -> None:
        """Tests renaming files by rotating filenames right."""
        expect_edit_move(
            self,
            ["foo.1", "foo.2", "foo.3", "foo.4"],
            "foo.4\nfoo.1\nfoo.2\nfoo.3\n",
            [
                unittest.mock.call.move("foo.2", "edit_filenames-0.tmp"),
                unittest.mock.call.move("foo.3", "foo.2"),
                unittest.mock.call.move("foo.4", "foo.3"),
                unittest.mock.call.move("foo.1", "foo.4"),
                unittest.mock.call.move("edit_filenames-0.tmp", "foo.1"),
            ])

    def test_edit_paths_interactive(self) -> None:
        """
        Tests the behavior of `edit_filenames.edit_paths` in interactive mode.
        """
        input_paths = ["foo", "bar", "baz"]
        with unittest.mock.patch("spawneditor.edit_temporary",
                                 return_value=["foo\n", "bar\n", "qux\n"]) \
                as mock_edit_temporary:
            edited_paths = edit_filenames.edit_paths(input_paths,
                                                     show_instructions=True)
            mock_edit_temporary.assert_called_once()
            content_lines = list(itertools.chain.from_iterable(
                # We intentionally use `str.split("\n")` here because
                # `str.splitlines()` will swallow a trailing newline.
                (s.split("\n") for s in mock_edit_temporary.call_args.args[0])
            ))
            line_number = mock_edit_temporary.call_args.kwargs["line_number"]

            self.assertTrue(line_number > 1)
            self.assertTrue(line_number <= len(content_lines))
            for i in range(line_number) :
                if "instructions" in content_lines[i].lower():
                    break
            else:
                self.fail("No instructions found")
            self.assertEqual(content_lines[line_number - 1:], input_paths)
            self.assertEqual(edited_paths, ["foo", "bar", "qux"])

    def test_edit_paths_noninteractive(self) -> None:
        """
        Tests the behavior of `edit_filenames.edit_paths` in non-interactive
        mode.
        """
        with unittest.mock.patch("spawneditor.edit_temporary",
                                 return_value=["foo\n", "bar\n", "qux\n"]) \
                as mock_edit_temporary:
            input_paths = ["foo", "bar", "baz"]
            edited_paths = edit_filenames.edit_paths(input_paths,
                                                     show_instructions=False)
            mock_edit_temporary.assert_called_once()
            content_lines = list(mock_edit_temporary.call_args.args[0])
            line_number = mock_edit_temporary.call_args.kwargs["line_number"]

            self.assertTrue(line_number is None or line_number == 1)
            self.assertEqual(content_lines, input_paths)
            self.assertEqual(edited_paths, ["foo", "bar", "qux"])


if __name__ == "__main__":
    unittest.main()
