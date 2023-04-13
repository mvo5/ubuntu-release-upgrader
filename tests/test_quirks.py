#!/usr/bin/python3
# -*- Mode: Python; indent-tabs-mode: nil; tab-width: 4; coding: utf-8 -*-

import apt
import apt_pkg
import hashlib
import mock
import os
import unittest
import shutil
import tempfile
import json

from DistUpgrade.DistUpgradeQuirks import DistUpgradeQuirks

CURDIR = os.path.dirname(os.path.abspath(__file__))


class MockController(object):
    def __init__(self):
        self._view = None


class MockConfig(object):
    pass


class MockPopenSnap():
    def __init__(self, cmd, universal_newlines=True,
                 stdout=None):
        self.command = cmd

    def communicate(self):
        if self.command[1] == "list":
            return []
        snap_name = self.command[2]
        if snap_name == 'gnome-logs':
            # Package to refresh
            return ["""
name:      test-snap
summary:   Test Snap
publisher: Canonical
license:   unset
description: Some description
commands:
  - gnome-calculator
snap-id:      1234
tracking:     stable/ubuntu-19.04
refresh-date: 2019-04-11
channels:
  stable:    3.32.1  2019-04-10 (406) 4MB -
  candidate: 3.32.2  2019-06-26 (433) 4MB -
  beta:      3.33.89 2019-08-06 (459) 4MB -
  edge:      3.33.90 2019-08-06 (460) 4MB -
installed:   3.32.1             (406) 4MB -
"""]
        elif "gnome-characters" in snap_name:
            # Package installed but not tracking the release channel
            return ["""
name:      test-snap
summary:   Test Snap
publisher: Canonical
license:   unset
description: Some description
commands:
  - gnome-characters
snap-id:      1234
refresh-date: 2019-04-11
channels:
  stable:    3.32.1  2019-04-10 (406) 4MB -
  candidate: 3.32.2  2019-06-26 (433) 4MB -
  beta:      3.33.89 2019-08-06 (459) 4MB -
  edge:      3.33.90 2019-08-06 (460) 4MB -
installed:   3.32.1             (406) 4MB -
"""]
        elif "gtk-common-themes" in snap_name:
            # Package installed but missing/invalid snap id
            return ["""
name:      test-snap
summary:   Test Snap
publisher: Canonical
license:   unset
description: Some description
commands:
  - gtk-common-themes
refresh-date: 2019-04-11
channels:
  stable:    3.32.1  2019-04-10 (406) 4MB -
  candidate: 3.32.2  2019-06-26 (433) 4MB -
  beta:      3.33.89 2019-08-06 (459) 4MB -
  edge:      3.33.90 2019-08-06 (460) 4MB -
"""]
        else:
            return ["""
name:      test-snap
summary:   Test Snap
publisher: Canonical
license:   unset
description: Some description
commands:
  - gnome-calculator
snap-id:      1234
refresh-date: 2019-04-11
channels:
  stable:    3.32.1  2019-04-10 (406) 4MB -
  candidate: 3.32.2  2019-06-26 (433) 4MB -
  beta:      3.33.89 2019-08-06 (459) 4MB -
  edge:      3.33.90 2019-08-06 (460) 4MB -
"""]


def mock_urlopen_snap(req):
    result = """{{
  "error-list": [],
  "results": [
    {{
      "effective-channel": "stable",
      "instance-key": "test",
      "name": "{name}",
      "released-at": "2019-04-10T18:54:15.717357+00:00",
      "result": "download",
      "snap": {{
        "created-at": "2019-04-09T17:09:29.941588+00:00",
        "download": {{
          "deltas": [],
          "size": {size},
          "url": "SNAPURL"
        }},
        "license": "GPL-3.0+",
        "name": "{name}",
        "prices": {{ }},
        "publisher": {{
          "display-name": "Canonical",
          "id": "canonical",
          "username": "canonical",
          "validation": "verified"
        }},
        "revision": 406,
        "snap-id": "{snap_id}",
        "summary": "GNOME Calculator",
        "title": "GNOME Calculator",
        "type": "app",
        "version": "3.32.1"
      }},
      "snap-id": "{snap_id}"
    }}
  ]
}}
"""
    test_snaps = {
        '1': ("gnome-calculator", 4218880),
        '2': ("test-snap", 2000000)
    }
    json_data = json.loads(req.data)
    snap_id = json_data['actions'][0]['snap-id']
    name = test_snaps[snap_id][0]
    size = test_snaps[snap_id][1]
    response_mock = mock.Mock()
    response_mock.read.return_value = result.format(
        name=name, snap_id=snap_id, size=size)
    return response_mock


