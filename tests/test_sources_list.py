#!/usr/bin/python3
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

from __future__ import print_function

import apt_pkg
import distro_info
import glob
import inspect
import os
import shutil
import subprocess
import unittest
from DistUpgrade.DistUpgradeController import (
    DistUpgradeController,
    component_ordering_key,
)
from DistUpgrade.DistUpgradeViewNonInteractive import (
    DistUpgradeViewNonInteractive,
)
from DistUpgrade import DistUpgradeConfigParser
from DistUpgrade.utils import url_downloadable
from DistUpgrade.distro import (
    UbuntuDistribution,
    NoDistroTemplateException
)
import logging
import mock

DistUpgradeConfigParser.CONFIG_OVERRIDE_DIR = None

CURDIR = os.path.dirname(os.path.abspath(__file__))
dpkg = subprocess.Popen(['dpkg', '--print-architecture'],
                        stdout=subprocess.PIPE)
ARCH = dpkg.communicate()[0].decode().strip()
di = distro_info.UbuntuDistroInfo()
LTSES = [supported for supported in di.supported()
         if di.is_lts(supported)]


class TestComponentOrdering(unittest.TestCase):

    def test_component_ordering_key_from_set(self):
        self.assertEqual(
            sorted(set(["x", "restricted", "main"]),
                   key=component_ordering_key),
            ["main", "restricted", "x"])

    def test_component_ordering_key_from_list(self):
        self.assertEqual(
            sorted(["x", "main"], key=component_ordering_key),
            ["main", "x"])
        self.assertEqual(
            sorted(["restricted", "main"],
                   key=component_ordering_key),
            ["main", "restricted"])
        self.assertEqual(
            sorted(["main", "restricted"],
                   key=component_ordering_key),
            ["main", "restricted"])
        self.assertEqual(
            sorted(["main", "multiverse", "restricted", "universe"],
                   key=component_ordering_key),
            ["main", "restricted", "universe", "multiverse"])
        self.assertEqual(
            sorted(["a", "main", "multiverse", "restricted", "universe"],
                   key=component_ordering_key),
            ["main", "restricted", "universe", "multiverse", "a"])


