# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import os
import re
import shutil
import subprocess
import textwrap

from typing import List

import packaging.requirements
import pytest

import hatch_meson.plugin


@pytest.mark.parametrize(
    "ninja", [None, "1.8.1", "1.8.3"], ids=["noninja", "oldninja", "newninja"]
)
def test_get_requires_for_build_wheel(monkeypatch, package_pure, ninja):
    # the NINJA environment variable affects the ninja executable lookup and breaks the test
    monkeypatch.delenv("NINJA", raising=False)

    def which(prog: str) -> bool:
        if prog == "ninja":
            return ninja and "ninja"
        if prog in ("ninja-build", "samu"):
            return None
        # smoke check for the future if we add another usage
        raise AssertionError(f"Called with {prog}, tests not expecting that usage")

    subprocess_run = subprocess.run

    def run(
        cmd: List[str], *args: object, **kwargs: object
    ) -> subprocess.CompletedProcess:
        if cmd == ["ninja", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, f"{ninja}\n", "")
        return subprocess_run(cmd, *args, **kwargs)

    monkeypatch.setattr(shutil, "which", which)
    monkeypatch.setattr(subprocess, "run", run)

    expected = set()

    if ninja is None or hatch_meson.plugin._parse_version_string(ninja) < (1, 8, 2):
        expected.add("ninja")

    requirements = hatch_meson.plugin._get_requires_for_build_wheel()

    # Check that the requirement strings are in the correct format.
    names = {packaging.requirements.Requirement(x).name for x in requirements}

    assert names == expected


@pytest.mark.parametrize("meson", [None, "meson"])
def test_get_meson_command(monkeypatch, meson):
    # The MESON environment variable affects the meson executable lookup and breaks the test.
    monkeypatch.delenv("MESON", raising=False)
    assert hatch_meson.plugin._get_meson_command(meson) == ["meson"]


def test_get_meson_command_bad_path(monkeypatch):
    # The MESON environment variable affects the meson executable lookup and breaks the test.
    monkeypatch.delenv("MESON", raising=False)
    with pytest.raises(
        hatch_meson.plugin.ConfigError,
        match=re.escape('meson executable "bad" not found'),
    ):
        hatch_meson.plugin._get_meson_command("bad")


def test_get_meson_command_bad_python_path(monkeypatch):
    # The MESON environment variable affects the meson executable lookup and breaks the test.
    monkeypatch.delenv("MESON", raising=False)
    with pytest.raises(
        hatch_meson.plugin.ConfigError,
        match=re.escape('Could not find the specified meson: "bad-python-path.py"'),
    ):
        hatch_meson.plugin._get_meson_command("bad-python-path.py")


def test_get_meson_command_wrong_version(monkeypatch, tmp_path):
    # The MESON environment variable affects the meson executable lookup and breaks the test.
    monkeypatch.delenv("MESON", raising=False)
    meson = tmp_path / "meson.py"
    meson.write_text(
        textwrap.dedent(
            """
        print('0.0.1')
    """
        )
    )
    with pytest.raises(
        hatch_meson.plugin.ConfigError,
        match=r"Could not find meson version [0-9\.]+ or newer, found 0\.0\.1\.",
    ):
        hatch_meson.plugin._get_meson_command(os.fspath(meson))


def test_get_meson_command_error(monkeypatch, tmp_path):
    # The MESON environment variable affects the meson executable lookup and breaks the test.
    monkeypatch.delenv("MESON", raising=False)
    meson = tmp_path / "meson.py"
    meson.write_text(
        textwrap.dedent(
            """
        import sys
        print('Just testing', file=sys.stderr)
        sys.exit(1)
    """
        )
    )
    with pytest.raises(
        hatch_meson.plugin.ConfigError,
        match=re.escape("Could not execute meson: Just testing"),
    ):
        hatch_meson.plugin._get_meson_command(os.fspath(meson))