def make_mock_pkg(name, is_installed, candidate_rec=""):
    mock_pkg = mock.Mock()
    mock_pkg.name = name
    mock_pkg.is_installed = is_installed
    mock_pkg.marked_install = False
    if candidate_rec:
        mock_pkg.candidate = mock.Mock()
        mock_pkg.candidate.record = candidate_rec
    return mock_pkg


class TestPatches(unittest.TestCase):

    orig_chdir = ''

    def setUp(self):
        # To patch, we need to be in the same directory as the patched files
        self.orig_chdir = os.getcwd()
        os.chdir(CURDIR)

    def tearDown(self):
        os.chdir(self.orig_chdir)

    def _verify_result_checksums(self):
        """ helper for test_patch to verify that we get the expected result """
        # simple case is foo
        patchdir = CURDIR + "/patchdir/"
        with open(patchdir + "foo") as f:
            self.assertFalse("Hello" in f.read())
        with open(patchdir + "foo_orig") as f:
            self.assertTrue("Hello" in f.read())
        md5 = hashlib.md5()
        with open(patchdir + "foo", "rb") as patch:
            md5.update(patch.read())
        self.assertEqual(md5.hexdigest(), "52f83ff6877e42f613bcd2444c22528c")
        # more complex example fstab
        md5 = hashlib.md5()
        with open(patchdir + "fstab", "rb") as patch:
            md5.update(patch.read())
        self.assertEqual(md5.hexdigest(), "c56d2d038afb651920c83106ec8dfd09")
        # most complex example
        md5 = hashlib.md5()
        with open(patchdir + "pycompile", "rb") as patch:
            md5.update(patch.read())
        self.assertEqual(md5.hexdigest(), "97c07a02e5951cf68cb3f86534f6f917")
        # with ".\n"
        md5 = hashlib.md5()
        with open(patchdir + "dotdot", "rb") as patch:
            md5.update(patch.read())
        self.assertEqual(md5.hexdigest(), "cddc4be46bedd91db15ddb9f7ddfa804")
        # test that incorrect md5sum after patching rejects the patch
        with open(patchdir + "fail") as f1, open(patchdir + "fail_orig") as f2:
            self.assertEqual(f1.read(),
                             f2.read())

    def test_patch(self):
        q = DistUpgradeQuirks(MockController(), MockConfig)
        # create patch environment
        patchdir = CURDIR + "/patchdir/"
        shutil.copy(patchdir + "foo_orig", patchdir + "foo")
        shutil.copy(patchdir + "fstab_orig", patchdir + "fstab")
        shutil.copy(patchdir + "pycompile_orig", patchdir + "pycompile")
        shutil.copy(patchdir + "dotdot_orig", patchdir + "dotdot")
        shutil.copy(patchdir + "fail_orig", patchdir + "fail")
        # apply patches
        q._applyPatches(patchdir=patchdir)
        self._verify_result_checksums()
        # now apply patches again and ensure we don't patch twice
        q._applyPatches(patchdir=patchdir)
        self._verify_result_checksums()

    def test_patch_lowlevel(self):
        # test lowlevel too
        from DistUpgrade.DistUpgradePatcher import patch, PatchError
        self.assertRaises(PatchError, patch, CURDIR + "/patchdir/fail",
                          CURDIR + "/patchdir/patchdir_fail."
                          "ed04abbc6ee688ee7908c9dbb4b9e0a2."
                          "deadbeefdeadbeefdeadbeff",
                          "deadbeefdeadbeefdeadbeff")


