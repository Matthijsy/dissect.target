"""A pathlib.Path compatible implementation for dissect.target.

This allows for the majority of the pathlib.Path API to "just work" on dissect.target filesystems.

Most of this consists of subclassed internal classes with dissect.target specific patches,
but sometimes the change to a function is small, so the entire internal function is copied
and only a small part changed. To ease updating this code, the order of functions, comments
and code style is kept exactly the same as the original pathlib.py.

Yes, we know, this is playing with fire and it can break on new CPython releases.

The implementation is split up in multiple files, one for each CPython version.
You're currently looking at the CPython 3.9 implementation.

Commit hash we're in sync with: debb751
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePath, _Accessor, _PosixFlavour
from typing import IO, TYPE_CHECKING, Any, BinaryIO, Callable, ClassVar

from dissect.target import filesystem
from dissect.target.exceptions import (
    FilesystemError,
    NotASymlinkError,
    SymlinkRecursionError,
)
from dissect.target.helpers import polypath
from dissect.target.helpers.compat import path_common

if TYPE_CHECKING:
    from collections.abc import Iterator

    from typing_extensions import Self

    from dissect.target.filesystem import Filesystem, FilesystemEntry
    from dissect.target.helpers.compat.path_common import _DissectScandirIterator
    from dissect.target.helpers.fsutil import stat_result


class _DissectFlavour(_PosixFlavour):
    is_supported = True

    __variant_instances: ClassVar[dict[tuple[bool, str], _DissectFlavour]] = {}

    def __new__(cls, case_sensitive: bool = False, alt_separator: str = ""):
        idx = (case_sensitive, alt_separator)
        instance = cls.__variant_instances.get(idx)
        if instance is None:
            instance = _PosixFlavour.__new__(cls)
            cls.__variant_instances[idx] = instance

        return instance

    def __init__(self, case_sensitive: bool = False, alt_separator: str = ""):
        super().__init__()
        self.altsep = alt_separator
        self.case_sensitive = case_sensitive

    def casefold(self, s: str) -> str:
        return s if self.case_sensitive else s.lower()

    def casefold_parts(self, parts: list[str]) -> list[str]:
        return parts if self.case_sensitive else [p.lower() for p in parts]

    def compile_pattern(self, pattern: str) -> Callable[..., Any]:
        return re.compile(fnmatch.translate(pattern), 0 if self.case_sensitive else re.IGNORECASE).fullmatch

    def resolve(self, path: TargetPath, strict: bool = False) -> str:
        sep = self.sep
        accessor = path._accessor
        seen = {}

        def _resolve(fs: filesystem.Filesystem, path: str, rest: str) -> str:
            if rest.startswith(sep):
                path = ""

            for name in rest.split(sep):
                if not name or name == ".":
                    # current dir
                    continue
                if name == "..":
                    # parent dir
                    path, _, _ = path.rpartition(sep)
                    continue
                newpath = path + name if path.endswith(sep) else path + sep + name
                if newpath in seen:
                    # Already seen this path
                    path = seen[newpath]
                    if path is not None:
                        # use cached value
                        continue
                    # The symlink is not resolved, so we must have a symlink loop.
                    raise SymlinkRecursionError(newpath)
                # Resolve the symbolic link
                try:
                    target = accessor.readlink(fs.path(newpath))
                except FilesystemError as e:
                    if not isinstance(e, NotASymlinkError) and strict:
                        raise
                    # Not a symlink, or non-strict mode. We just leave the path
                    # untouched.
                    path = newpath
                else:
                    seen[newpath] = None  # not resolved symlink
                    path = _resolve(fs, path, target)
                    seen[newpath] = path  # resolved symlink

            return path

        # NOTE: according to POSIX, getcwd() cannot contain path components
        # which are symlinks.
        return _resolve(path._fs, "", str(path)) or sep

    def gethomedir(self, username: str) -> str:
        raise NotImplementedError("gethomedir() is unsupported")


class _DissectAccessor(_Accessor):
    # Forward compatibility with CPython >= 3.10
    @staticmethod
    def stat(path: TargetPath, *, follow_symlinks: bool = True) -> stat_result:
        if follow_symlinks:
            return path.get().stat()
        return path.get().lstat()

    @staticmethod
    def lstat(path: TargetPath) -> stat_result:
        return path.get().lstat()

    @staticmethod
    def open(path: TargetPath, flags: int, mode: int = 0o777) -> BinaryIO:
        return path.get().open()

    @staticmethod
    def listdir(path: TargetPath) -> list[str]:
        return path.get().listdir()

    @staticmethod
    def scandir(path: TargetPath) -> _DissectScandirIterator:
        return path_common.scandir(path)

    @staticmethod
    def chmod(path: TargetPath, mode: int, *, follow_symlinks: bool = True) -> None:
        raise NotImplementedError("TargetPath.chmod() is unsupported")

    @staticmethod
    def lchmod(path: TargetPath, mode: int) -> None:
        raise NotImplementedError("TargetPath.lchmod() is unsupported")

    @staticmethod
    def mkdir(path: TargetPath, mode: int = 0o777, parents: bool = False, exist_ok: bool = False) -> None:
        raise NotImplementedError("TargetPath.mkdir() is unsupported")

    @staticmethod
    def unlink(path: TargetPath, missing_ok: bool = False) -> None:
        raise NotImplementedError("TargetPath.unlink() is unsupported")

    @staticmethod
    def link_to(src: str, dst: TargetPath) -> None:
        raise NotImplementedError("TargetPath.link_to() is unsupported")

    @staticmethod
    def rmdir(path: TargetPath) -> None:
        raise NotImplementedError("TargetPath.rmdir() is unsupported")

    @staticmethod
    def rename(path: TargetPath, target: str) -> str:
        raise NotImplementedError("TargetPath.rename() is unsupported")

    @staticmethod
    def replace(path: TargetPath, target: str) -> str:
        raise NotImplementedError("TargetPath.replace() is unsupported")

    @staticmethod
    def symlink(path: TargetPath, target: str, target_is_directory: bool = False) -> None:
        raise NotImplementedError("TargetPath.symlink() is unsupported")

    @staticmethod
    def utime(
        path: TargetPath, times: tuple[float, float], *, ns: tuple[int, int] | None = None, follow_symlinks: bool = True
    ) -> None:
        raise NotImplementedError("TargetPath.utime() is unsupported")

    @staticmethod
    def readlink(path: TargetPath) -> str:
        return path.get().readlink()

    @staticmethod
    def owner(path: TargetPath) -> str:
        raise NotImplementedError("TargetPath.owner() is unsupported")

    @staticmethod
    def group(path: TargetPath) -> str:
        raise NotImplementedError("TargetPath.group() is unsupported")

    # NOTE: Forward compatibility with CPython >= 3.12
    isjunction = staticmethod(path_common.isjunction)


_dissect_accessor = _DissectAccessor()


class PureDissectPath(PurePath):
    _fs: Filesystem
    _flavour = _DissectFlavour(case_sensitive=False)

    def __reduce__(self) -> tuple:
        raise TypeError("TargetPath pickling is currently not supported")

    @classmethod
    def _from_parts(cls, args: list, init: bool = True) -> Self:
        fs = args[0]

        if not isinstance(fs, filesystem.Filesystem):
            raise TypeError(
                "invalid PureDissectPath initialization: missing filesystem, "
                f"got {args!r} (this might be a bug, please report)"
            )

        alt_separator = fs.alt_separator
        path_args = []
        for arg in args[1:]:
            if isinstance(arg, str):
                arg = polypath.normalize(arg, alt_separator=alt_separator)
            path_args.append(arg)

        self = super()._from_parts(path_args, init=init)
        self._fs = fs

        self._flavour = _DissectFlavour(alt_separator=fs.alt_separator, case_sensitive=fs.case_sensitive)

        return self

    def _make_child(self, args: list) -> Self:
        child = super()._make_child(args)
        child._fs = self._fs
        child._flavour = self._flavour
        return child

    def with_name(self, name: str) -> Self:
        result = super().with_name(name)
        result._fs = self._fs
        result._flavour = self._flavour
        return result

    def with_stem(self, stem: str) -> Self:
        result = super().with_stem(stem)
        result._fs = self._fs
        result._flavour = self._flavour
        return result

    def with_suffix(self, suffix: str) -> Self:
        result = super().with_suffix(suffix)
        result._fs = self._fs
        result._flavour = self._flavour
        return result

    def relative_to(self, *other) -> Self:
        result = super().relative_to(*other)
        result._fs = self._fs
        result._flavour = self._flavour
        return result

    def __rtruediv__(self, key: str) -> Self:
        try:
            return self._from_parts([self._fs, key, *self._parts])
        except TypeError:
            return NotImplemented

    @property
    def parent(self) -> Self:
        result = super().parent
        result._fs = self._fs
        result._flavour = self._flavour
        return result

    @property
    def parents(self) -> path_common._DissectPathParents:
        return path_common._DissectPathParents(self)


class TargetPath(Path, PureDissectPath):
    __slots__ = ("_entry",)

    def _init(self, template: Path | None = None) -> None:
        self._accessor = _dissect_accessor

    def _make_child_relpath(self, part: str) -> Self:
        child = super()._make_child_relpath(part)
        child._fs = self._fs
        child._flavour = self._flavour
        return child

    def get(self) -> FilesystemEntry:
        try:
            return self._entry
        except AttributeError:
            self._entry = self._fs.get(str(self))
            return self._entry

    @classmethod
    def cwd(cls) -> Self:
        """Return a new path pointing to the current working directory
        (as returned by os.getcwd()).
        """
        raise NotImplementedError("TargetPath.cwd() is unsupported")

    @classmethod
    def home(cls) -> Self:
        """Return a new path pointing to the user's home directory (as
        returned by os.path.expanduser('~')).
        """
        raise NotImplementedError("TargetPath.home() is unsupported")

    def iterdir(self) -> Iterator[Self]:
        """Iterate over the files in this directory.  Does not yield any
        result for the special paths '.' and '..'.
        """
        for entry in self._accessor.scandir(self):
            if entry.name in {".", ".."}:
                # Yielding a path object for these makes little sense
                continue
            child_path = self._make_child_relpath(entry.name)
            child_path._entry = entry
            yield child_path

    # NOTE: Forward compatibility with CPython >= 3.12
    def walk(
        self, top_down: bool = True, on_error: Callable[[Exception], None] | None = None, follow_symlinks: bool = False
    ) -> Iterator[tuple[Self, list[str], list[str]]]:
        """Walk the directory tree from this directory, similar to os.walk()."""
        paths = [self]

        while paths:
            path = paths.pop()
            if isinstance(path, tuple):
                yield path
                continue

            # We may not have read permission for self, in which case we can't
            # get a list of the files the directory contains. os.walk()
            # always suppressed the exception in that instance, rather than
            # blow up for a minor reason when (say) a thousand readable
            # directories are still left to visit. That logic is copied here.
            try:
                scandir_it = self._accessor.scandir(path)
            except OSError as e:
                if on_error is not None:
                    on_error(e)
                continue

            with scandir_it:
                dirnames = []
                filenames = []
                for entry in scandir_it:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=follow_symlinks)
                    except OSError:
                        # Carried over from os.path.isdir().
                        is_dir = False

                    if is_dir:
                        dirnames.append(entry.name)
                    else:
                        filenames.append(entry.name)

            if top_down:
                yield path, dirnames, filenames
            else:
                paths.append((path, dirnames, filenames))

            paths += [path._make_child_relpath(d) for d in reversed(dirnames)]

    def absolute(self) -> Self:
        """Return an absolute version of this path.  This function works
        even if the path doesn't point to anything.

        No normalization is done, i.e. all '.' and '..' will be kept along.
        Use resolve() to get the canonical path to a file.
        """
        raise NotImplementedError("TargetPath.absolute() is unsupported in Dissect")

    def resolve(self, strict: bool = False) -> Self:
        """
        Make the path absolute, resolving all symlinks on the way and also
        normalizing it (for example turning slashes into backslashes under
        Windows).
        """
        s = self._flavour.resolve(self, strict=strict)
        if s is None:
            # No symlink resolution => for consistency, raise an error if
            # the path doesn't exist or is forbidden
            self.stat()
            s = str(self.absolute())
        # Now we have no symlinks in the path, it's safe to normalize it.
        normed = polypath.normpath(s, self._flavour.altsep)
        obj = self._from_parts((self._fs, normed), init=False)
        obj._init(template=self)
        return obj

    # Forward compatibility with CPython >= 3.10
    def stat(self, *, follow_symlinks: bool = True) -> stat_result:
        """
        Return the result of the stat() system call on this path, like
        os.stat() does.
        """
        return self._accessor.stat(self, follow_symlinks=follow_symlinks)

    # Forward compatibility with CPython >= 3.10
    def open(
        self,
        mode: str = "rb",
        buffering: int = 0,
        encoding: str | None = None,
        errors: str | None = None,
        newline: str | None = None,
    ) -> IO:
        """Open file and return a stream.

        Supports a subset of features of the real pathlib.open/io.open.

        Note: in contrast to regular Python, the mode is binary by default. Text mode
        has to be explicitly specified. Buffering is also disabled by default.
        """
        return path_common.io_open(self, mode, buffering, encoding, errors, newline)

    def write_bytes(self, data: bytes) -> int:
        """
        Open the file in bytes mode, write to it, and close the file.
        """
        raise NotImplementedError("TargetPath.write_bytes() is unsupported")

    def write_text(
        self, data: str, encoding: str | None = None, errors: str | None = None, newline: str | None = None
    ) -> int:
        """
        Open the file in text mode, write to it, and close the file.
        """
        raise NotImplementedError("TargetPath.write_text() is unsupported")

    def readlink(self) -> Self:
        """
        Return the path to which the symbolic link points.
        """
        path = self._accessor.readlink(self)
        return self._from_parts((self._fs, path), init=False)

    # NOTE: Forward compatibility with CPython >= 3.12
    def is_junction(self) -> bool:
        """
        Whether this path is a junction.
        """
        return self._accessor.isjunction(self)

    def expanduser(self) -> Self:
        """Return a new path with expanded ~ and ~user constructs
        (as returned by os.path.expanduser)
        """
        raise NotImplementedError("TargetPath.expanduser() is unsupported")
