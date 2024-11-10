# SPDX-FileCopyrightText: 2021 The meson-python developers
#
# SPDX-License-Identifier: MIT

project('install-tags',  version: '1.0.0')

py = import('python').find_installation()

py.install_sources(
    'pkg1.py',
    install_tag: 'pkg1',
)

py.install_sources(
    'pkg2.py',
    install_tag: 'pkg2',
)
