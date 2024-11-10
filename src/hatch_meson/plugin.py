# SPDX-FileCopyrightText: 2021 Filipe Laíns <lains@riseup.net>
# SPDX-FileCopyrightText: 2021 Quansight, LLC
# SPDX-FileCopyrightText: 2022 The meson-python developers
# SPDX-FileCopyrightText: 2024 The hatch-meson developers
#
# SPDX-License-Identifier: MIT
#
# Lots of code ripped from meson-python and some limited pieces inspired by the
# scikit-build-core hatchling plugin also
#

import argparse
import collections
import functools
import importlib.machinery
import inspect
import json
import os
import pathlib
import platform
import re
import shutil
import subprocess
import sys
import sysconfig
import textwrap
import typing as T

from . import _tags
from .config import CmdlineConfig, HatchMesonConfig

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from hatchling.metadata.plugin.interface import MetadataHookInterface
from hatchling.version.source.plugin.interface import VersionSourceInterface

from validobj.validation import parse_input


# Terrible hack to get config_settings even though hatchling doesn't support it
# - https://github.com/pypa/hatch/issues/1072
def _get_cmdline_config_settings() -> T.Optional[T.Dict[str, T.Any]]:
    for frame_info in inspect.stack():
        frame = frame_info.frame
        module = inspect.getmodule(frame)
        if (
            module
            and module.__name__.startswith("hatchling.build")
            and "config_settings" in frame.f_locals
        ):
            return frame.f_locals["config_settings"]

    return None


_NINJA_REQUIRED_VERSION = "1.8.2"
_MESON_REQUIRED_VERSION = (
    "0.64.0"  # keep in sync with the version requirement in pyproject.toml
)


class Error(RuntimeError):
    def __str__(self) -> str:
        return str(self.args[0])


class ConfigError(Error):
    """Error in the backend configuration."""


class BuildError(Error):
    """Error when installing"""


_SUFFIXES = importlib.machinery.all_suffixes()
_EXTENSION_SUFFIX_REGEX = re.compile(r"^[^.]+\.(?:(?P<abi>[^.]+)\.)?(?:so|pyd|dll)$")
assert all(
    re.match(_EXTENSION_SUFFIX_REGEX, f"foo{x}")
    for x in importlib.machinery.EXTENSION_SUFFIXES
)

# Map Meson installation path placeholders to wheel installation paths.
# See https://docs.python.org/3/library/sysconfig.html#installation-paths
_INSTALLATION_PATH_MAP = {
    "{bindir}": "scripts",
    "{py_purelib}": "purelib",
    "{py_platlib}": "platlib",
    "{moduledir_shared}": "platlib",
    # hatchling doesn't support this, and nobody uses it anyways
    # "{includedir}": "headers",
    "{datadir}": "data",
    # custom location -- bundling not supported yet, and I'm not very comfortable
    # with how meson-python deals with this problem yet (but I don't have a good
    # rationale for this quite yet)
    # "{libdir}": "mesonpy-libs",
    # "{libdir_shared}": "mesonpy-libs",
}


