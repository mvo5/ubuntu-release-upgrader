# __init__.py for computerjanitor
# Copyright (C) 2008  Canonical, Ltd.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.


from __future__ import absolute_import

VERSION = "1.11"


# Set up gettext. This needs to be before the import statements below
# so that if any modules call it right after importing, they find
# setup_gettext.

def setup_gettext():
    """Set up gettext for a module.

    Return a method to be used for looking up translations. Usage:

      import computerjanitor
      _ = computerjanitor.setup_gettext()

    """

    import gettext
    import os

    domain = 'update-manager'
    localedir = os.environ.get('LOCPATH', None)
    t = gettext.translation(domain, localedir=localedir, fallback=True)
    try:
        return t.ugettext
    except AttributeError:
        return t.gettext


from .cruft import Cruft
from .file_cruft import FileCruft
from .package_cruft import PackageCruft
from .missing_package_cruft import MissingPackageCruft
from .exc import ComputerJanitorException as Exception, UnimplementedMethod
from .plugin import Plugin, PluginManager

# reference it here to make pyflakes happy
Cruft
FileCruft
PackageCruft
Exception
UnimplementedMethod
MissingPackageCruft
Plugin
PluginManager


