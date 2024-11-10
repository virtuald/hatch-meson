# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

import ast
import os
import shutil
import sys

import hatch_meson.plugin

import hatchling.build
import pytest

from .conftest import in_git_repo_context, package_dir


def test_missing_dynamic_version(copyof_missing_dynamic_version, tmp_path):
    with pytest.raises(
        hatch_meson.plugin.BuildError,
        match="version not set for project()",
    ):
        hatchling.build.build_wheel(tmp_path)


def test_user_args(copyof_user_args, tmp_path, monkeypatch):
    project_run = hatch_meson.plugin.MesonBuildHook._run
    cmds = []
    args = []

    def wrapper(self, cmd):
        # intercept and filter out test arguments and forward the call
        if cmd[:2] == ["meson", "compile"]:
            # when using meson compile instead of ninja directly, the
            # arguments needs to be unmarshalled from the form used to
            # pass them to the --ninja-args option
            assert cmd[-1].startswith("--ninja-args=")
            cmds.append(cmd[:2])
            args.append(ast.literal_eval(cmd[-1].split("=")[1]))
        elif cmd[:1] == ["meson"]:
            cmds.append(cmd[:2])
            args.append(cmd[2:])
        else:
            # direct ninja invocation
            cmds.append([os.path.basename(cmd[0])])
            args.append(cmd[1:])
        return project_run(
            self,
            [x for x in cmd if not x.startswith(("config-", "cli-", "--ninja-args"))],
        )

    monkeypatch.setattr(hatch_meson.plugin.MesonBuildHook, "_run", wrapper)

    config_settings = {
        "setup-args": ["cli-setup"],
        "compile-args": ["cli-compile"],
        "install-args": ["cli-install"],
    }

    with in_git_repo_context():
        hatchling.build.build_wheel(tmp_path, config_settings)

    # check that the right commands are executed, namely that 'meson
    # compile' is used on Windows rather than a 'ninja' direct
    # invocation.
    assert cmds == [
        # wheel: calls to 'meson setup', 'meson compile', and 'meson install'
        ["meson", "setup"],
        ["meson", "compile"] if sys.platform == "win32" else ["ninja"],
    ]

    # check that the user options are passed to the invoked commands
    expected = [
        # sdist: calls to 'meson setup' and 'meson dist'
        # ["config-setup", "cli-setup"],
        # ["config-dist", "cli-dist"],
        # wheel: calls to 'meson setup', 'meson compile', and 'meson install'
        ["config-setup", "cli-setup"],
        ["config-compile", "cli-compile"],
        ["config-install", "cli-install"],
    ]
    for expected_args, cmd_args in zip(expected, args):
        for arg in expected_args:
            assert arg in cmd_args


def test_unknown_user_args_meson_args(copyof_unknown_user_args_meson_args, tmp_path):
    with pytest.raises(hatch_meson.plugin.ConfigError):
        hatchling.build.build_wheel(tmp_path)


# test_install_tags moved to test_wheel.py


@pytest.mark.skipif(
    sys.version_info < (3, 8),
    reason="unittest.mock doesn't support the required APIs for this test",
)
def test_invalid_build_dir(copyof_pure, tmp_path, mocker):
    meson = mocker.spy(hatch_meson.plugin.MesonBuildHook, "_run")
    build_dir = copyof_pure / "build"
    config_settings = {"build-dir": str(build_dir)}

    # configure the project
    hatchling.build.build_wheel(tmp_path, config_settings)
    assert len(meson.call_args_list) == 2
    assert meson.call_args_list[0].args[1][1] == "setup"
    assert "--reconfigure" not in meson.call_args_list[0].args[1]
    meson.reset_mock()

    # subsequent builds with the same build directory result in a setup --reconfigure
    hatchling.build.build_wheel(tmp_path, config_settings)
    assert len(meson.call_args_list) == 2
    assert meson.call_args_list[0].args[1][1] == "setup"
    assert "--reconfigure" in meson.call_args_list[0].args[1]
    meson.reset_mock()

    # corrupting the build direcory setup is run again
    build_dir.joinpath("meson-private/coredata.dat").unlink()
    hatchling.build.build_wheel(tmp_path, config_settings)
    assert len(meson.call_args_list) == 2
    assert meson.call_args_list[0].args[1][1] == "setup"
    assert "--reconfigure" not in meson.call_args_list[0].args[1]
    meson.reset_mock()

    # removing the build directory things should still work
    shutil.rmtree(build_dir)
    hatchling.build.build_wheel(tmp_path, config_settings)
    assert len(meson.call_args_list) == 2
    assert meson.call_args_list[0].args[1][1] == "setup"
    assert "--reconfigure" not in meson.call_args_list[0].args[1]


@pytest.mark.skipif(
    not os.getenv("CI") or sys.platform != "win32", reason="Requires MSVC"
)
def test_compiler(venv, copyof_detect_compiler, tmp_path):
    # Check that things are setup properly to use the MSVC compiler on
    # Windows. This effectively means running the compilation step
    # with 'meson compile' instead of 'ninja' on Windows. Run this
    # test only on CI where we know that MSVC is available.
    wheel = hatchling.build.build_wheel(tmp_path, {"setup-args": ["--vsenv"]})
    venv.pip("install", os.fspath(tmp_path / wheel))
    compiler = venv.python(
        "-c", "import detect_compiler; print(detect_compiler.compiler())"
    ).strip()
    assert compiler == "msvc"


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
@pytest.mark.parametrize(
    "archflags",
    [
        "-arch x86_64",
        "-arch arm64",
        "-arch arm64 -arch arm64",
    ],
)
def test_archflags_envvar_parsing(copyof_plat, monkeypatch, archflags, tmp_path):
    try:
        monkeypatch.setenv("ARCHFLAGS", archflags)
        arch = archflags.split()[-1]
        whl = hatchling.build.build_wheel(tmp_path)
        assert whl.endswith(f"_{arch}.whl")
    finally:
        # revert environment variable setting done by the in-process build
        os.environ.pop("_PYTHON_HOST_PLATFORM", None)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific test")
@pytest.mark.parametrize(
    "archflags",
    [
        "-arch arm64 -arch x86_64",
        "-arch arm64 -DFOO=1",
    ],
)
def test_archflags_envvar_parsing_invalid(
    copyof_plat, monkeypatch, archflags, tmp_path
):
    try:
        monkeypatch.setenv("ARCHFLAGS", archflags)
        with pytest.raises(hatch_meson.plugin.ConfigError):
            hatchling.build.build_wheel(tmp_path)
    finally:
        # revert environment variable setting done by the in-process build
        os.environ.pop("_PYTHON_HOST_PLATFORM", None)
