import dataclasses
import typing as T

# Cannot use `from __future__ import annotations` because validobj does not
# support annotations


@dataclasses.dataclass
class MesonArgs:
    """
    Contents of [tool.hatch.build.hooks.meson.args] items
    """

    setup: T.List[str] = dataclasses.field(default_factory=list)
    """Additional args to pass to ``meson setup``"""

    compile: T.List[str] = dataclasses.field(default_factory=list)
    """Additional args to pass to ninja or ``meson compile``"""

    install: T.List[str] = dataclasses.field(default_factory=list)
    """Arguments to ``meson install``"""

    # hatch-meson does not use `meson dist`


@dataclasses.dataclass
class HatchMesonConfig:
    """
    Contents of [tool.hatch.build.hooks.meson] items
    """

    meson: T.Optional[str] = None
    """Meson to use"""

    limited_api: bool = False
    """Build extension modules targeting the limited API"""

    args: MesonArgs = dataclasses.field(default_factory=lambda: MesonArgs())


@dataclasses.dataclass
class CmdlineConfig:
    """
    Contents of config settings passed in through a build tool
    """

    build_dir: T.Optional[str] = None
    editable_verbose: bool = False

    # dist_args: T.Union[None, str, T.List[str]] = None
    setup_args: T.Union[None, str, T.List[str]] = None
    compile_args: T.Union[None, str, T.List[str]] = None
    install_args: T.Union[None, str, T.List[str]] = None