class TestQuirks(unittest.TestCase):

    orig_recommends = ''
    orig_status = ''

    def setUp(self):
        self.orig_recommends = apt_pkg.config.get("APT::Install-Recommends")
        self.orig_status = apt_pkg.config.get("Dir::state::status")

    def tearDown(self):
        apt_pkg.config.set("APT::Install-Recommends", self.orig_recommends)
        apt_pkg.config.set("Dir::state::status", self.orig_status)

    def test_enable_recommends_during_upgrade(self):
        controller = mock.Mock()

        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        # server mode
        apt_pkg.config.set("APT::Install-Recommends", "0")
        controller.serverMode = True
        self.assertFalse(apt_pkg.config.find_b("APT::Install-Recommends"))
        q.ensure_recommends_are_installed_on_desktops()
        self.assertFalse(apt_pkg.config.find_b("APT::Install-Recommends"))
        # desktop mode
        apt_pkg.config.set("APT::Install-Recommends", "0")
        controller.serverMode = False
        self.assertFalse(apt_pkg.config.find_b("APT::Install-Recommends"))
        q.ensure_recommends_are_installed_on_desktops()
        self.assertTrue(apt_pkg.config.find_b("APT::Install-Recommends"))

    def test_parse_from_modaliases_header(self):
        pkgrec = {
            "Package": "foo",
            "Modaliases": "modules1(pci:v00001002d00006700sv*sd*bc03sc*i*, "
                          "pci:v00001002d00006701sv*sd*bc03sc*i*), "
                          "module2(pci:v00001002d00006702sv*sd*bc03sc*i*, "
                          "pci:v00001001d00006702sv*sd*bc03sc*i*)"
        }
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        self.assertEqual(q._parse_modaliases_from_pkg_header({}), [])
        self.assertEqual(q._parse_modaliases_from_pkg_header(pkgrec),
                         [("modules1",
                           ["pci:v00001002d00006700sv*sd*bc03sc*i*",
                            "pci:v00001002d00006701sv*sd*bc03sc*i*"]),
                          ("module2",
                           ["pci:v00001002d00006702sv*sd*bc03sc*i*",
                            "pci:v00001001d00006702sv*sd*bc03sc*i*"])])

    def disabled__as_fglrx_is_gone_testFglrx(self):
        mock_lspci_good = set(['1002:9990'])
        mock_lspci_bad = set(['8086:ac56'])
        config = mock.Mock()
        cache = apt.Cache()
        controller = mock.Mock()
        controller.cache = cache
        q = DistUpgradeQuirks(controller, config)
        if q.arch not in ['i386', 'amd64']:
            return self.skipTest("Not on an arch with fglrx package")
        self.assertTrue(q._supportInModaliases("fglrx", mock_lspci_good))
        self.assertFalse(q._supportInModaliases("fglrx", mock_lspci_bad))

    def test_screensaver_poke(self):
        # fake nothing is installed
        empty_status = tempfile.NamedTemporaryFile()
        apt_pkg.config.set("Dir::state::status", empty_status.name)

        # create quirks class
        controller = mock.Mock()
        config = mock.Mock()
        quirks = DistUpgradeQuirks(controller, config)
        quirks._pokeScreensaver()
        res = quirks._stopPokeScreensaver()
        res  # pyflakes

    def test_get_linux_metapackage(self):
        q = DistUpgradeQuirks(mock.Mock(), mock.Mock())
        mock_cache = set([
            make_mock_pkg(
                name="linux-image-3.19-24-generic",
                is_installed=True,
                candidate_rec={"Source": "linux"},
            ),
        ])
        pkgname = q._get_linux_metapackage(mock_cache, headers=False)
        self.assertEqual(pkgname, "linux-generic")

    def test_get_lpae_linux_metapackage(self):
        q = DistUpgradeQuirks(mock.Mock(), mock.Mock())
        mock_cache = set([
            make_mock_pkg(
                name="linux-image-4.2.0-16-generic-lpae",
                is_installed=True,
                candidate_rec={"Source": "linux"},
            ),
        ])
        pkgname = q._get_linux_metapackage(mock_cache, headers=False)
        self.assertEqual(pkgname, "linux-generic-lpae")

    def test_get_lowlatency_linux_metapackage(self):
        q = DistUpgradeQuirks(mock.Mock(), mock.Mock())
        mock_cache = set([
            make_mock_pkg(
                name="linux-image-4.2.0-16-lowlatency",
                is_installed=True,
                candidate_rec={"Source": "linux"},
            ),
        ])
        pkgname = q._get_linux_metapackage(mock_cache, headers=False)
        self.assertEqual(pkgname, "linux-lowlatency")

    def test_get_lts_linux_metapackage(self):
        q = DistUpgradeQuirks(mock.Mock(), mock.Mock())
        mock_cache = set([
            make_mock_pkg(
                name="linux-image-3.13.0-24-generic",
                is_installed=True,
                candidate_rec={"Source": "linux-lts-quantal"},
            ),
        ])
        pkgname = q._get_linux_metapackage(mock_cache, headers=False)
        self.assertEqual(pkgname, "linux-generic-lts-quantal")

    def test_ros_installed_warning(self):
        ros_packages = (
            "ros-melodic-catkin",
            "ros-noetic-rosboost-cfg",
            "ros-foxy-rosclean",
            "ros-kinetic-ros-environment",
            "ros-dashing-ros-workspace")
        for package_name in ros_packages:
            mock_controller = mock.Mock()
            mock_question = mock_controller._view.askYesNoQuestion
            mock_question.return_value = True

            q = DistUpgradeQuirks(mock_controller, mock.Mock())
            mock_cache = set([
                make_mock_pkg(
                    name=package_name,
                    is_installed=True,
                ),
            ])
            q._test_and_warn_if_ros_installed(mock_cache)
            mock_question.assert_called_once_with(mock.ANY, mock.ANY)
            self.assertFalse(len(mock_controller.abort.mock_calls))

            mock_controller.reset_mock()
            mock_question.reset_mock()
            mock_question.return_value = False

            mock_cache = set([
                make_mock_pkg(
                    name=package_name,
                    is_installed=True,
                ),
            ])
            q._test_and_warn_if_ros_installed(mock_cache)
            mock_question.assert_called_once_with(mock.ANY, mock.ANY)
            mock_controller.abort.assert_called_once_with()

    def test_ros_not_installed_no_warning(self):
        mock_controller = mock.Mock()
        mock_question = mock_controller._view.askYesNoQuestion
        mock_question.return_value = False

        q = DistUpgradeQuirks(mock_controller, mock.Mock())
        mock_cache = set([
            make_mock_pkg(
                name="ros-melodic-catkin",
                is_installed=False,
            ),
            make_mock_pkg(
                name="ros-noetic-rosboost-cfg",
                is_installed=False,
            ),
            make_mock_pkg(
                name="ros-foxy-rosclean",
                is_installed=False,
            ),
            make_mock_pkg(
                name="ros-kinetic-ros-environment",
                is_installed=False,
            ),
            make_mock_pkg(
                name="ros-dashing-ros-workspace",
                is_installed=False,
            ),
        ])
        q._test_and_warn_if_ros_installed(mock_cache)
        self.assertFalse(len(mock_question.mock_calls))
        self.assertFalse(len(mock_controller.abort.mock_calls))

    @mock.patch('os.path.exists')
    def test_aufs_fail(self, mock_exists):
        mock_exists.return_value = True
        mock_controller = mock.Mock()

        q = DistUpgradeQuirks(mock_controller, mock.Mock())

        q._test_and_fail_on_aufs()
        self.assertTrue(len(mock_controller.abort.mock_calls))

    def test_replace_fkms_overlay_no_config(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            mock_controller = mock.Mock()

            q = DistUpgradeQuirks(mock_controller, mock.Mock())

            q._replace_fkms_overlay(boot_dir)
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))

    def test_replace_fkms_overlay_no_changes(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            demo_config = """\
# This is a demo boot config
[pi4]
max_framebuffers=2
[all]
arm_64bit=1
kernel=vmlinuz
initramfs initrd.img followkernel"""
            with open(os.path.join(boot_dir, 'config.txt'), 'w') as f:
                f.write(demo_config)

            mock_controller = mock.Mock()

            q = DistUpgradeQuirks(mock_controller, mock.Mock())

            q._replace_fkms_overlay(boot_dir)
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))
            with open(os.path.join(boot_dir, 'config.txt')) as f:
                self.assertTrue(f.read() == demo_config)

    def test_replace_fkms_overlay_with_changes(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            demo_config = """\
# This is a demo boot config
[pi4]
max_framebuffers=2
[all]
arm_64bit=1
kernel=vmlinuz
initramfs initrd.img followkernel
dtoverlay=vc4-fkms-v3d,cma-256
start_x=1
gpu_mem=256
"""
            expected_config = """\
# This is a demo boot config
[pi4]
max_framebuffers=2
[all]
arm_64bit=1
kernel=vmlinuz
initramfs initrd.img followkernel
# changed by do-release-upgrade (LP: #1923673)
#dtoverlay=vc4-fkms-v3d,cma-256
dtoverlay=vc4-kms-v3d,cma-256
# disabled by do-release-upgrade (LP: #1923673)
#start_x=1
# disabled by do-release-upgrade (LP: #1923673)
#gpu_mem=256
"""
            with open(os.path.join(boot_dir, 'config.txt'), 'w') as f:
                f.write(demo_config)

            mock_controller = mock.Mock()

            q = DistUpgradeQuirks(mock_controller, mock.Mock())

            q._replace_fkms_overlay(boot_dir)
            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))
            with open(os.path.join(boot_dir, 'config.txt')) as f:
                self.assertTrue(f.read() == expected_config)

    def test_remove_uboot_no_config(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            mock_controller = mock.Mock()
            q = DistUpgradeQuirks(mock_controller, mock.Mock())
            q._remove_uboot_on_rpi(boot_dir)

            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))

    def test_remove_uboot_no_changes(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            native_config = """\
# This is a demo boot config with a comment at the start that should not
# be removed

[pi4]
max_framebuffers=2

[all]
arm_64bit=1
kernel=vmlinuz
initramfs initrd.img followkernel

# This is a user-added include that should not be merged
include custom.txt
"""
            custom_config = """\
# This is the custom included configuration file

hdmi_group=1
hdmi_mode=4
"""
            with open(os.path.join(boot_dir, 'config.txt'), 'w') as f:
                f.write(native_config)
            with open(os.path.join(boot_dir, 'custom.txt'), 'w') as f:
                f.write(custom_config)

            mock_controller = mock.Mock()
            q = DistUpgradeQuirks(mock_controller, mock.Mock())
            q._remove_uboot_on_rpi(boot_dir)

            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'custom.txt.distUpgrade')))
            with open(os.path.join(boot_dir, 'config.txt')) as f:
                self.assertTrue(f.read() == native_config)
            with open(os.path.join(boot_dir, 'custom.txt')) as f:
                self.assertTrue(f.read() == custom_config)

    def test_remove_uboot_with_changes(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            config_txt = """\
# This is a warning that you should not edit this file. The upgrade should
# remove this comment

[pi4]
# This is a comment that should be included
kernel=uboot_rpi_4.bin
max_framebuffers=2

[pi2]
kernel=uboot_rpi_2.bin

[pi3]
kernel=uboot_rpi_3.bin

[all]
arm_64bit=1
device_tree_address=0x3000000
include syscfg.txt
include usercfg.txt
dtoverlay=vc4-fkms-v3d,cma-256
include custom.txt
"""
            usercfg_txt = """\
# Another chunk of warning text that should be skipped
"""
            syscfg_txt = """\
# Yet more warnings to exclude
dtparam=audio=on
dtparam=spi=on
enable_uart=1
"""
            custom_txt = """\
# This is a user-added file that should be left alone by the upgrade
[gpio4=1]
kernel=custom
"""
            expected_config_txt = """\

[pi4]
# This is a comment that should be included
# commented by do-release-upgrade (LP: #1936401)
#kernel=uboot_rpi_4.bin
max_framebuffers=2

[pi2]
# commented by do-release-upgrade (LP: #1936401)
#kernel=uboot_rpi_2.bin

[pi3]
# commented by do-release-upgrade (LP: #1936401)
#kernel=uboot_rpi_3.bin

[all]
# added by do-release-upgrade (LP: #1936401)
kernel=vmlinuz
initramfs initrd.img followkernel
arm_64bit=1
# commented by do-release-upgrade (LP: #1936401)
#device_tree_address=0x3000000
# merged from syscfg.txt by do-release-upgrade (LP: #1936401)
dtparam=audio=on
dtparam=spi=on
enable_uart=1
# merged from usercfg.txt by do-release-upgrade (LP: #1936401)
dtoverlay=vc4-fkms-v3d,cma-256
include custom.txt
"""
            with open(os.path.join(boot_dir, 'config.txt'), 'w') as f:
                f.write(config_txt)
            with open(os.path.join(boot_dir, 'syscfg.txt'), 'w') as f:
                f.write(syscfg_txt)
            with open(os.path.join(boot_dir, 'usercfg.txt'), 'w') as f:
                f.write(usercfg_txt)
            with open(os.path.join(boot_dir, 'custom.txt'), 'w') as f:
                f.write(custom_txt)

            mock_controller = mock.Mock()
            q = DistUpgradeQuirks(mock_controller, mock.Mock())
            q._remove_uboot_on_rpi(boot_dir)

            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))
            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'syscfg.txt.distUpgrade')))
            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'usercfg.txt.distUpgrade')))
            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'config.txt')))
            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'custom.txt')))
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'syscfg.txt')))
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'usercfg.txt')))
            self.assertFalse(os.path.exists(os.path.join(
                boot_dir, 'custom.txt.distUpgrade')))
            with open(os.path.join(boot_dir, 'config.txt')) as f:
                self.assertTrue(f.read() == expected_config_txt)
            with open(os.path.join(boot_dir, 'custom.txt')) as f:
                self.assertTrue(f.read() == custom_txt)

    def test_remove_uboot_no_all_section(self):
        with tempfile.TemporaryDirectory() as boot_dir:
            config_txt = """\
arm_64bit=1
device_tree_address=0x3000000

[pi4]
# This is a comment that should be included
kernel=uboot_rpi_4.bin
max_framebuffers=2

[pi3]
kernel=uboot_rpi_3.bin
"""
            expected_config_txt = """\
arm_64bit=1
# commented by do-release-upgrade (LP: #1936401)
#device_tree_address=0x3000000

[pi4]
# This is a comment that should be included
# commented by do-release-upgrade (LP: #1936401)
#kernel=uboot_rpi_4.bin
max_framebuffers=2

[pi3]
# commented by do-release-upgrade (LP: #1936401)
#kernel=uboot_rpi_3.bin
# added by do-release-upgrade (LP: #1936401)
[all]
kernel=vmlinuz
initramfs initrd.img followkernel
"""
            with open(os.path.join(boot_dir, 'config.txt'), 'w') as f:
                f.write(config_txt)

            mock_controller = mock.Mock()
            q = DistUpgradeQuirks(mock_controller, mock.Mock())
            q._remove_uboot_on_rpi(boot_dir)

            self.assertTrue(os.path.exists(os.path.join(
                boot_dir, 'config.txt.distUpgrade')))
            with open(os.path.join(boot_dir, 'config.txt')) as f:
                self.assertTrue(f.read() == expected_config_txt)