class TestSourcesListUpdate(unittest.TestCase):

    testdir = os.path.abspath(CURDIR + "/data-sources-list-test/")

    def setUp(self):
        apt_pkg.config.set("Dir::Etc", self.testdir)
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        if os.path.exists(os.path.join(self.testdir, "sources.list")):
            os.unlink(os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("APT::Default-Release", "")

    def tearDown(self):
        if os.path.exists(os.path.join(self.testdir, "sources.list")):
            os.unlink(os.path.join(self.testdir, "sources.list"))

    def test_sources_list_with_nothing(self):
        """
        test sources.list rewrite with nothing in it
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.nothing"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)

        # now test the result
        self._verifySources("""
deb http://archive.ubuntu.com/ubuntu gutsy main restricted
deb http://archive.ubuntu.com/ubuntu gutsy-updates main restricted
deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted
""")

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_sources_list_rewrite(self, mock_get_distro, mock_sourcesListEntryDownloadable):
        """
        test regular sources.list rewrite
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.in"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        #print(open(os.path.join(self.testdir,"sources.list")).read())
        if ARCH in ('amd64', 'i386'):
            self._verifySources("""
# main repo
deb http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse universe
deb http://archive.ubuntu.com/ubuntu/ gutsy main restricted multiverse
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse
deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted multiverse
deb http://security.ubuntu.com/ubuntu/ gutsy-security universe
""")
        else:
            self._verifySources("""
# main repo
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy main restricted multiverse universe
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy main restricted multiverse
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-security main restricted multiverse
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-security universe
""")
        # check that the backup file was created correctly
        self.assertEqual(0, subprocess.call(
            ["cmp",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".in",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".distUpgrade"
             ]))

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_sources_list_rewrite_no_network(self, mock_get_distro, mock_sourcesListEntryDownloadable):
        """
        test sources.list rewrite no network
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.in"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = False
        res = d.updateSourcesList()
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        #print(open(os.path.join(self.testdir,"sources.list")).read())
        if ARCH in ('amd64', 'i386'):
            self._verifySources("""
# main repo
# deb http://archive.ubuntu.com/ubuntu feisty main restricted multiverse universe
# deb http://archive.ubuntu.com/ubuntu/ feisty main restricted multiverse
# deb-src http://archive.ubuntu.com/ubuntu feisty main restricted multiverse
# deb http://security.ubuntu.com/ubuntu/ feisty-security main restricted
# deb http://security.ubuntu.com/ubuntu/ feisty-security universe
""")
        else:
            self._verifySources("""
# main repo
# deb http://ports.ubuntu.com/ubuntu-ports/ feisty main restricted multiverse universe
# deb http://ports.ubuntu.com/ubuntu-ports/ feisty main restricted multiverse
# deb-src http://archive.ubuntu.com/ubuntu feisty main restricted multiverse
# deb http://ports.ubuntu.com/ubuntu-ports/ feisty-security main restricted
# deb http://ports.ubuntu.com/ubuntu-ports/ feisty-security universe
""")

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController.abort")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_double_check_source_distribution_reject(self, mock_abort, mock_get_distro):
        """
        test that an upgrade from feisty with a sources.list containing
        hardy asks a question, and if rejected, aborts the upgrade.
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.hardy"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = mock.Mock()
        v.askYesNoQuestion.return_value=False
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")

        class AbortException(Exception):
            """Exception"""

        mock_abort.side_effect = AbortException
        d.openCache(lock=False)
        with self.assertRaises(AbortException):
            d.updateSourcesList()
        self.assertTrue(mock_abort.called)
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(v.askYesNoQuestion.called)

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_double_check_source_distribution_continue(self, mock_get_distro, mock_sourcesListEntryDownloadable):
        """
        test that an upgrade from feisty with a sources.list containing
        hardy asks a question, and if continued, does something.
        """
        arch = apt_pkg.config.find("APT::Architecture")
        apt_pkg.config.set("APT::Architecture", "amd64")

        shutil.copy(os.path.join(self.testdir, "sources.list.hardy"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = mock.Mock()
        v.askYesNoQuestion.return_value=True
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        #print(open(os.path.join(self.testdir,"sources.list")).read())

        # The result here is not really all that helpful, hence we
        # added the question in the first place. But still better to
        # check what it does than to not check it.
        self._verifySources2Way("""
# main repo
# deb cdrom:[Ubuntu 8.10 _foo]/ hardy main
# deb ftp://uk.archive.ubuntu.com/ubuntu/ hardy main restricted multiverse universe
# deb http://de.archive.ubuntu.com/ubuntu/ hardy main restricted multiverse
deb-src http://uk.archive.ubuntu.com/ubuntu/ hardy main restricted multiverse

# deb http://security.ubuntu.com/ubuntu/ hardy-security main restricted
# deb http://security.ubuntu.com/ubuntu/ hardy-security universe

deb http://archive.ubuntu.com/ubuntu gutsy main

""")
        # check that the backup file was created correctly
        self.assertEqual(0, subprocess.call(
            ["cmp",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".hardy",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".distUpgrade"
             ]))
        apt_pkg.config.set("APT::Architecture", arch)

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_sources_list_inactive_mirror(self, mock_get_distro, mock_sourcesListEntryDownloadable):
        """
        test sources.list rewrite of an obsolete mirror
        """
        arch = apt_pkg.config.find("APT::Architecture")
        apt_pkg.config.set("APT::Architecture", "amd64")
        shutil.copy(os.path.join(self.testdir, "sources.list.obsolete_mirror"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        #print(open(os.path.join(self.testdir,"sources.list")).read())
        self._verifySources2Way("""
# main repo
# deb http://mirror.mcs.anl.gov/ubuntu gutsy main restricted universe multiverse # disabled on upgrade to gutsy
# deb http://mirror.mcs.anl.gov/ubuntu gutsy-updates main restricted universe multiverse # disabled on upgrade to gutsy
# deb http://mirror.mcs.anl.gov/ubuntu feisty-proposed main restricted universe multiverse
# deb http://mirror.mcs.anl.gov/ubuntu gutsy-security main restricted universe multiverse # disabled on upgrade to gutsy
# deb-src http://mirror.mcs.anl.gov/ubuntu gutsy main restricted universe multiverse # disabled on upgrade to gutsy
# deb-src http://mirror.mcs.anl.gov/ubuntu gutsy-updates main restricted universe multiverse # disabled on upgrade to gutsy
##deb-src http://mirror.mcs.anl.gov/ubuntu feisty-proposed main restricted universe multiverse
# deb-src http://mirror.mcs.anl.gov/ubuntu gutsy-security main restricted universe multiverse # disabled on upgrade to gutsy
# deb https://example.com/3rd-party/deb/ stable main # disabled on upgrade to gutsy
deb http://archive.ubuntu.com/ubuntu gutsy main
deb http://archive.ubuntu.com/ubuntu gutsy main restricted universe multiverse # auto generated by ubuntu-release-upgrader
deb http://archive.ubuntu.com/ubuntu gutsy-updates main restricted universe multiverse # auto generated by ubuntu-release-upgrader
deb http://archive.ubuntu.com/ubuntu gutsy-security main restricted universe multiverse # auto generated by ubuntu-release-upgrader
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted universe multiverse # auto generated by ubuntu-release-upgrader
deb-src http://archive.ubuntu.com/ubuntu gutsy-updates main restricted universe multiverse # auto generated by ubuntu-release-upgrader
deb-src http://archive.ubuntu.com/ubuntu gutsy-security main restricted universe multiverse # auto generated by ubuntu-release-upgrader
""")
        # check that the backup file was created correctly
        self.assertEqual(0, subprocess.call(
            ["cmp",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".obsolete_mirror",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".distUpgrade"
             ]))
        apt_pkg.config.set("APT::Architecture", arch)

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_sources_list_no_template(self, mock_get_distro):
        """
        test sources.list rewrite for a mirror when there is no distro template
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.obsolete_mirror"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        mock_get_distro.side_effect = NoDistroTemplateException("No distro template.")
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(mock_get_distro.called)
        self.assertTrue(res)

        # now test the result
        #print(open(os.path.join(self.testdir,"sources.list")).read())
        self._verifySources("""
# main repo
# deb http://mirror.mcs.anl.gov/ubuntu gutsy main restricted universe multiverse # disabled on upgrade to gutsy
# deb http://mirror.mcs.anl.gov/ubuntu feisty-updates main restricted universe multiverse # disabled on upgrade to gutsy
# deb http://mirror.mcs.anl.gov/ubuntu feisty-proposed main restricted universe multiverse
# deb http://mirror.mcs.anl.gov/ubuntu feisty-security main restricted universe multiverse # disabled on upgrade to gutsy
# deb-src http://mirror.mcs.anl.gov/ubuntu gutsy main restricted universe multiverse # disabled on upgrade to gutsy
# deb-src http://mirror.mcs.anl.gov/ubuntu feisty-updates main restricted universe multiverse # disabled on upgrade to gutsy
##deb-src http://mirror.mcs.anl.gov/ubuntu feisty-proposed main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu gutsy main restricted # auto generated by ubuntu-release-upgrader
deb http://archive.ubuntu.com/ubuntu gutsy-updates main restricted # auto generated by ubuntu-release-upgrader
deb http://security.ubuntu.com/ubuntu gutsy-security main restricted # auto generated by ubuntu-release-upgrader
# deb-src http://mirror.mcs.anl.gov/ubuntu feisty-security main restricted universe multiverse # disabled on upgrade to gutsy
""")

        # check that the backup file was created correctly
        self.assertEqual(0, subprocess.call(
            ["cmp",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".obsolete_mirror",
             apt_pkg.config.find_file("Dir::Etc::sourcelist") + ".distUpgrade"
             ]))

    def test_partner_deprecation(self):
        """
        test removal of partner archive
        """
        shutil.copy(os.path.join(self.testdir,
                                 "sources.list.partner-deprecation"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)

        # now test the result
        self._verifySources("""
""")

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "extras was not for ports")
    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    @mock.patch("DistUpgrade.DistUpgradeController.get_distro")
    def test_extras_removal(self, mock_get_distro, mock_sourcesListEntryDownloadable):
        """
        test removal of extras.ubuntu.com archives
        """
        original = os.path.join(self.testdir,
                                 "sources.list.extras")
        shutil.copy(original,
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        mock_get_distro.return_value = UbuntuDistribution("Ubuntu", "feisty",
                                                          "Ubuntu Feisty Fawn",
                                                          "7.04")
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        sources_file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        self.assertEqual(open(sources_file).read(),"""deb http://archive.ubuntu.com/ubuntu gutsy main restricted
deb http://archive.ubuntu.com/ubuntu gutsy-updates main restricted
deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted

""")

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_powerpc_transition(self, mock_sourcesListEntryDownloadable):
        """
        test transition of powerpc to ports.ubuntu.com
        """
        arch = apt_pkg.config.find("APT::Architecture")
        apt_pkg.config.set("APT::Architecture", "powerpc")
        shutil.copy(os.path.join(self.testdir, "sources.list.powerpc"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)
        # now test the result
        self._verifySources("""
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse

deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-security main restricted universe multiverse
""")
        apt_pkg.config.set("APT::Architecture", arch)

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_sparc_transition(self, mock_sourcesListEntryDownloadable):
        """
        test transition of sparc to ports.ubuntu.com
        """
        arch = apt_pkg.config.find("APT::Architecture")
        apt_pkg.config.set("APT::Architecture", "sparc")
        shutil.copy(os.path.join(self.testdir, "sources.list.sparc"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = "gutsy"
        d.toDist = "hardy"
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)
        # now test the result
        self._verifySources("""
deb http://ports.ubuntu.com/ubuntu-ports/ hardy main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu hardy main restricted multiverse

deb http://ports.ubuntu.com/ubuntu-ports/ hardy-security main restricted universe multiverse
""")
        apt_pkg.config.set("APT::Architecture", arch)

    def testVerifySourcesListEntry(self):
        from aptsources.sourceslist import SourceEntry
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        to_dist = LTSES[-2]
        for scheme in ["http"]:
            entry = "deb %s://archive.ubuntu.com/ubuntu/ %s main universe restricted multiverse" % \
                    (scheme, to_dist)
            self.assertTrue(d._sourcesListEntryDownloadable(SourceEntry(entry)),
                            "entry '%s' not downloadable" % entry)
            entry = "deb %s://archive.ubuntu.com/ubuntu/ warty main universe restricted multiverse" % scheme
            self.assertFalse(d._sourcesListEntryDownloadable(SourceEntry(entry)),
                             "entry '%s' not downloadable" % entry)
            entry = "deb %s://archive.ubuntu.com/ubuntu/ xxx main" % scheme
            self.assertFalse(d._sourcesListEntryDownloadable(SourceEntry(entry)),
                             "entry '%s' not downloadable" % entry)

    def testEOL2EOLUpgrades(self):
        " test upgrade from EOL release to EOL release "
        shutil.copy(os.path.join(self.testdir, "sources.list.EOL"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = "warty"
        d.toDist = "hoary"
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)
        self._verifySources("""
# main repo
deb http://old-releases.ubuntu.com/ubuntu hoary main restricted multiverse universe
deb-src http://old-releases.ubuntu.com/ubuntu hoary main restricted multiverse

deb http://old-releases.ubuntu.com/ubuntu hoary-security main restricted universe multiverse
""")

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @unittest.skipUnless(url_downloadable(
        "http://us.archive.ubuntu.com/ubuntu", logging.debug),
        "Could not reach mirror")
    def testEOL2SupportedWithMirrorUpgrade(self):
        " test upgrade from a EOL release to a supported release with mirror "
        # Use us.archive.ubuntu.com, because it is available in Canonical's
        # data center, unlike most mirrors.  This lets this test pass when
        # when run in their Jenkins test environment.
        to_dist = LTSES[-2]
        from_dist = di.all[di.all.index(to_dist) - 1]
        os.environ["LANG"] = "en_US.UTF-8"
        with open(os.path.join(self.testdir, "sources.list"), "w") as f:
            f.write("""
# main repo
deb http://old-releases.ubuntu.com/ubuntu %s main restricted multiverse universe
deb-src http://old-releases.ubuntu.com/ubuntu %s main restricted multiverse

deb http://old-releases.ubuntu.com/ubuntu %s-security main restricted
""" % (from_dist, from_dist, from_dist))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = from_dist
        d.toDist = to_dist
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)
        self._verifySources("""
# main repo
deb http://us.archive.ubuntu.com/ubuntu %s main restricted multiverse universe
deb-src http://us.archive.ubuntu.com/ubuntu %s main restricted multiverse

deb http://us.archive.ubuntu.com/ubuntu %s-security main restricted universe multiverse
""" % (to_dist, to_dist, to_dist))

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @unittest.skipUnless(url_downloadable(
        "https://mirrors.kernel.org/ubuntu", logging.debug),
        "Could not reach mirror")
    def testSupportedWithHttpsMirrorUpgrade(self):
        " test upgrade from to a supported release with https mirror "
        # Use mirrors.kernel.org because it supports https, when the main
        # archive does we should switch that.
        os.environ["LANG"] = "en_US.UTF-8"
        shutil.copy(os.path.join(self.testdir, "sources.list.https"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = "xenial"
        d.toDist = "bionic"
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)
        self._verifySources("""
# main repo
deb https://mirrors.kernel.org/ubuntu bionic main restricted multiverse universe
deb-src https://mirrors.kernel.org/ubuntu bionic main restricted multiverse

deb https://mirrors.kernel.org/ubuntu bionic-security main restricted universe multiverse
""")

    def testEOL2SupportedUpgrade(self):
        " test upgrade from a EOL release to a supported release "
        to_dist = LTSES[-2]
        from_dist = di.all[di.all.index(to_dist) - 1]
        os.environ["LANG"] = "C"
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        with open(os.path.join(self.testdir, "sources.list"), "w") as f:
            f.write("""
# main repo
deb http://old-releases.ubuntu.com/ubuntu %s main restricted multiverse universe
deb-src http://old-releases.ubuntu.com/ubuntu %s main restricted multiverse

deb http://old-releases.ubuntu.com/ubuntu %s-security main restricted
""" % (from_dist, from_dist, from_dist))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = from_dist
        d.toDist = to_dist
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)
        if ARCH in ('amd64', 'i386'):
            self._verifySources("""
# main repo
deb http://archive.ubuntu.com/ubuntu %s main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu %s main restricted multiverse

deb http://archive.ubuntu.com/ubuntu %s-security main restricted universe multiverse
""" % (to_dist, to_dist, to_dist))
        else:
            self._verifySources("""
# main repo
deb http://ports.ubuntu.com/ubuntu-ports/ %s main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu %s main restricted multiverse

deb http://ports.ubuntu.com/ubuntu-ports/ %s-security main restricted universe multiverse
""" % (to_dist, to_dist, to_dist))

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_private_ppa_transition(self, mock_sourcesListEntryDownloadable):
        if "RELEASE_UPGRADER_ALLOW_THIRD_PARTY" in os.environ:
            del os.environ["RELEASE_UPGRADER_ALLOW_THIRD_PARTY"]
        shutil.copy(
            os.path.join(self.testdir,
                         "sources.list.commercial-ppa-uploaders"),
            os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        if ARCH in ('amd64', 'i386'):
            self._verifySources("""
deb http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse

deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted universe multiverse

# random one
# deb http://user:pass@private-ppa.launchpad.net/random-ppa gutsy main # disabled on upgrade to gutsy

# commercial PPA
deb https://user:pass@private-ppa.launchpad.net/commercial-ppa-uploaders gutsy main
""")
        else:
            self._verifySources("""
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse

deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-security main restricted universe multiverse

# random one
# deb http://user:pass@private-ppa.launchpad.net/random-ppa gutsy main # disabled on upgrade to gutsy

# commercial PPA
deb https://user:pass@private-ppa.launchpad.net/commercial-ppa-uploaders gutsy main
""")

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "test is not arch specific")
    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_apt_cacher_and_apt_bittorent(self, mock_sourcesListEntryDownloadable):
        """
        test transition of apt-cacher/apt-torrent uris
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.apt-cacher"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourceparts",
                           os.path.join(self.testdir, "sources.list.d"))
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # now test the result
        self._verifySources("""
deb http://localhost:9977/security.ubuntu.com/ubuntu gutsy-security main restricted universe multiverse
deb http://localhost:9977/us.archive.ubuntu.com/ubuntu/ gutsy main
deb http://localhost:9977/archive.ubuntu.com/ubuntu/ gutsy main

deb http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse universe
deb-src http://archive.ubuntu.com/ubuntu gutsy main restricted multiverse

deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted
deb http://security.ubuntu.com/ubuntu/ gutsy-security universe
""")

    def test_unicode_comments(self):
        """
        test a sources.list file with unicode comments
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.unicode"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        self._verifySources("""
deb http://archive.ubuntu.com/ubuntu gutsy main restricted
deb http://archive.ubuntu.com/ubuntu gutsy-updates main restricted
deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted
# A PPA with a unicode comment
deb http://ppa.launchpad.net/random-ppa quantal main # ppa of Víctor R. Ruiz (vrruiz)
""")

        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        res = d.updateSourcesList()
        self.assertTrue(res)

        # verify it
        self._verifySourcesLine("""
# deb http://ppa.launchpad.net/random-ppa quantal main # ppa of Víctor R. Ruiz (vrruiz) disabled on upgrade to gutsy
""")

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_local_mirror(self, mock_sourcesListEntryDownloadable):
        """
        test that a local mirror with official -backports works (LP: #1067393)
        """
        shutil.copy(os.path.join(self.testdir, "sources.list.local"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        # verify it
        if ARCH in ('amd64', 'i386'):
            self._verifySources("""
deb http://192.168.1.1/ubuntu gutsy main restricted
deb http://192.168.1.1/ubuntu gutsy-updates main restricted
deb http://security.ubuntu.com/ubuntu/ gutsy-security main restricted
deb http://archive.ubuntu.com/ubuntu gutsy-backports main restricted universe multiverse
""")
        else:
            self._verifySources("""
deb http://192.168.1.1/ubuntu gutsy main restricted
deb http://192.168.1.1/ubuntu gutsy-updates main restricted
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-security main restricted
deb http://ports.ubuntu.com/ubuntu-ports/ gutsy-backports main restricted universe multiverse
""")

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._sourcesListEntryDownloadable")
    def test_disable_proposed(self, mock_sourcesListEntryDownloadable):
        """
        Test that proposed is disabled when upgrading to a development
        release.
        """
        shutil.copy(os.path.join(self.testdir,
                    "sources.list.proposed_enabled"),
                    os.path.join(self.testdir, "sources.list"))
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        v = DistUpgradeViewNonInteractive()
        options = mock.Mock()
        options.devel_release = True
        d = DistUpgradeController(v, options, datadir=self.testdir)
        d.openCache(lock=False)
        mock_sourcesListEntryDownloadable.return_value = True
        res = d.updateSourcesList()
        self.assertTrue(mock_sourcesListEntryDownloadable.called)
        self.assertTrue(res)

        self._verifySourcesLine("""
# deb http://archive.ubuntu.com/ubuntu gutsy-proposed universe main multiverse restricted #Not for humans during development stage of release gutsy
""")

    def _verifySources(self, expected):
        sources_file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        with open(sources_file) as f:
            sources_list = f.read()
        for l in expected.split("\n"):
            self.assertTrue(
                l in sources_list.split("\n"),
                "expected entry '%s' in sources.list missing. got:\n'''%s'''" %
                (l, sources_list))

    def _verifySourcesLine(self, expected):
        sources_file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        with open(sources_file) as f:
            sources_list = f.read()
            self.assertTrue(
                expected in sources_list,
                "expected entry '%s' in sources.list missing. got:\n'''%s'''" %
                 (expected.strip("\n"), sources_list))

    def _verifySources2Way(self, expected):
        self._verifySources(expected)
        sources_file = apt_pkg.config.find_file("Dir::Etc::sourcelist")
        with open(sources_file) as f:
            sources_list = f.read()
        for l in sources_list.split("\n"):
            self.assertTrue(
                l in expected.split("\n"),
                "unexpected entry '%s' in sources.list. got:\n'''%s'''" %
                (l, sources_list))

class TestDeb822SourcesUpdate(unittest.TestCase):

    testdir = os.path.abspath(os.path.join(CURDIR, "data-deb822-sources-test"))
    sourceparts_dir = os.path.join(testdir, "sources.list.d")

    def setUp(self):
        apt_pkg.config.set("Dir::Etc", self.testdir)
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        apt_pkg.config.set("Dir::Etc::sourceparts", self.sourceparts_dir)
        apt_pkg.config.set("APT::Default-Release", "")

    def tearDown(self):
        shutil.rmtree(self.sourceparts_dir, ignore_errors=True)

    def test_ubuntu_sources_with_nothing(self):
        """
        test ubuntu.sources rewrite with nothing in it
        """
        self.prepareTestSources()

        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        res = d.updateDeb822Sources()
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            dist=d.toDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_sources_rewrite(self, mock_deb822SourceEntryDownloadable):
        """
        test regular ubuntu.sources rewrite
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.useNetwork = False
        self.prepareTestSources(
            dist=d.fromDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        d.openCache(lock=False)
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            dist=d.toDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    @unittest.skipUnless(ARCH in ('amd64', 'i386'), "ports are not mirrored")
    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_sources_inactive_mirror(self,
                                     mock_deb822SourceEntryDownloadable):
        """
        test ubuntu.sources rewrite of an obsolete mirror
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.config.set("Distro", "BaseMetaPkgs", "ubuntu-minimal")
        d.openCache(lock=False)
        self.prepareTestSources(dist=d.fromDist)
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            from_dist=d.fromDist,
            to_dist=d.toDist,
            default_source_uri=d.default_source_uri
        )

    def testEOL2SupportedUpgrade(self):
        " test upgrade from a EOL release to a supported release "
        to_dist = LTSES[-2]
        from_dist = di.all[di.all.index(to_dist) - 1]
        os.environ["LANG"] = "C"
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.fromDist = from_dist
        d.toDist = to_dist
        d.openCache(lock=False)
        self.prepareTestSources(dist=from_dist)
        res = d.updateDeb822Sources()
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            dist=to_dist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_private_ppa_transition(self, mock_deb822SourceEntryDownloadable):
        if "RELEASE_UPGRADER_ALLOW_THIRD_PARTY" in os.environ:
            del os.environ["RELEASE_UPGRADER_ALLOW_THIRD_PARTY"]

        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        self.prepareTestSources(
            dist=d.fromDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            to_dist=d.toDist,
            from_dist=d.fromDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_apt_cacher_and_apt_bittorent(self,
                                          mock_deb822SourceEntryDownloadable):
        """
        test transition of apt-cacher/apt-torrent uris
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        self.prepareTestSources(dist=d.fromDist)
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(dist=d.toDist)

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_local_mirror(self, mock_deb822SourceEntryDownloadable):
        """
        test that a local mirror with official -backports works (LP: #1067393)
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)
        self.prepareTestSources(
            dist=d.fromDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            dist=d.toDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    @mock.patch("DistUpgrade.DistUpgradeController.DistUpgradeController._deb822SourceEntryDownloadable")
    def test_disable_proposed(self, mock_deb822SourceEntryDownloadable):
        """
        Test that proposed is disabled when upgrading to a development
        release.
        """
        v = DistUpgradeViewNonInteractive()
        options = mock.Mock()
        options.devel_release = True
        d = DistUpgradeController(v, options, datadir=self.testdir)
        d.openCache(lock=False)
        self.prepareTestSources(
            dist=d.fromDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        mock_deb822SourceEntryDownloadable.return_value = (True, [])
        res = d.updateDeb822Sources()
        self.assertTrue(mock_deb822SourceEntryDownloadable.called)
        self.assertTrue(res)
        self.assertSourcesMatchExpected(
            from_dist=d.fromDist,
            to_dist=d.toDist,
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    def assertSourcesMatchExpected(self, **kwargs):
        # Compare the output to the expected data corresponding to the calling
        # test function.
        testdata = os.path.join(self.testdir, inspect.stack()[1][3], "expect")

        for expect_path in os.listdir(testdata):
            actual_path = os.path.join(self.sourceparts_dir, expect_path)
            expect_path = os.path.join(testdata, expect_path)
            with open(expect_path) as e, open(actual_path) as a:
                expect = e.read().format(**kwargs)
                actual = a.read()
                self.assertEqual(expect, actual,
                                 '\n# Actual {}:\n{}'
                                 .format(os.path.basename(actual_path), actual))

    def prepareTestSources(self, **kwargs):
        # Copy the test data from the directory corresponding to the calling
        # test function.
        testdata = os.path.join(self.testdir, inspect.stack()[1][3], "in")

        shutil.rmtree(self.sourceparts_dir, ignore_errors=True)
        os.mkdir(self.sourceparts_dir)

        for file in os.listdir(testdata):
            path_in = os.path.join(testdata, file)
            path_out = os.path.join(self.sourceparts_dir, file)

            with open(path_in) as fin, open(path_out, 'w') as fout:
                fout.write(fin.read().format(**kwargs))


class TestDeb822SourcesMigration(unittest.TestCase):

    testdir = os.path.abspath(os.path.join(CURDIR, "data-deb822-migration-test"))
    sourceparts_dir = os.path.join(testdir, "sources.list.d")
    trustedparts_dir = os.path.join(testdir, "trusted.gpg.d")

    def setUp(self):
        apt_pkg.config.set("Dir::Etc", self.testdir)
        apt_pkg.config.set("Dir::Etc::sourcelist", "sources.list")
        apt_pkg.config.set("Dir::Etc::sourceparts", self.sourceparts_dir)
        apt_pkg.config.set("Dir::Etc::trustedparts", self.trustedparts_dir)
        apt_pkg.config.set("APT::Default-Release", "")
        self.maxDiff = None

    def tearDown(self):
        shutil.rmtree(self.sourceparts_dir, ignore_errors=True)
        shutil.rmtree(self.trustedparts_dir, ignore_errors=True)
        for file in glob.glob("{}/sources.list*".format(self.testdir)):
            os.remove(file)

    def assertSourcesMatchExpected(self, **kwargs):
        # Compare the output to the expected data corresponding to the calling
        # test function.
        testdata = os.path.join(self.testdir, inspect.stack()[1][3], "expect")

        for expect_path in os.listdir(testdata):
            if expect_path.endswith(".gpg"):
                actual_path = os.path.join(self.trustedparts_dir, expect_path)
            else:
                actual_path = os.path.join(self.sourceparts_dir, expect_path)

            expect_path = os.path.join(testdata, expect_path)

            self.assertTrue(
                os.path.exists(actual_path),
                "File {} was not created during deb822 migration"
                .format(actual_path)
            )

            with open(expect_path) as e, open(actual_path) as a:
                expect = e.read().format(**kwargs)
                actual = a.read()
                self.assertEqual(expect, actual)
                                 #'\n# Actual {}:\n{}'
                                 #.format(os.path.basename(actual_path), actual))

    def prepareTestSources(self, **kwargs):
        # Copy the test data from the directory corresponding to the calling
        # test function.
        testdata = os.path.join(self.testdir, inspect.stack()[1][3], "in")

        shutil.rmtree(self.sourceparts_dir, ignore_errors=True)
        os.mkdir(self.sourceparts_dir)
        shutil.rmtree(self.trustedparts_dir, ignore_errors=True)
        os.mkdir(self.trustedparts_dir)

        for file in os.listdir(testdata):
            path_in = os.path.join(testdata, file)
            in_mode = 'r'
            out_mode = 'w'

            if file == "sources.list":
                path_out = os.path.join(self.testdir, file)
            elif file.endswith(".gpg"):
                path_out = os.path.join(self.trustedparts_dir, file)
                in_mode += 'b'
                out_mode += 'b'
            else:
                path_out = os.path.join(self.sourceparts_dir, file)

            with open(path_in, in_mode) as fin, open(path_out, out_mode) as fout:
                data = fin.read()
                if isinstance(data, str):
                    data = data.format(**kwargs)

                fout.write(data)

    def test_sources_list_migration(self):
        """
        test that the usual sources.list is migrated to an appropriate
        ubuntu.sources
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

        # Make sure we leave behind a comment in sources.list
        with open(os.path.join(self.testdir, "sources.list")) as f:
            self.assertEqual(
                f.read(),
                "# Ubuntu sources have moved to {}/ubuntu.sources\n"
                .format(self.sourceparts_dir)
            )

    def test_third_party_sources_migration(self):
        """
        test that third party sources from sources.list are moved to
        third-party.sources.
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )

    def test_partial_migration(self):
        """
        test that only .list sources are modified during migration
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )

    def test_ppa_migration(self):
        """
        test that PPA sources.list.d .list files are migrated
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources()
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected()

    def test_consolidate_types(self):
        """
        test that deb and deb-src entries are consolidated when appropriate
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
            security_source_uri=d.security_source_uri,
        )

    def test_consolidate_suites(self):
        """
        test that suites are consolidated when appropriate
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )

    def test_consolidate_comps(self):
        """
        test that components are consolidated when appropriate
        """
        v = DistUpgradeViewNonInteractive()
        d = DistUpgradeController(v, datadir=self.testdir)
        d.openCache(lock=False)

        self.prepareTestSources(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )
        self.assertFalse(d.migratedToDeb822())

        d.migrateToDeb822Sources()

        self.assertTrue(d.migratedToDeb822())
        self.assertSourcesMatchExpected(
            dist=di.devel(),
            default_source_uri=d.default_source_uri,
        )


if __name__ == "__main__":
    import sys
    for e in sys.argv:
        if e == "-v":
            logging.basicConfig(level=logging.DEBUG)
    unittest.main()
