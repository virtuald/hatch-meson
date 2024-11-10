# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import os
import re
import shutil
import stat
import subprocess
import sys
import sysconfig

import hatch_meson.plugin

import hatchling.build
import packaging.tags
import pytest
import wheel.wheelfile

from .conftest import adjust_packaging_platform_tag


_meson_ver_str = subprocess.run(
    ["meson", "--version"], check=True, stdout=subprocess.PIPE, text=True
).stdout
MESON_VERSION = tuple(map(int, _meson_ver_str.split(".")[:3]))

EXT_SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
if sys.version_info <= (3, 8, 7):
    if MESON_VERSION >= (0, 99):
        # Fixed in Meson 1.0, see https://github.com/mesonbuild/meson/pull/10961.
        from distutils.sysconfig import get_config_var

        EXT_SUFFIX = get_config_var("EXT_SUFFIX")

if sys.platform in {"win32", "cygwin"}:
    EXT_IMP_SUFFIX = re.sub(
        r".(pyd|dll)$", ".lib" if shutil.which("cl.exe") else ".dll.a", EXT_SUFFIX
    )

LIB_SUFFIX = {
    "cygwin": ".dll",
    "darwin": ".dylib",
    "win32": ".dll",
}.get(sys.platform, ".so")

NOGIL_BUILD = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))

# Test against the wheel tag generated by packaging module.
tag = next(packaging.tags.sys_tags())
ABI = tag.abi
INTERPRETER = tag.interpreter
PLATFORM = adjust_packaging_platform_tag(tag.platform)


def wheel_contents(artifact):
    # Sometimes directories have entries, sometimes not, so we filter them out.
    return {entry for entry in artifact.namelist() if not entry.endswith("/")}


def test_scipy_like(wheel_scipy_like):
    # This test is meant to exercise features commonly needed by a regular
    # Python package for scientific computing or data science:
    #   - C and Cython extensions,
    #   - including generated code,
    #   - using `install_subdir`,
    #   - packaging data files with extensions not known to Meson
    artifact = wheel.wheelfile.WheelFile(wheel_scipy_like)

    expecting = {
        "mypkg-2.3.4.dist-info/METADATA",
        "mypkg-2.3.4.dist-info/RECORD",
        "mypkg-2.3.4.dist-info/WHEEL",
        "mypkg/__init__.py",
        "mypkg/__config__.py",
        f"mypkg/extmod{EXT_SUFFIX}",
        f"mypkg/cy_extmod{EXT_SUFFIX}",
        "mypkg/submod/__init__.py",
        "mypkg/submod/unknown_filetype.npq",
    }
    if sys.platform in {"win32", "cygwin"}:
        # Currently Meson is installing .dll.a (import libraries) next
        # to .pyd extension modules. Those are very small, so it's not
        # a major issue - just sloppy. Ensure we don't fail on those.
        expecting.update(
            {
                f"mypkg/extmod{EXT_IMP_SUFFIX}",
                f"mypkg/cy_extmod{EXT_IMP_SUFFIX}",
            }
        )
    assert wheel_contents(artifact) == expecting

    name = artifact.parsed_filename
    assert name is not None
    assert name.group("pyver") == INTERPRETER
    assert name.group("abi") == ABI
    assert name.group("plat") == PLATFORM


# hatch-meson doesn't support mixed purelib and platlib
# def test_purelib_and_platlib(wheel_purelib_and_platlib):
#     artifact = wheel.wheelfile.WheelFile(wheel_purelib_and_platlib)
#
#     expecting = {
#         f"plat{EXT_SUFFIX}",
#         "purelib_and_platlib-1.0.0.data/purelib/pure.py",
#         "pure.py",
#         "purelib_and_platlib-1.0.0.dist-info/METADATA",
#         "purelib_and_platlib-1.0.0.dist-info/RECORD",
#         "purelib_and_platlib-1.0.0.dist-info/WHEEL",
#     }
#     if sys.platform in {"win32", "cygwin"}:
#         # Currently Meson is installing .dll.a (import libraries) next
#         # to .pyd extension modules. Those are very small, so it's not
#         # a major issue - just sloppy. Ensure we don't fail on those.
#         expecting.update({f"plat{EXT_IMP_SUFFIX}"})
#
#     assert wheel_contents(artifact) == expecting


