#!/usr/bin/env python3

import glob

from distutils.core import setup
from subprocess import check_output

from DistUtilsExtra.command import (
    build_extra, build_i18n)

for line in check_output('dpkg-parsechangelog --format rfc822'.split(),
                         universal_newlines=True).splitlines():
    header, colon, value = line.lower().partition(':')
    if header == 'version':
        # PEP 440 uses '!' for the epoch separator:
        #   https://peps.python.org/pep-0440/#version-epochs
        version = value.strip().replace(':','!')
        break
else:
    raise RuntimeError('No version found in debian/changelog')

setup(name='ubuntu-release-upgrader',
      version=version,
      packages=[
                'DistUpgrade',
                ],
      scripts=[
               "do-partial-upgrade",
               "do-release-upgrade",
               "kubuntu-devel-release-upgrade",
               "check-new-release-gtk",
               ],
      data_files=[
                  ('share/ubuntu-release-upgrader/gtkbuilder',
                   glob.glob("data/gtkbuilder/*.ui")
                  ),
                  ('share/ubuntu-release-upgrader/',
                   glob.glob("data/*.cfg")+
                   glob.glob("DistUpgrade/*.ui")+
                   ["DistUpgrade/deb2snap.json"]
                  ),
                  ('share/man/man8',
                   glob.glob('data/*.8')
                  ),
                  ('../etc/update-manager/', # intentionally use old name
                   ['data/release-upgrades', 'data/meta-release']),
                  ],
      cmdclass = { "build" : build_extra.build_extra,
                   "build_i18n" :  build_i18n.build_i18n }
      )
