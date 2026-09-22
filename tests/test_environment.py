# SPDX-License-Identifier: MIT

import json
import os
import shutil
import subprocess
import sys

import hatchling.build
import pytest

import hatch_meson.plugin


@pytest.fixture
def dependency_pkgconf(request, monkeypatch):
    """Expose pkgconf only to the Windows tests that need it."""
    if sys.platform != "win32":
        return

    # Installing globally affects unrelated builds through pkgconf's wrappers.
    venv = request.getfixturevalue("venv")
    venv.pip("install", "pkgconf")
    prefix, paths = json.loads(
        venv.python(
            "-c",
            "import json, sys, sysconfig; "
            "print(json.dumps([sys.prefix, sysconfig.get_paths()]))",
        )
    )
    monkeypatch.syspath_prepend(paths["purelib"])
    monkeypatch.setenv("PATH", paths["scripts"], prepend=os.pathsep)
    monkeypatch.setenv("VIRTUAL_ENV", prefix)


@pytest.mark.usefixtures("dependency_pkgconf")
@pytest.mark.parametrize(
    "build", [hatchling.build.build_wheel, hatchling.build.build_editable]
)
@pytest.mark.parametrize("legacy_failed", [False, True])
def test_dependencies_follow_environment(
    copyof_pure, tmp_path, monkeypatch, build, legacy_failed
):
    """Do not reuse dependency paths from a previous build environment."""
    if shutil.which("pkg-config") is None:
        pytest.skip("requires pkg-config")

    meson_file = copyof_pure / "meson.build"
    meson_file.write_text(
        meson_file.read_text()
        + "\ndep = dependency('hatch-meson-test', method: 'pkg-config')\n",
        encoding="utf-8",
    )
    build_dir = tmp_path / "build"
    settings = {"build-dir": str(build_dir)}
    original_path = sys.path[:]
    pkgconfig = tmp_path / "pkgconfig"
    pkgconfig.mkdir()
    # Keep Meson's pkg_config_path option fixed; only dependency results move.
    monkeypatch.setenv("PKG_CONFIG_PATH", str(pkgconfig))

    # Simulate non-isolated -> isolated -> new isolated -> non-isolated.
    # pip keeps sys.executable/sys.prefix but replaces the package search paths.
    for i, name in enumerate(("venv", "isolated-1", "isolated-2", "venv")):
        environment = tmp_path / name
        (environment / "include").mkdir(parents=True, exist_ok=True)
        # Avoid prefix: pkgconf relocates it based on the .pc path on Windows.
        (pkgconfig / "hatch-meson-test.pc").write_text(
            "Name: hatch-meson-test\n"
            "Description: Build environment regression test\n"
            "Version: 1.0\n"
            f"Cflags: -I{environment.as_posix()}/include\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(sys, "path", [str(environment), *original_path])
        build(tmp_path, settings)
        dependencies = json.loads(
            (build_dir / "meson-info" / "intro-dependencies.json").read_text(
                encoding="utf-8"
            )
        )
        dependency = next(d for d in dependencies if d["name"] == "hatch-meson-test")
        assert dependency["compile_args"] == [f"-I{environment.as_posix()}/include"]
        if legacy_failed and i == 0:
            # Simulate an older hatch-meson build without an environment record,
            # followed by a failed manual Meson reconfigure. The introspection
            # file now reports an error, but dependencies remain cached.
            (build_dir / "hatch-meson-environment.json").unlink()
            original = meson_file.read_text(encoding="utf-8")
            meson_file.write_text(
                original + "\nerror('legacy configuration failed')\n", encoding="utf-8"
            )
            result = subprocess.run(
                hatch_meson.plugin._get_meson_command()
                + ["setup", "--reconfigure", str(build_dir)]
            )
            assert result.returncode == 1
            meson_file.write_text(original, encoding="utf-8")
        shutil.rmtree(environment)  # pip deletes its temporary build environment.


@pytest.mark.parametrize(
    "state", ["unchanged", "changed", "missing", "malformed", "invalid-utf8"]
)
def test_environment_cache_refresh(copyof_pure, tmp_path, monkeypatch, mocker, state):
    """Only a known, unchanged environment may skip cache invalidation."""
    run = mocker.spy(hatch_meson.plugin.MesonBuildHook, "_run")
    build_dir = tmp_path / "build"
    settings = {"build-dir": str(build_dir)}
    hatchling.build.build_wheel(tmp_path, settings)
    assert len(run.call_args_list) == 2  # Fresh setup never clears a cache.
    run.reset_mock()

    stamp = build_dir / "hatch-meson-environment.json"
    if state == "changed":
        monkeypatch.syspath_prepend(str(tmp_path / "new-environment"))
    elif state == "missing":
        stamp.unlink(missing_ok=True)
    elif state == "malformed":
        stamp.write_text("{broken", encoding="utf-8")
    elif state == "invalid-utf8":
        stamp.write_bytes(b"\xff")

    hatchling.build.build_wheel(tmp_path, settings)
    commands = [call.args[1] for call in run.call_args_list]
    if state == "unchanged":
        assert len(commands) == 2
    else:
        assert commands[0][1:] == ["configure", "--clearcache", str(build_dir)]
        assert len(commands) == 3
    assert "--reconfigure" in commands[-2]

    # Successful configuration records the new state, avoiding another refresh.
    run.reset_mock()
    hatchling.build.build_wheel(tmp_path, settings)
    assert len(run.call_args_list) == 2


@pytest.mark.parametrize("existing", [False, True])
def test_failed_configuration_does_not_record_environment(
    copyof_pure, tmp_path, monkeypatch, existing
):
    build_dir = tmp_path / "build"
    settings = {"build-dir": str(build_dir)}
    stamp = build_dir / "hatch-meson-environment.json"
    if existing:
        hatchling.build.build_wheel(tmp_path, settings)
        previous = stamp.read_text(encoding="utf-8")

    monkeypatch.syspath_prepend(str(tmp_path / "new-environment"))
    with (copyof_pure / "meson.build").open("a", encoding="utf-8") as f:
        f.write("\nerror('configuration failed')\n")
    with pytest.raises(SystemExit):
        hatchling.build.build_wheel(tmp_path, settings)
    if existing:
        assert stamp.read_text(encoding="utf-8") == previous
    else:
        assert not stamp.exists()


@pytest.mark.parametrize(
    "outcome", ["recovered", "setup-fails", "cache-clear-fails", "interrupted"]
)
def test_cache_clear_failure_recovery(copyof_pure, tmp_path, monkeypatch, outcome):
    build_dir = tmp_path / "build"
    settings = {"build-dir": str(build_dir)}
    hatchling.build.build_wheel(tmp_path, settings)
    stamp = build_dir / "hatch-meson-environment.json"
    previous = stamp.read_text(encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path / "new-environment"))
    if outcome == "setup-fails":
        with (copyof_pure / "meson.build").open("a", encoding="utf-8") as f:
            f.write("\nerror('recovery failed')\n")

    run = hatch_meson.plugin.MesonBuildHook._run
    commands = []

    def wrapper(self, cmd):
        commands.append(cmd)
        # Simulate configure rejecting incompatible saved build data. setup can
        # recover it, but the subsequent cache clear must still succeed.
        if "--clearcache" in cmd and (
            len(commands) == 1 or outcome == "cache-clear-fails"
        ):
            raise SystemExit(130 if outcome == "interrupted" else 1)
        return run(self, cmd)

    monkeypatch.setattr(hatch_meson.plugin.MesonBuildHook, "_run", wrapper)
    if outcome == "recovered":
        hatchling.build.build_wheel(tmp_path, settings)
        assert [cmd[1] for cmd in commands[:4]] == [
            "configure",
            "setup",
            "configure",
            "setup",
        ]
        assert stamp.read_text(encoding="utf-8") != previous
    else:
        with pytest.raises(SystemExit):
            hatchling.build.build_wheel(tmp_path, settings)
        assert stamp.read_text(encoding="utf-8") == previous
        expected_count = {
            "setup-fails": 2,
            "cache-clear-fails": 3,
            "interrupted": 1,
        }[outcome]
        assert len(commands) == expected_count


@pytest.mark.parametrize(
    "field", ["executable", "prefix", "meson", "pkgconf", "meson_version"]
)
def test_environment_identity_fields(copyof_pure, tmp_path, mocker, field):
    """Changing an interpreter or tool identity must invalidate dependencies."""
    build_dir = tmp_path / "build"
    settings = {"build-dir": str(build_dir)}
    hatchling.build.build_wheel(tmp_path, settings)
    stamp = build_dir / "hatch-meson-environment.json"
    recorded = json.loads(stamp.read_text(encoding="utf-8"))
    assert field in recorded
    recorded[field] = "previous-environment"
    stamp.write_text(json.dumps(recorded), encoding="utf-8")

    run = mocker.spy(hatch_meson.plugin.MesonBuildHook, "_run")
    hatchling.build.build_wheel(tmp_path, settings)
    assert run.call_args_list[0].args[1][1:] == [
        "configure",
        "--clearcache",
        str(build_dir),
    ]