def test_purelib_and_platlib(copyof_purelib_and_platlib, tmp_path):
    with pytest.raises(
        hatch_meson.plugin.BuildError,
        match="The install plan contains both purelib and platlib",
    ):
        hatchling.build.build_wheel(tmp_path)


def test_pure(wheel_pure):
    artifact = wheel.wheelfile.WheelFile(wheel_pure)

    assert wheel_contents(artifact) == {
        "pure-1.0.0.dist-info/METADATA",
        "pure-1.0.0.dist-info/RECORD",
        "pure-1.0.0.dist-info/WHEEL",
        "pure.py",
    }


def test_configure_data(wheel_configure_data):
    artifact = wheel.wheelfile.WheelFile(wheel_configure_data)

    assert wheel_contents(artifact) == {
        "configure_data.py",
        "configure_data-1.0.0.dist-info/METADATA",
        "configure_data-1.0.0.dist-info/RECORD",
        "configure_data-1.0.0.dist-info/WHEEL",
    }


#
# TODO: add these tests back in when bundling is restored
#

# @pytest.mark.skipif(
#     sys.platform not in {"linux", "darwin"}, reason="Not supported on this platform"
# )
# def test_contents(package_library, wheel_library):
#     artifact = wheel.wheelfile.WheelFile(wheel_library)
#
#     assert wheel_contents(artifact) == {
#         f".library.mesonpy.libs/libexample{LIB_SUFFIX}",
#         "library-1.0.0.data/headers/examplelib.h",
#         "library-1.0.0.data/scripts/example",
#         "library-1.0.0.dist-info/METADATA",
#         "library-1.0.0.dist-info/RECORD",
#         "library-1.0.0.dist-info/WHEEL",
#     }


# @pytest.mark.skipif(
#     sys.platform not in {"linux", "darwin"}, reason="Not supported on this platform"
# )
# def test_local_lib(venv, wheel_link_against_local_lib):
#     venv.pip("install", wheel_link_against_local_lib)
#     output = venv.python("-c", "import example; print(example.example_sum(1, 2))")
#     assert int(output) == 3


# @pytest.mark.skipif(
#     sys.platform not in {"linux", "darwin"}, reason="Not supported on this platform"
# )
# def test_rpath(wheel_link_against_local_lib, tmp_path):
#     artifact = wheel.wheelfile.WheelFile(wheel_link_against_local_lib)
#     artifact.extractall(tmp_path)
#
#     origin = {"linux": "$ORIGIN", "darwin": "@loader_path"}[sys.platform]
#     expected = {
#         f"{origin}/.link_against_local_lib.mesonpy.libs",
#         "custom-rpath",
#     }
#
#     rpath = set(mesonpy._rpath._get_rpath(tmp_path / f"example{EXT_SUFFIX}"))
#     # Verify that rpath is a superset of the expected one: linking to
#     # the Python runtime may require additional rpath entries.
#     assert rpath >= expected


# @pytest.mark.skipif(
#     sys.platform not in {"linux", "darwin"}, reason="Not supported on this platform"
# )
# def test_uneeded_rpath(wheel_plat, tmp_path):
#     artifact = wheel.wheelfile.WheelFile(wheel_plat)
#     artifact.extractall(tmp_path)
#
#     origin = {"linux": "$ORIGIN", "darwin": "@loader_path"}[sys.platform]
#
#     rpath = mesonpy._rpath._get_rpath(tmp_path / f"plat{EXT_SUFFIX}")
#     for path in rpath:
#         assert origin not in path


@pytest.mark.skipif(
    sys.platform not in {"linux", "darwin"}, reason="Not supported on this platform"
)
def test_executable_bit(wheel_executable_bit):
    artifact = wheel.wheelfile.WheelFile(wheel_executable_bit)

    executable_files = {
        "executable_module.py",
        "executable_bit-1.0.0.data/scripts/example",
        "executable_bit-1.0.0.data/scripts/example-script",
    }
    for info in artifact.infolist():
        mode = (info.external_attr >> 16) & 0o777
        assert bool(mode & stat.S_IXUSR) == (info.filename in executable_files)