def _map_to_wheel(
    sources: T.Dict[str, T.Dict[str, T.Any]]
) -> T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]]:
    """Map files to the wheel, organized by wheel installation directory."""
    wheel_files: T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]] = (
        collections.defaultdict(list)
    )
    # packages: T.Dict[str, str] = {}

    for key, group in sources.items():
        for src, target in group.items():
            destination = pathlib.Path(target["destination"])
            anchor = destination.parts[0]
            dst = pathlib.Path(*destination.parts[1:])

            path = _INSTALLATION_PATH_MAP.get(anchor)
            if path is None:
                raise BuildError(
                    f"Could not map installation path to an equivalent wheel directory: {str(destination)!r}"
                )

            # meson-python tries to support both purelib and platlib, but we're only going
            # to support one or the other. It'll be checked later.
            #
            # if path == "purelib" or path == "platlib":
            #     package = destination.parts[1]
            #     other = packages.setdefault(package, path)
            #     if other != path:
            #         this = os.fspath(pathlib.Path(path, *destination.parts[1:]))
            #         that = os.fspath(
            #             other
            #             / next(
            #                 d
            #                 for d, s in wheel_files[other]
            #                 if d.parts[0] == destination.parts[1]
            #             )
            #         )
            #         raise BuildError(
            #             f"The {package} package is split between {path} and {other}: "
            #             f'{this!r} and {that!r}, a "pure: false" argument may be missing in meson.build. '
            #             f"It is recommended to set it in \"import('python').find_installation()\""
            #         )

            if key == "install_subdirs" or key == "targets" and os.path.isdir(src):
                exclude_files = {
                    os.path.normpath(x) for x in target.get("exclude_files", [])
                }
                exclude_dirs = {
                    os.path.normpath(x) for x in target.get("exclude_dirs", [])
                }
                for root, dirnames, filenames in os.walk(src):
                    for name in dirnames.copy():
                        dirsrc = os.path.join(root, name)
                        relpath = os.path.relpath(dirsrc, src)
                        if relpath in exclude_dirs:
                            dirnames.remove(name)
                    # sort to process directories determninistically
                    dirnames.sort()
                    for name in sorted(filenames):
                        filesrc = os.path.join(root, name)
                        relpath = os.path.relpath(filesrc, src)
                        if relpath in exclude_files:
                            continue
                        filedst = dst / relpath
                        wheel_files[path].append((filedst, filesrc))
            else:
                wheel_files[path].append((dst, src))

    return wheel_files


def _is_native(fname) -> bool:
    """Check if file is a native file."""

    with open(fname, "rb") as f:
        if sys.platform == "darwin":
            return f.read(4) in (
                b"\xfe\xed\xfa\xce",  # 32-bit
                b"\xfe\xed\xfa\xcf",  # 64-bit
                b"\xcf\xfa\xed\xfe",  # arm64
                b"\xca\xfe\xba\xbe",  # universal / fat (same as java class so beware!)
            )
        elif sys.platform == "win32" or sys.platform == "cygwin":
            return f.read(2) == b"MZ"
        else:
            # Assume that any other platform uses ELF binaries.
            return f.read(4) == b"\x7fELF"  # ELF


def _install_is_pure(
    install_plan: T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]]
) -> bool:
    """Whether the wheel is architecture independent"""
    if install_plan["platlib"]:
        return False
    for _, src in install_plan["scripts"]:
        if _is_native(src):
            return False
    return True


def _compute_stable_abi(
    install_plan: T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]],
    limited_api: bool,
) -> T.Optional[str]:
    # PyPy supports the limited API but does not provide a stable
    # ABI, therefore extension modules using the limited API do
    # not use the stable ABI filename suffix and wheels should not
    # be tagged with the abi3 tag.
    if limited_api and "__pypy__" not in sys.builtin_module_names:
        # Verify stable ABI compatibility: examine files installed
        # in {platlib} that look like extension modules, and raise
        # an exception if any of them has a Python version
        # specific extension filename suffix ABI tag.
        for path, _ in install_plan["platlib"]:
            match = _EXTENSION_SUFFIX_REGEX.match(path.name)
            if match:
                abi = match.group("abi")
                if abi is not None and abi != "abi3":
                    raise BuildError(
                        f"The package declares compatibility with Python limited API but extension "
                        f"module {os.fspath(path)!r} is tagged for a specific Python version."
                    )
        return "abi3"
    return None


def _compute_tag(
    install_plan: T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]],
    limited_api: bool,
) -> _tags.Tag:
    """Wheel tags."""
    if _install_is_pure(install_plan):
        return _tags.Tag("py3", "none", "any")

    # Assume that all code installed in {platlib} is Python ABI dependent.
    if not install_plan["platlib"]:
        # The wheel has platform dependent code (is not pure) but
        # does not contain any extension module (does not
        # distribute any file in {platlib}) thus use generic
        # implementation and ABI tags.
        return _tags.Tag("py3", "none", None)

    return _tags.Tag(None, _compute_stable_abi(install_plan, limited_api), None)


