hatch-meson
===========

Hatchling plugins that allow building native extensions using Meson and bundling
them into your python projects that use Hatchling.

Should I use this?
------------------

If you want to build python wheels that contain native extensions built using
Meson... you probably should use [meson-python](https://github.com/mesonbuild/meson-python)
and not use this project.

### Why does this exist then?

Meson is great for building native libraries due to its simple, straightforward
build syntax. This simplicity is one of its most compelling features, but
at the same time can make it impossible to accomplish something that the Meson
designers did not intend to make possible.

As a Hatchling build plugin, this project allows you to leverage Meson to handle
what it does best, and use other Hatchling plugins for tasks Meson doesn’t support.

When using hatch-meson, it is intended that you only use meson for things that
require a build system, and that you use Hatchling features for other aspects
of packaging a python project.

### How is this different from meson-python

The initial version of hatch-meson contains a lot of code that is copied directly
from `meson-python`, as are the initial set of tests, so it's not that different.
However, there are some differences.

* Creating a source distribution only uses Hatchling, so scripts added via
  `meson.add_dist_script` are not ran
* Currently this does not bundle libraries into your wheel
* Editable installs are supported, but with key differences
  * Built artifacts are copied into the source tree
  * Importing your project will not automatically trigger a rebuild
* It is not required to use `py.install_sources` to specify all of your python
  files. You can if you want, but it is recommended to use Hatchling's
  standard mechanisms for doing this instead
* Will not create wheels that contain both purelib and platlib packages

While hatch-meson will try to support many of the same things that meson-python
supports, it is not a goal to have the exact same behavior.

Documentation
-------------

TODO, but much of the meson-python documentation applies. Except the parts that don't.

All of the options supported in `pyproject.toml` can be found in the dataclasses
at [src/hatch_meson/config.py](src/hatch_meson/config.py)

Usage
-----

Use this `pyproject.toml` to retrieve the name/version from your `meson.build`:

```toml
[build-system]
build-backend = "hatchling.build"
requires = ["hatch-meson"]

[project]
dynamic = ["name", "version"]

[tool.hatch.version]
source = "meson"

[tool.hatch.build.hooks.meson]
[tool.hatch.metadata.hooks.meson]
```

If you prefer to use the standard Hatchling project settings, you can omit
the version and metadata hooks.

```toml
[build-system]
build-backend = "hatchling.build"
requires = ["hatch-meson"]

[project]
name = "myproject"
# version needs to be either specified here or you can use a different hatch
# plugin to set the version


[tool.hatch.build.hooks.meson]
[tool.hatch.metadata.hooks.meson]
```

Building an sdist and wheel can be done using standard python build tooling. Refer
to the hatch documentation for more details.

Credit
------

The meson-python project drove a lot of changes in meson to make it possible to
build wheels using meson. Much of the code and tests for this package are directly
copied from the meson-python project, and this would have been way more work if
it didn't exist.

All bugs in hatch-meson are probably my fault.