def test_detect_wheel_tag_module(wheel_plat):
    name = wheel.wheelfile.WheelFile(wheel_plat).parsed_filename
    assert name is not None
    assert name.group("pyver") == INTERPRETER
    assert name.group("abi") == ABI
    assert name.group("plat") == PLATFORM


def test_detect_wheel_tag_script(wheel_executable):
    name = wheel.wheelfile.WheelFile(wheel_executable).parsed_filename
    assert name is not None
    assert name.group("pyver") == "py3"
    assert name.group("abi") == "none"
    assert name.group("plat") == PLATFORM


# hatchling does entry points
# def test_entrypoints(wheel_full_metadata):
#     artifact = wheel.wheelfile.WheelFile(wheel_full_metadata)

#     with artifact.open("full_metadata-1.2.3.dist-info/entry_points.txt") as f:
#         assert (
#             f.read().decode().strip()
#             == textwrap.dedent(
#                 """
#             [something.custom]
#             example = example:custom

#             [console_scripts]
#             example-cli = example:cli

#             [gui_scripts]
#             example-gui = example:gui
#         """
#             ).strip()
#         )


# Hatchling deals with editable details
#
# def test_top_level_modules(package_module_types):
#     with mesonpy._project() as project:
#         builder = mesonpy._EditableWheelBuilder(
#             project._metadata, project._manifest, project._limited_api
#         )
#         assert set(builder._top_level_modules) == {
#             "file",
#             "package",
#             "namespace",
#             "native",
#         }


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
@pytest.mark.parametrize("arch", ["x86_64", "arm64"])
def test_archflags_envvar(copyof_plat, monkeypatch, tmp_path, arch):
    try:
        monkeypatch.setenv("ARCHFLAGS", f"-arch {arch}")
        filename = hatchling.build.build_wheel(tmp_path)
        name = wheel.wheelfile.WheelFile(tmp_path / filename).parsed_filename
        assert name is not None
        assert name.group("plat").endswith(arch)
    finally:
        # revert environment variable setting done by the in-process build
        os.environ.pop("_PYTHON_HOST_PLATFORM", None)


def test_subprojects(wheel_subproject):
    artifact = wheel.wheelfile.WheelFile(wheel_subproject)
    assert wheel_contents(artifact) == {
        "subproject-1.0.0.dist-info/METADATA",
        "subproject-1.0.0.dist-info/RECORD",
        "subproject-1.0.0.dist-info/WHEEL",
        "subproject.py",
        "dep.py",
    }


# Requires Meson 1.2.0, see https://github.com/mesonbuild/meson/pull/11909.
@pytest.mark.skipif(MESON_VERSION < (1, 1, 99), reason="Meson version too old")
@pytest.mark.parametrize(("arg"), ["--skip-subprojects", "--skip-subprojects=dep"])
def test_skip_subprojects(copyof_subproject, tmp_path, arg):
    filename = hatchling.build.build_wheel(tmp_path, {"install-args": [arg]})
    artifact = wheel.wheelfile.WheelFile(tmp_path / filename)
    assert wheel_contents(artifact) == {
        "subproject-1.0.0.dist-info/METADATA",
        "subproject-1.0.0.dist-info/RECORD",
        "subproject-1.0.0.dist-info/WHEEL",
        "subproject.py",
    }


# Requires Meson 1.3.0, see https://github.com/mesonbuild/meson/pull/11745.
@pytest.mark.skipif(MESON_VERSION < (1, 2, 99), reason="Meson version too old")
@pytest.mark.skipif(
    NOGIL_BUILD, reason="Free-threaded CPython does not support the limited API"
)
@pytest.mark.xfail(
    "__pypy__" in sys.builtin_module_names,
    reason="PyPy does not support the abi3 platform tag for wheels",
)
def test_limited_api(wheel_limited_api):
    artifact = wheel.wheelfile.WheelFile(wheel_limited_api)
    name = artifact.parsed_filename
    assert name is not None
    assert name.group("pyver") == INTERPRETER
    assert name.group("abi") == "abi3"
    assert name.group("plat") == PLATFORM


