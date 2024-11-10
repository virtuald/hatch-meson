# SPDX-FileCopyrightText: 2022 The meson-python developers
#
# SPDX-License-Identifier: MIT

import pathlib
import shutil
import subprocess
import sys

import pytest

import hatchling.build

from .conftest import chdir


examples_dir = pathlib.Path(__file__).parent.parent / "docs" / "examples"


def test_spam(venv, tmp_path):
    """Test that the wheel for the example builds, installs, and imports."""
    project_path = tmp_path / "project"
    shutil.copytree(examples_dir / "spam", project_path)
    dist_path = project_path / "dist"
    with chdir(project_path):
        if sys.version_info < (3, 8):
            # The test project requires Python >= 3.8.
            with pytest.raises(SystemExit):
                hatchling.build.build_wheel(dist_path)
        else:
            wheel = hatchling.build.build_wheel(dist_path)
            subprocess.run(
                [venv.executable, "-m", "pip", "install", dist_path / wheel], check=True
            )
            output = subprocess.run(
                [venv.executable, "-c", "import spam; print(spam.add(1, 2))"],
                check=True,
                stdout=subprocess.PIPE,
            ).stdout
            assert int(output) == 3
