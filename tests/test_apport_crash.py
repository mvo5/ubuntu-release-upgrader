#!/usr/bin/python3

import os
import sys
import tempfile
import unittest

from mock import patch

from DistUpgrade.DistUpgradeApport import (
    _apport_append_logfiles,
    apport_pkgfailure,
    APPORT_ALLOWLIST,
)
sys.path.insert(0, "..")


class TestApportInformationLeak(unittest.TestCase):

    def test_no_information_leak_in_apport_append_logfiles(self):
        tmpdir = tempfile.mkdtemp()
        from apport.report import Report
        report = Report()
        for name in ["apt.log", "system_state.tar.gz", "bar", "main.log"]:
            with open(os.path.join(tmpdir, name), "w") as f:
                f.write("some-data")
        _apport_append_logfiles(report, tmpdir)
        self.assertEqual(
            sorted([fname[0].name
                    for fname in report.values() if isinstance(f, tuple)]),
            sorted([os.path.join(tmpdir, "main.log"),
                    os.path.join(tmpdir, "apt.log")]))

    @patch("subprocess.Popen")
    def test_no_information_leak_in_apport_pkgfailure(self, mock_popen):
        # call apport_pkgfailure with mocked data
        apport_pkgfailure("apt", "random error msg")
        # extract the call arguments
        function_call_args, kwargs = mock_popen.call_args
        apport_cmd_args = function_call_args[0]
        # ensure that the allow list is honored
        for i in range(1, len(apport_cmd_args), 2):
            option = apport_cmd_args[i]
            arg = apport_cmd_args[i + 1]
            if option == "-l":
                self.assertTrue(os.path.basename(arg) in APPORT_ALLOWLIST)


if __name__ == "__main__":
    unittest.main()
