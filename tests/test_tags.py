# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import importlib.machinery
import os
import pathlib
import platform
import sys
import sysconfig

from collections import defaultdict

import packaging.tags
import pytest

import hatch_meson.plugin
import hatch_meson._tags

from .conftest import adjust_packaging_platform_tag


# Test against the wheel tag generated by packaging module.
tag = next(packaging.tags.sys_tags())
ABI = tag.abi
INTERPRETER = tag.interpreter
PLATFORM = adjust_packaging_platform_tag(tag.platform)


def get_abi3_suffix():
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if ".abi3" in suffix:  # Unix
            return suffix
        elif suffix == ".pyd":  # Windows
            return suffix


SUFFIX = sysconfig.get_config_var("EXT_SUFFIX")
ABI3SUFFIX = get_abi3_suffix()


def test_wheel_tag():
    assert str(hatch_meson._tags.Tag()) == f"{INTERPRETER}-{ABI}-{PLATFORM}"
    assert str(hatch_meson._tags.Tag(abi="abi3")) == f"{INTERPRETER}-abi3-{PLATFORM}"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
def test_macos_platform_tag(monkeypatch):
    for minor in range(9, 16):
        monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", f"10.{minor}")
        version = (10, minor) if platform.mac_ver()[2] != "arm64" else (11, 0)
        assert (
            next(packaging.tags.mac_platforms(version))
            == hatch_meson._tags.get_platform_tag()
        )
    for major in range(11, 20):
        for minor in range(3):
            monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", f"{major}.{minor}")
            assert (
                next(packaging.tags.mac_platforms((major, minor)))
                == hatch_meson._tags.get_platform_tag()
            )


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
def test_macos_platform_tag_arm64(monkeypatch):
    monkeypatch.setenv("_PYTHON_HOST_PLATFORM", "macosx-12.0-arm64")
    # Verify that the minimum platform ABI version on arm64 is 11.0.
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "10.12")
    assert hatch_meson._tags.get_platform_tag() == "macosx_11_0_arm64"
    monkeypatch.setenv("MACOSX_DEPLOYMENT_TARGET", "12.34")
    assert hatch_meson._tags.get_platform_tag() == "macosx_12_0_arm64"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
def test_python_host_platform(monkeypatch):
    monkeypatch.setenv("_PYTHON_HOST_PLATFORM", "macosx-12.0-arm64")
    assert hatch_meson._tags.get_platform_tag().endswith("arm64")
    monkeypatch.setenv("_PYTHON_HOST_PLATFORM", "macosx-11.1-x86_64")
    assert hatch_meson._tags.get_platform_tag().endswith("x86_64")


def wheel_builder_test_factory(content, pure=True, limited_api=False):
    manifest = defaultdict(list)
    manifest.update(
        {
            key: [(pathlib.Path(x), os.path.join("build", x)) for x in value]
            for key, value in content.items()
        }
    )
    return hatch_meson.plugin._compute_tag(manifest, limited_api)


def test_tag_empty_wheel():
    tag = wheel_builder_test_factory({})
    assert str(tag) == "py3-none-any"


def test_tag_purelib_wheel():
    tag = wheel_builder_test_factory(
        {
            "purelib": ["pure.py"],
        }
    )
    assert str(tag) == "py3-none-any"


def test_tag_platlib_wheel():
    tag = wheel_builder_test_factory(
        {
            "platlib": [f"extension{SUFFIX}"],
        }
    )
    assert str(tag) == f"{INTERPRETER}-{ABI}-{PLATFORM}"


def test_tag_stable_abi():
    tag = wheel_builder_test_factory(
        {
            "platlib": [f"extension{ABI3SUFFIX}"],
        },
        limited_api=True,
    )
    # PyPy does not support the stable ABI.
    abi = "abi3" if "__pypy__" not in sys.builtin_module_names else ABI
    assert str(tag) == f"{INTERPRETER}-{abi}-{PLATFORM}"


@pytest.mark.xfail(
    sys.version_info < (3, 8) and sys.platform == "win32",
    reason="Extension modules suffix without ABI tags",
)
@pytest.mark.xfail(
    "__pypy__" in sys.builtin_module_names,
    reason="PyPy does not support the stable ABI",
)
def test_tag_mixed_abi():

    with pytest.raises(
        hatch_meson.plugin.BuildError,
        match="The package declares compatibility with Python limited API but ",
    ):
        tag = wheel_builder_test_factory(
            {
                "platlib": [f"extension{ABI3SUFFIX}", f"another{SUFFIX}"],
            },
            pure=False,
            limited_api=True,
        )

        assert str(tag) == f"{INTERPRETER}-abi3-{PLATFORM}"
