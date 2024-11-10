# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import contextlib
import os
import os.path
import pathlib
import re
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import warnings

from venv import EnvBuilder

import packaging.metadata
import packaging.version
import pytest

import hatchling.build


@contextlib.contextmanager
def chdir(path):
    """Context manager helper to change the current working directory -- cd."""
    old_cwd = os.getcwd()
    os.chdir(os.fspath(path))
    try:
        yield path
    finally:
        os.chdir(old_cwd)


def metadata(data):
    meta, other = packaging.metadata.parse_email(data)
    assert not other
    return meta


def adjust_packaging_platform_tag(platform: str) -> str:
    if platform.startswith(("manylinux", "musllinux")):
        # The packaging module generates overly specific platforms tags on
        # Linux.  The platforms tags on Linux evolved over time.
        # meson-python uses more relaxed platform tags to maintain
        # compatibility with old wheel installation tools.  The relaxed
        # platform tags match the ones generated by the wheel package.
        # https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/
        return re.sub(
            r"^(many|musl)linux(1|2010|2014|_\d+_\d+)_(.*)$", r"linux_\3", platform
        )
    if platform.startswith("macosx"):
        # Python built with older macOS SDK on macOS 11, reports an
        # unexising macOS 10.16 version instead of the real version.
        # The packaging module introduced a workaround in version
        # 22.0.  Too maintain compatibility with older packaging
        # releases we don't implement it.  Reconcile this.
        from platform import mac_ver

        version = tuple(map(int, mac_ver()[0].split(".")))[:2]
        if version == (10, 16):
            return re.sub(r"^macosx_\d+_\d+_(.*)$", r"macosx_10_16_\1", platform)
    return platform


package_dir = pathlib.Path(__file__).parent / "packages"


@contextlib.contextmanager
def in_git_repo_context(path=os.path.curdir):
    # Resist the tentation of using pathlib.Path here: it is not
    # supporded by subprocess in Python 3.7.
    path = os.path.abspath(path)
    shutil.rmtree(os.path.join(path, ".git"), ignore_errors=True)
    try:
        subprocess.run(["git", "init", "-b", "main", path], check=True)
        subprocess.run(
            ["git", "config", "user.email", "author@example.com"], cwd=path, check=True
        )
        subprocess.run(["git", "config", "user.name", "A U Thor"], cwd=path, check=True)
        subprocess.run(["git", "add", "*"], cwd=path, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Test"], cwd=path, check=True)
        yield
    finally:
        # PermissionError raised on Windows.
        with contextlib.suppress(PermissionError):
            shutil.rmtree(os.path.join(path, ".git"))


@pytest.fixture(scope="session")
def tmp_path_session(tmp_path_factory):
    return pathlib.Path(
        tempfile.mkdtemp(
            prefix="mesonpy-test-",
            dir=tmp_path_factory.mktemp("test"),
        )
    )


class VEnv(EnvBuilder):
    def __init__(self, env_dir):
        super().__init__(symlinks=True, with_pip=True)

        # This warning is mistakenly generated by CPython 3.11.0
        # https://github.com/python/cpython/pull/98743
        with warnings.catch_warnings():
            if sys.version_info[:3] == (3, 11, 0):
                warnings.filterwarnings(
                    "ignore",
                    "check_home argument is deprecated and ignored.",
                    DeprecationWarning,
                )
            self.create(env_dir)

        # Free-threaded Python 3.13 requires pip 24.1b1 or later.
        if sysconfig.get_config_var("Py_GIL_DISABLED"):
            # importlib.metadata is not available on Python 3.7 and
            # earlier, however no-gil builds are available only for
            # Python 3.13 and later.
            import importlib.metadata

            if packaging.version.Version(
                importlib.metadata.version("pip")
            ) < packaging.version.Version("24.1b1"):
                self.pip("install", "--upgrade", "pip >= 24.1b1")

    def ensure_directories(self, env_dir):
        context = super().ensure_directories(env_dir)
        # Store the path to the venv Python interpreter. There does
        # not seem to be a way to do this without subclassing.
        self.executable = context.env_exe
        return context

    def python(self, *args: str):
        return subprocess.check_output([self.executable, *args]).decode()

    def pip(self, *args: str):
        return self.python("-m", "pip", *args)


@pytest.fixture()
def venv(tmp_path_factory):
    path = pathlib.Path(tmp_path_factory.mktemp("mesonpy-test-venv"))
    return VEnv(path)


def generate_package_fixture(package):
    @pytest.fixture
    def fixture():
        with chdir(package_dir / package) as new_path:
            yield new_path

    return fixture


def generate_copyof_package_fixture(package):
    @pytest.fixture
    def fixture(tmp_path):
        shutil.copytree(package_dir / package, tmp_path / package)

        with chdir(tmp_path / package) as new_path:
            yield new_path

    return fixture


def generate_sdist_fixture(package):
    @pytest.fixture(scope="session")
    def fixture(tmp_path_session):
        with chdir(package_dir / package), in_git_repo_context():
            return tmp_path_session / hatchling.build.build_sdist(tmp_path_session)

    return fixture


def generate_wheel_fixture(package):
    @pytest.fixture(scope="session")
    def fixture(tmp_path_session):
        shutil.copytree(package_dir / package, tmp_path_session / package)

        with chdir(tmp_path_session / package), in_git_repo_context():
            return tmp_path_session / hatchling.build.build_wheel(tmp_path_session)

    return fixture


# def generate_editable_fixture(package):
#     @pytest.fixture(scope="session")
#     def fixture(tmp_path_session):
#         # shutil.rmtree(
#         #     package_dir / package / ".mesonpy" / "editable", ignore_errors=True
#         # )
#         with chdir(package_dir / package), in_git_repo_context():
#             return tmp_path_session / hatchling.build.build_editable(tmp_path_session)

#     return fixture


# inject {package,sdist,wheel}_* fixtures (https://github.com/pytest-dev/pytest/issues/2424)
for package in os.listdir(package_dir):
    normalized = package.replace("-", "_")
    globals()[f"package_{normalized}"] = generate_package_fixture(package)
    globals()[f"copyof_{normalized}"] = generate_copyof_package_fixture(package)
    globals()[f"sdist_{normalized}"] = generate_sdist_fixture(package)
    globals()[f"wheel_{normalized}"] = generate_wheel_fixture(package)
    # globals()[f"editable_{normalized}"] = generate_editable_fixture(package)


@pytest.fixture(autouse=True, scope="session")
def disable_pip_version_check():
    # Cannot use the 'monkeypatch' fixture because of scope mismatch.
    mpatch = pytest.MonkeyPatch()
    yield mpatch.setenv("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    mpatch.undo()