def _aslist(s: T.Union[None, str, T.List[str]]) -> T.List[str]:
    if s is None:
        return []
    elif isinstance(s, str):
        return [s]
    return s


def _rmdashes(d: T.Optional[T.Dict[str, T.Any]]) -> T.Dict[str, T.Any]:
    if d is None:
        return {}

    return {k.replace("-", "_"): v for k, v in d.items()}


class MesonBuildHook(BuildHookInterface):

    PLUGIN_NAME = "meson"

    def initialize(self, version: str, build_data: T.Dict[str, T.Any]) -> None:
        # meson is not invoked when building an sdist
        if self.target_name != "wheel":
            return

        try:
            self._hook_config = parse_input(_rmdashes(self.config), HatchMesonConfig)
        except Exception as e:
            raise ConfigError(
                "[tool.hatch.build.hooks.meson] has incorrect configuration"
            ) from e

        self._setup_excludes()

        try:
            raw_config_settings = _rmdashes(_get_cmdline_config_settings())
            config_settings = parse_input(raw_config_settings, CmdlineConfig)
        except Exception as e:
            raise ConfigError("incorrect config settings passed to hatch-meson") from e

        # meson arguments from the command line take precedence over
        # arguments from the configuration file thus are added later
        self._hook_config.args.setup.extend(_aslist(config_settings.setup_args))
        self._hook_config.args.compile.extend(_aslist(config_settings.compile_args))
        self._hook_config.args.install.extend(_aslist(config_settings.install_args))

        self._source_dir = pathlib.Path(self.root)
        if config_settings.build_dir is not None:
            self._build_dir = pathlib.Path(config_settings.build_dir)
        else:
            self._build_dir = self._source_dir / "build" / _tags.get_abi_tag()

        self._meson_native_file = self._build_dir / "hatch-meson-native-file.ini"
        self._meson_cross_file = self._build_dir / "hatch-meson-cross-file.ini"

        self._meson = _get_meson_command(self._hook_config.meson)

        self._ninja = _env_ninja_command()
        if self._ninja is None:
            raise ConfigError(
                f"Could not find ninja version {_NINJA_REQUIRED_VERSION} or newer."
            )
        os.environ.setdefault("NINJA", self._ninja)

        self._build_dir.mkdir(parents=True, exist_ok=True)

        if _create_macos_crossfile(self._meson_cross_file):
            self._hook_config.args.setup += [
                "--cross-file",
                os.fspath(self._meson_cross_file),
            ]

        # write the native file
        native_file_data = textwrap.dedent(
            f"""
            [binaries]
            python = '{sys.executable}'
        """
        )
        self._meson_native_file.write_text(native_file_data, encoding="utf-8")

        # reconfigure if we have a valid Meson build directory. Meson
        # uses the presence of the 'meson-private/coredata.dat' file
        # in the build directory as indication that the build
        # directory has already been configured and arranges this file
        # to be created as late as possible or deleted if something
        # goes wrong during setup.
        reconfigure = (self._build_dir / "meson-private" / "coredata.dat").is_file()
        self._run_configure(reconfigure)

        # limited API
        self._limited_api = self._hook_config.limited_api
        if self._limited_api:
            # check whether limited API is disabled for the Meson project
            options = self._info("intro-buildoptions")
            value = next(
                (
                    option["value"]
                    for option in options
                    if option["name"] == "python.allow_limited_api"
                ),
                None,
            )
            if not value:
                self._limited_api = False

        if self._limited_api and bool(sysconfig.get_config_var("Py_GIL_DISABLED")):
            raise BuildError(
                "The package targets Python's Limited API, which is not supported by free-threaded CPython. "
                'The "python.allow_limited_api" Meson build option may be used to override the package default.'
            )

        # Time to build
        self._run_build()

        # Take anything that meson would have installed, and make sure that hatchling
        # will also install it
        install_plan = self._get_meson_install_plan()
        artifacts: T.List[str] = []

        # Scripts are just handled by hatchling
        for dst, src in install_plan["scripts"]:
            build_data["shared_scripts"][src] = dst.as_posix()

        # As is data
        for dst, src in install_plan["datadir"]:
            build_data["shared_data"][src] = dst.as_posix()

        # platlib, purelib are copied to the build tree in the package source path
        try:
            package_sources = list(self.build_config.sources)
        except ValueError:
            package_sources = []

        force_include = build_data["force_include"]
        if package_sources:
            pkgsrc: pathlib.Path = self._source_dir / package_sources[0]
        else:
            pkgsrc = self._source_dir

        # Only allow either purelib or platlib, not both
        if install_plan["purelib"] and install_plan["platlib"]:
            raise BuildError(
                "The install plan contains both purelib and platlib components, a "
                "'pure: false' argument may be missing in meson.build. "
                "It is recommended to set it in \"import('python').find_installation()\""
            )

        # copy purelib/platlib artifacts
        # - this is the desired behavior in editable mode as it allows other
        #   hatchling build hooks to do things with the files
        # - when making a real wheel, we could just always map it in via force_include,
        #   but if the user tries to make a wheel from a directory previously
        #   used in editable mode then hatchling may create a zipfile with two
        #   items of the same name in them... so just copy the file
        # - but if the user didn't tell hatchling which packages to use, if something
        #   was added to purelib/platlib then we add it to force_include

        for dstrel, src in install_plan["purelib"] + install_plan["platlib"]:
            dst = pkgsrc / dstrel

            force_include[str(dst)] = dstrel.as_posix()
            artifacts.append(dst.as_posix())

            if str(dst) == str(src):
                continue

            dst.parent.mkdir(parents=True, exist_ok=True)

            shutil.copy(src, dst)

        tag = _compute_tag(install_plan, self._limited_api)

        is_pure = _install_is_pure(install_plan)
        if not is_pure:
            build_data["pure_python"] = False

        build_data["tag"] = str(tag)
        build_data["artifacts"].extend(artifacts)

    def clean(self, versions: T.List[str]) -> None:
        # TODO
        pass

    def dependencies(self) -> T.List[str]:
        return _get_requires_for_build_wheel()

    def _setup_excludes(self):
        to_exclude = ["meson.build"]

        # Feels like a hack, but it works? https://github.com/pypa/hatch/issues/1787
        # - should we exclude common source files by default, or make the user specify
        #   them? My gut says let the user do it, otherwise we have to provide an option
        #   to override it.
        build_config = self.build_config.build_config
        wheel_config = build_config.get("targets", {}).get("wheel", {})
        if "exclude" in wheel_config:
            wheel_config["exclude"] += to_exclude
        elif "exclude" in build_config:
            build_config["exclude"] += to_exclude
        else:
            build_config["exclude"] = to_exclude

    def _run_configure(self, reconfigure: bool = False) -> None:
        """Configure Meson project."""

        # TODO: only run this when configure args have changed
        setup_args = [
            os.fspath(self._source_dir),
            os.fspath(self._build_dir),
            # default build options
            "-Dbuildtype=release",
            "-Db_ndebug=if-release",
            "-Db_vscrt=md",
            # user build options
            *self._hook_config.args.setup,
            # pass native file last to have it override the python
            # interpreter path that may have been specified in user
            # provided native files
            f"--native-file={os.fspath(self._meson_native_file)}",
        ]
        if reconfigure:
            setup_args.insert(0, "--reconfigure")
        self._run(self._meson + ["setup", *setup_args])

    @property
    def _build_command(self) -> T.List[str]:
        assert self._ninja is not None  # help mypy out
        if sys.platform == "win32":
            # On Windows use 'meson compile' to setup the MSVC compiler
            # environment. Using the --ninja-args option allows to
            # provide the exact same semantics for the compile arguments
            # provided by the users.
            cmd = self._meson + ["compile"]
            args = self._hook_config.args.compile
            if args:
                cmd.append(f"--ninja-args={args!r}")
            return cmd
        return [self._ninja, *self._hook_config.args.compile]

    @functools.lru_cache(maxsize=None)
    def _run_build(self) -> None:
        """Build the Meson project."""
        self._run(self._build_command)

    @functools.lru_cache()
    def _info(self, name: str) -> T.Any:
        """Read info from meson-info directory."""
        info = self._build_dir.joinpath("meson-info", f"{name}.json")
        return json.loads(info.read_text(encoding="utf-8"))

    def _get_meson_install_plan(
        self,
    ) -> T.DefaultDict[str, T.List[T.Tuple[pathlib.Path, str]]]:
        """The files to be added to the wheel, organized by wheel path."""

        # Obtain the list of files Meson would install.
        install_plan = self._info("intro-install_plan")

        # Parse the 'meson install' args to extract --tags and --skip-subprojects
        parser = argparse.ArgumentParser(add_help=False)
        parser.add_argument("--tags")
        parser.add_argument("--skip-subprojects", nargs="?", const="*", default="")
        args, _ = parser.parse_known_args(self._hook_config.args.install)
        install_tags = {t.strip() for t in args.tags.split(",")} if args.tags else None
        skip_subprojects = {
            p for p in (p.strip() for p in args.skip_subprojects.split(",")) if p
        }

        # Filter the install plan accordingly.
        sources: T.DefaultDict[str, T.Dict[str, T.Dict[str, str]]] = (
            collections.defaultdict(dict)
        )
        for key, targets in install_plan.items():
            for target, details in targets.items():
                if install_tags is not None and details["tag"] not in install_tags:
                    continue
                subproject = details.get("subproject")
                if subproject is not None and (
                    subproject in skip_subprojects or "*" in skip_subprojects
                ):
                    continue
                sources[key][target] = details

        # Map Meson installation locations to wheel paths.
        return _map_to_wheel(sources)

    def _run(self, cmd: T.Sequence[str]):
        # Flush the line to ensure that the log line with the executed
        # command line appears before the command output. Without it,
        # the lines appear in the wrong order in pip output.
        self.app.display_info(f"+ {' '.join(cmd)}")
        r = subprocess.run(cmd, cwd=self._build_dir)
        if r.returncode != 0:
            raise SystemExit(r.returncode)