class TestSnapQuirks(unittest.TestCase):

    def test_get_from_and_to_version(self):
        # Prepare the state for testing
        controller = mock.Mock()
        controller.fromDist = 'disco'
        controller.toDist = 'eoan'
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        # Call method under test
        q._get_from_and_to_version()
        self.assertEqual(q._from_version, '19.04')
        self.assertEqual(q._to_version, '19.10')

    @mock.patch("subprocess.Popen", MockPopenSnap)
    def test_prepare_snap_replacement_data(self):
        # Prepare the state for testing
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        q._from_version = "20.04"
        q._to_version = "22.04"
        # Call method under test

        controller.cache = {
            'ubuntu-desktop':
                make_mock_pkg(
                    name="ubuntu-desktop",
                    is_installed=True),
            'core18':
                make_mock_pkg(
                    name="core18",
                    is_installed=True),
            'gnome-3-28-1804':
                make_mock_pkg(
                    name="gnome-3-28-1804",
                    is_installed=True),
            'gtk-common-themes':
                make_mock_pkg(
                    name="gtk-common-themes",
                    is_installed=True),
            'gnome-calculator':
                make_mock_pkg(
                    name="gnome-calculator",
                    is_installed=True),
            'gnome-characters':
                make_mock_pkg(
                    name="gnome-characters",
                    is_installed=False),
            'gnome-logs':
                make_mock_pkg(
                    name="gnome-logs",
                    is_installed=False),
            'gnome-software':
                make_mock_pkg(
                    name="gnome-software",
                    is_installed=True),
            'snap-not-tracked':
                make_mock_pkg(
                    name="snap-not-tracked",
                    is_installed=True),
        }

        q._prepare_snap_replacement_data()
        # Check if the right snaps have been detected as installed and
        # needing refresh and which ones need installation
        self.maxDiff = None
        self.assertDictEqual(
            q._snap_list,
            {'core20': {
                'channel': 'stable',
                'command': 'install',
                'deb': None, 'snap-id': '1234'},
             'gnome-42-2204': {
                'channel': 'stable/ubuntu-22.04',
                'command': 'install',
                'deb': None, 'snap-id': '1234'},
             'snap-store': {
                'channel': 'stable/ubuntu-22.04',
                'command': 'install',
                'deb': 'gnome-software',
                'snap-id': '1234'}})

    def test_is_deb2snap_metapkg_installed(self):
        # Prepare the state for testing
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        q._from_version = "19.04"
        q._to_version = "19.10"
        controller.cache = {
            'ubuntu-desktop':
                make_mock_pkg(
                    name="ubuntu-desktop",
                    is_installed=True)
        }

        testdata = [
            # (input, expected output)
            ({}, False),
            ({'metapkg': None}, False),
            ({'metapkg': 'ubuntu-desktop'}, True),
            ({'metapkg': 'kubuntu-desktop'}, False),
            ({'metapkg': ['kubuntu-desktop', 'ubuntu-desktop']}, True),
            ({'metapkg': ['kubuntu-desktop', 'lubuntu-desktop']}, False),
        ]

        for data in testdata:
            self.assertEqual(q._is_deb2snap_metapkg_installed(data[0]),
                             data[1],
                             'Expected {1} for input {0}'.format(*data))

    @mock.patch("DistUpgrade.DistUpgradeQuirks.get_arch")
    @mock.patch("urllib.request.urlopen")
    def test_calculate_snap_size_requirements(self, urlopen, arch):
        # Prepare the state for testing
        arch.return_value = 'amd64'
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        # We mock out _prepare_snap_replacement_data(), as this is tested
        # separately.
        q._prepare_snap_replacement_data = mock.Mock()
        q._snap_list = {
            'test-snap': {'command': 'install',
                          'deb': None, 'snap-id': '2',
                          'channel': 'stable/ubuntu-19.10'},
            'gnome-calculator': {'command': 'install',
                                 'deb': 'gnome-calculator',
                                 'snap-id': '1',
                                 'channel': 'stable/ubuntu-19.10'},
            'gnome-system-monitor': {'command': 'refresh',
                                     'channel': 'stable/ubuntu-19.10'}
        }
        q._to_version = "19.10"
        # Mock out urlopen in such a way that we get a mocked response based
        # on the parameters given but also allow us to check call arguments
        # etc.
        urlopen.side_effect = mock_urlopen_snap
        # Call method under test
        q._calculateSnapSizeRequirements()
        # Check if the size was calculated correctly
        self.assertEqual(q.extra_snap_space, 6218880)
        # Check if we only sent queries for the two command: install snaps
        self.assertEqual(urlopen.call_count, 2)
        # Make sure each call had the right headers and parameters
        for call in urlopen.call_args_list:
            req = call[0][0]
            self.assertIn(b"stable/ubuntu-19.10", req.data)
            self.assertDictEqual(
                req.headers,
                {'Snap-device-series': '16',
                 'Content-type': 'application/json',
                 'Snap-device-architecture': 'amd64'})

    @mock.patch("subprocess.run")
    def test_replace_debs_and_snaps(self, run_mock):
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)
        q._snap_list = {
            'core18': {'command': 'refresh',
                       'channel': 'stable'},
            'gnome-3-28-1804': {'command': 'refresh',
                                'channel': 'stable/ubuntu-19.10'},
            'gtk-common-themes': {'command': 'refresh',
                                  'channel': 'stable/ubuntu-19.10'},
            'gnome-calculator': {'command': 'remove'},
            'gnome-characters': {'command': 'remove'},
            'gnome-logs': {'command': 'install',
                           'deb': 'gnome-logs',
                           'snap-id': '1234',
                           'channel': 'stable/ubuntu-19.10'},
            'gnome-system-monitor': {'command': 'install',
                                     'deb': 'gnome-system-monitor',
                                     'snap-id': '1234',
                                     'channel': 'stable/ubuntu-19.10'},
            'snap-store': {'command': 'install',
                           'deb': 'gnome-software',
                           'snap-id': '1234',
                           'channel': 'stable/ubuntu-19.10'}
        }
        q._to_version = "19.10"
        q._replaceDebsAndSnaps()
        # Make sure all snaps have been handled
        self.assertEqual(run_mock.call_count, 8)
        snaps_refreshed = {}
        snaps_installed = {}
        snaps_removed = []
        # Check if all the snaps that needed to be installed were installed
        # and those that needed a refresh - refreshed
        # At the same time, let's check that all the snaps were acted upon
        # while using the correct channel and branch
        for call in run_mock.call_args_list:
            args = call[0][0]
            if args[1] == 'refresh':
                snaps_refreshed[args[4]] = args[3]
            elif args[1] == 'install':
                snaps_installed[args[4]] = args[3]
            elif args[1] == 'remove':
                snaps_removed.append(args[2])
        self.assertDictEqual(
            snaps_refreshed,
            {'core18': 'stable',
             'gnome-3-28-1804': 'stable/ubuntu-19.10',
             'gtk-common-themes': 'stable/ubuntu-19.10'})
        self.assertDictEqual(
            snaps_installed,
            {'gnome-logs': 'stable/ubuntu-19.10',
             'gnome-system-monitor': 'stable/ubuntu-19.10',
             'snap-store': 'stable/ubuntu-19.10'})
        self.assertListEqual(
            snaps_removed,
            ['gnome-calculator',
             'gnome-characters'])
        # Make sure we marked the replaced ones for removal
        # Here we only check if the right number of 'packages' has been
        # added to the forced_obsoletes list - not all of those packages are
        # actual deb packages that will have to be removed during the upgrade
        self.assertEqual(controller.forced_obsoletes.append.call_count, 3)

    @mock.patch("builtins.open", new_callable=mock.mock_open,
                read_data="""\
processor       : 0
cpu             : POWER8 (raw), altivec supported
clock           : 3491.000000MHz
revision        : 2.0 (pvr 004d 0200)

processor       : 1
cpu             : POWER8 (raw), altivec supported
clock           : 3491.000000MHz
revision        : 2.0 (pvr 004d 0200)

timebase        : 512000000
platform        : PowerNV
model           : 8001-22C
machine         : PowerNV 8001-22C
firmware        : OPAL
MMU             : Hash
""")
    @mock.patch("DistUpgrade.DistUpgradeQuirks.get_arch",
                return_value="ppc64el")
    def test_power8_fail(self, arch, mock_file):
        controller = mock.Mock()
        config = mock.Mock()
        q = DistUpgradeQuirks(controller, config)

        q._test_and_fail_on_power8()
        self.assertTrue(len(controller.abort.mock_calls))

        mock_file.assert_called_with("/proc/cpuinfo")


if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.DEBUG)
    unittest.main()
