#!/usr/bin/python

import os
import sys
sys.path.insert(0, "../")

import unittest

from DistUpgrade.DistUpgradeFetcherCore import country_mirror

class testCountryMirror(unittest.TestCase):

      def testSimple(self):
            # empty
            try:
                del os.environ["LANG"] 
            except KeyError:
                pass
            self.assertEqual(country_mirror(),'')
            # simple
            os.environ["LANG"] = 'de'
            self.assertEqual(country_mirror(),'de.')
            # more complicated
            os.environ["LANG"] = 'en_DK.UTF-8'
            self.assertEqual(country_mirror(),'dk.')
            os.environ["LANG"] = 'fr_FR@euro.ISO-8859-15'
            self.assertEqual(country_mirror(),'fr.')
            

if __name__ == "__main__":
    unittest.main()
