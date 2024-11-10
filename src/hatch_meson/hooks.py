from hatchling.plugin import hookimpl

from .plugin import MesonBuildHook, MesonMetadataHook, MesonVersionSource


@hookimpl
def hatch_register_build_hook():
    return MesonBuildHook


@hookimpl
def hatch_register_metadata_hook():
    return MesonMetadataHook


@hookimpl
def hatch_register_version_source():
    return MesonVersionSource