# Requires Meson 1.3.0, see https://github.com/mesonbuild/meson/pull/11745.
@pytest.mark.skipif(MESON_VERSION < (1, 2, 99), reason="Meson version too old")
@pytest.mark.skipif(
    NOGIL_BUILD, reason="Free-threaded CPython does not support the limited API"
)
@pytest.mark.xfail(
    "__pypy__" in sys.builtin_module_names,
    reason="PyPy does not use special modules suffix for stable ABI",
)
def test_limited_api_bad(copyof_limited_api, tmp_path):
    with pytest.raises(
        hatch_meson.plugin.BuildError,
        match="The package declares compatibility with Python limited API but ",
    ):
        hatchling.build.build_wheel(tmp_path, {"setup-args": ["-Dextra=true"]})


# Requires Meson 1.3.0, see https://github.com/mesonbuild/meson/pull/11745.
@pytest.mark.skipif(MESON_VERSION < (1, 2, 99), reason="Meson version too old")
def test_limited_api_disabled(copyof_limited_api, tmp_path):
    filename = hatchling.build.build_wheel(
        tmp_path, {"setup-args": ["-Dpython.allow_limited_api=false"]}
    )
    artifact = wheel.wheelfile.WheelFile(tmp_path / filename)
    name = artifact.parsed_filename
    assert name is not None
    assert name.group("pyver") == INTERPRETER
    assert name.group("abi") == ABI
    assert name.group("plat") == PLATFORM


def test_install_subdir(wheel_install_subdir):
    artifact = wheel.wheelfile.WheelFile(wheel_install_subdir)
    # Handling of the exclude_files and exclude_directories requires
    # Meson 1.1.0, see https://github.com/mesonbuild/meson/pull/11432.
    # Run the test anyway to ensure that meson-python can produce a
    # wheel also for older versions of Meson.
    if MESON_VERSION >= (1, 1, 99):
        assert wheel_contents(artifact) == {
            "install_subdir-1.0.0.dist-info/METADATA",
            "install_subdir-1.0.0.dist-info/RECORD",
            "install_subdir-1.0.0.dist-info/WHEEL",
            "subdir/__init__.py",
            "subdir/test.py",
            "test/module.py",
            "nested/deep/deep.py",
            "nested/nested.py",
        }


def test_vendored_meson(wheel_vendored_meson):
    # This test will error if the vendored meson.py wrapper script in
    # the test package isn't used.
    pass


def test_encoding(wheel_encoding):
    artifact = wheel.wheelfile.WheelFile(wheel_encoding)
    assert wheel_contents(artifact) == {
        "encoding-1.0.0.dist-info/METADATA",
        "encoding-1.0.0.dist-info/RECORD",
        "encoding-1.0.0.dist-info/WHEEL",
        "テスト.py",
    }


def test_custom_target_install_dir(wheel_custom_target_dir):
    artifact = wheel.wheelfile.WheelFile(wheel_custom_target_dir)
    assert wheel_contents(artifact) == {
        "custom_target_dir-1.0.0.dist-info/METADATA",
        "custom_target_dir-1.0.0.dist-info/RECORD",
        "custom_target_dir-1.0.0.dist-info/WHEEL",
        "package/generated/one.py",
        "package/generated/two.py",
    }


def test_install_tags(copyof_install_tags, tmp_path):
    filename = hatchling.build.build_wheel(
        tmp_path, {"install-args": ["--tags", "pkg1"]}
    )
    artifact = wheel.wheelfile.WheelFile(tmp_path / filename)
    assert wheel_contents(artifact) == {
        "install_tags-1.0.0.dist-info/METADATA",
        "install_tags-1.0.0.dist-info/RECORD",
        "install_tags-1.0.0.dist-info/WHEEL",
        "pkg1.py",
    }
