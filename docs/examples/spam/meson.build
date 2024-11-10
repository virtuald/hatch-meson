# SPDX-FileCopyrightText: 2022 The meson-python developers
# SPDX-FileCopyrightText: 2024 The hatch-meson developers
#
# SPDX-License-Identifier: MIT

project('spam', 'c')

py = import('python').find_installation()

# Specify directories to be included - usually this is where your header files live.
# Note that specifying the path to Python.h is not necessary with meson-python.
includes = include_directories('src/spam')

srcs = [
    'src/spam/spammodule.c',
]

# When building an extension module, 'subdir' argument indicates where
# the module is installed (<python directory>/site-packages/<subdir>)
py.extension_module(
    '_spam',
    srcs,
    install: true,
    subdir: 'spam',
    include_directories: includes,
)

# The directory layout of this project follows hatchling's default file
# selection heuristics, so nothing else is needed here to bundle the python
# files in the wheel.