def _get_meson_projectinfo(cwd):
    meson = _get_meson_command(None)
    result = subprocess.run(
        meson + ["introspect", "meson.build", "--projectinfo"],
        cwd=cwd,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        raise BuildError(f"meson introspect failed: {result.stdout}")

    return json.loads(result.stdout)


class MesonMetadataHook(MetadataHookInterface):
    PLUGIN_NAME = "meson"

    def update(self, metadata: T.Dict):
        md = _get_meson_projectinfo(self.root)
        metadata["name"] = md["descriptive_name"]


class MesonVersionSource(VersionSourceInterface):
    PLUGIN_NAME = "meson"

    def get_version_data(self):
        md = _get_meson_projectinfo(self.root)
        if md["version"] == "undefined":
            raise BuildError("version not set for project() in meson.build")

        return {"version": md["version"]}


def _get_requires_for_build_wheel() -> T.List[str]:
    dependencies = []

    if os.environ.get("NINJA") is None and _env_ninja_command() is None:
        dependencies.append(f"ninja >= {_NINJA_REQUIRED_VERSION}")

    return dependencies


def _parse_version_string(string: str) -> T.Tuple[int, ...]:
    """Parse version string."""
    try:
        return tuple(map(int, string.split(".")[:3]))
    except ValueError:
        return (0,)


def _get_meson_command(
    meson: T.Optional[str] = None, *, version: str = _MESON_REQUIRED_VERSION
) -> T.List[str]:
    """Return the command to invoke meson."""

    # The MESON env var, if set, overrides the config value from pyproject.toml.
    # The config value, if given, is an absolute path or the name of an executable.
    meson = os.environ.get("MESON", meson or "meson")

    # If the specified Meson string ends in `.py`, we run it with the current
    # Python executable. This avoids problems for users on Windows, where
    # making a script executable isn't enough to get it to run when invoked
    # directly. For packages that vendor a forked Meson, the `meson.py` in the
    # root of the Meson repo can be used this way.
    if meson.endswith(".py"):
        if not os.path.exists(meson):
            raise ConfigError(f'Could not find the specified meson: "{meson}"')
        cmd = [sys.executable, os.path.abspath(meson)]
    else:
        cmd = [meson]

    # The meson Python package is a dependency of the hatch-meson Python
    # package, however, it may occur that the meson Python package is installed
    # but the corresponding meson command is not available in $PATH. Implement
    # a runtime check to verify that the build environment is setup correcly.
    try:
        r = subprocess.run(cmd + ["--version"], text=True, capture_output=True)
    except FileNotFoundError as err:
        raise ConfigError(f'meson executable "{meson}" not found') from err
    if r.returncode != 0:
        raise ConfigError(f"Could not execute meson: {r.stderr.strip()}")
    meson_version = r.stdout.strip()

    if _parse_version_string(meson_version) < _parse_version_string(version):
        raise ConfigError(
            f"Could not find meson version {version} or newer, found {meson_version}."
        )

    return cmd


def _env_ninja_command(*, version: str = _NINJA_REQUIRED_VERSION) -> T.Optional[str]:
    """Returns the path to ninja, or None if no ninja found."""
    required_version = _parse_version_string(version)
    env_ninja = os.environ.get("NINJA")
    ninja_candidates = [env_ninja] if env_ninja else ["ninja", "ninja-build", "samu"]
    for ninja in ninja_candidates:
        ninja_path = shutil.which(ninja)
        if ninja_path is not None:
            version = subprocess.run(
                [ninja_path, "--version"], check=False, text=True, capture_output=True
            ).stdout
            if _parse_version_string(version) >= required_version:
                return ninja_path
    return None


def _create_macos_crossfile(crossfile_path: pathlib.Path) -> bool:
    """setuptools-like ARCHFLAGS environment variable support"""
    if sysconfig.get_platform().startswith("macosx-"):
        archflags = os.environ.get("ARCHFLAGS", "").strip()
        if archflags:

            # parse the ARCHFLAGS environment variable
            parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
            parser.add_argument("-arch", action="append")
            args, unknown = parser.parse_known_args(archflags.split())
            if unknown:
                raise ConfigError(f"Unknown flag specified in $ARCHFLAGS={archflags!r}")
            arch, *other = set(args.arch)
            if other:
                raise ConfigError(
                    f"Multi-architecture builds are not supported but $ARCHFLAGS={archflags!r}"
                )

            macver, _, nativearch = platform.mac_ver()
            if arch != nativearch:
                x = os.environ.setdefault(
                    "_PYTHON_HOST_PLATFORM", f"macosx-{macver}-{arch}"
                )
                if not x.endswith(arch):
                    raise ConfigError(
                        f"$ARCHFLAGS={archflags!r} and $_PYTHON_HOST_PLATFORM={x!r} do not agree"
                    )
                family = "aarch64" if arch == "arm64" else arch
                cross_file_data = textwrap.dedent(
                    f"""
                    [binaries]
                    c = ['cc', '-arch', {arch!r}]
                    cpp = ['c++', '-arch', {arch!r}]
                    objc = ['cc', '-arch', {arch!r}]
                    objcpp = ['c++', '-arch', {arch!r}]
                    [host_machine]
                    system = 'darwin'
                    cpu = {arch!r}
                    cpu_family = {family!r}
                    endian = 'little'
                """
                )
                crossfile_path.write_text(cross_file_data, encoding="utf-8")
                return True

    return False
