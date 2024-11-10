# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import stat
import sys
import tarfile
import textwrap

import pytest

from .conftest import metadata


def test_dynamic_version(sdist_dynamic_version):
    with tarfile.open(sdist_dynamic_version, "r:gz") as sdist:
        sdist_pkg_info = sdist.extractfile("dynamic_version-1.0.0/PKG-INFO").read()

    assert metadata(sdist_pkg_info) == metadata(
        textwrap.dedent(
            """\
            Metadata-Version: 2.3
            Name: dynamic-version
            Version: 1.0.0
        """
        )
    )


# def test_contents(sdist_library):
#     with tarfile.open(sdist_library, "r:gz") as sdist:
#         names = {member.name for member in sdist.getmembers()}
#         mtimes = {member.mtime for member in sdist.getmembers()}

#     assert names == {
#         "library-1.0.0/example.c",
#         "library-1.0.0/examplelib.c",
#         "library-1.0.0/examplelib.h",
#         "library-1.0.0/meson.build",
#         "library-1.0.0/pyproject.toml",
#         "library-1.0.0/PKG-INFO",
#     }

#     # All the archive members have a valid mtime.
#     assert 0 not in mtimes


def test_contents_subdirs(sdist_subdirs):
    with tarfile.open(sdist_subdirs, "r:gz") as sdist:
        names = {member.name for member in sdist.getmembers()}
        mtimes = {member.mtime for member in sdist.getmembers()}

    assert names == {
        "subdirs-1.0.0/PKG-INFO",
        "subdirs-1.0.0/meson.build",
        "subdirs-1.0.0/pyproject.toml",
        "subdirs-1.0.0/subdirs/__init__.py",
        "subdirs-1.0.0/subdirs/a/__init__.py",
        "subdirs-1.0.0/subdirs/a/b/c.py",
        "subdirs-1.0.0/subdirs/b/c.py",
    }

    # All the archive members have a valid mtime.
    assert 0 not in mtimes


# This tests something that hatchling handles
# def test_contents_unstaged(package_pure, tmp_path):
#     new = textwrap.dedent(
#         """
#         def bar():
#             return 'foo'
#     """
#     ).strip()

#     old = pathlib.Path("pure.py").read_text()

#     with in_git_repo_context():
#         try:
#             pathlib.Path("pure.py").write_text(new)
#             pathlib.Path("other.py").touch()
#             sdist_path = hatchling.build.build_sdist(tmp_path)
#         finally:
#             pathlib.Path("pure.py").write_text(old)
#             pathlib.Path("other.py").unlink()

#     with tarfile.open(tmp_path / sdist_path, "r:gz") as sdist:
#         names = {member.name for member in sdist.getmembers()}
#         mtimes = {member.mtime for member in sdist.getmembers()}
#         data = sdist.extractfile("pure-1.0.0/pure.py").read().replace(b"\r\n", b"\n")

#     # Verify that uncommitted changes are not included in the sdist.
#     assert names == {
#         "pure-1.0.0/PKG-INFO",
#         "pure-1.0.0/meson.build",
#         "pure-1.0.0/pure.py",
#         "pure-1.0.0/pyproject.toml",
#     }
#     assert data == old.encode()

#     # All the archive members have a valid mtime.
#     assert 0 not in mtimes


@pytest.mark.skipif(
    sys.platform in {"win32", "cygwin"},
    reason="Platform does not support executable bit",
)
def test_executable_bit(sdist_executable_bit):
    expected = {
        "executable_bit-1.0.0/PKG-INFO": False,
        "executable_bit-1.0.0/example-script.py": True,
        "executable_bit-1.0.0/example.c": False,
        "executable_bit-1.0.0/executable_module.py": True,
        "executable_bit-1.0.0/meson.build": False,
        "executable_bit-1.0.0/pyproject.toml": False,
    }

    with tarfile.open(sdist_executable_bit, "r:gz") as sdist:
        for member in sdist.getmembers():
            assert bool(member.mode & stat.S_IXUSR) == expected[member.name]


# This meson-python test will fail because there isn't a way to run a user's
# dist script without running `meson dist`, and we rely on hatchling to create
# the sdist instead.
#
# def test_generated_files(sdist_generated_files):
#     with tarfile.open(sdist_generated_files, "r:gz") as sdist:
#         names = {member.name for member in sdist.getmembers()}
#         mtimes = {member.mtime for member in sdist.getmembers()}
#
#     assert names == {
#         "executable_bit-1.0.0/PKG-INFO",
#         "executable_bit-1.0.0/example-script.py",
#         "executable_bit-1.0.0/example.c",
#         "executable_bit-1.0.0/executable_module.py",
#         "executable_bit-1.0.0/meson.build",
#         "executable_bit-1.0.0/pyproject.toml",
#         "executable_bit-1.0.0/_version_meson.py",
#         "executable_bit-1.0.0/generate_version.py",
#     }
#
#     # All the archive members have a valid mtime.
#     assert 0 not in mtimes


# def test_reproducible(package_pure, tmp_path):
#     with in_git_repo_context():
#         t1 = time.time()
#         sdist_path_a = hatchling.build.build_sdist(tmp_path / "a")
#         t2 = time.time()
#         # Ensure that the two sdists are build at least one second apart.
#         time.sleep(max(t1 + 1.0 - t2, 0.0))
#         sdist_path_b = hatchling.build.build_sdist(tmp_path / "b")

#     assert sdist_path_a == sdist_path_b
#     assert (
#         tmp_path.joinpath("a", sdist_path_a).read_bytes()
#         == tmp_path.joinpath("b", sdist_path_b).read_bytes()
#     )
