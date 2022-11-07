#!/bin/sh

set -e

# The testsuite has a sad if you're in a non-UTF-8 locale:
export LANG='C.UTF-8'

dpkg-checkbuilddeps -d 'python3-apt, apt-btrfs-snapshot, parsewiki, python3-feedparser,
			python3-mock, xvfb, gir1.2-gtk-3.0, python3-gi, python3-nose, pycodestyle, python3-distutils-extra, python3-update-manager'

# make sure the DistUpgrade symlink is good LP: #1824430
SYMLINK=$(readlink -q DistUpgrade/DistUpgrade)
if [ $SYMLINK != "." ]; then
   echo "DistUpgrade/DistUpgrade is not a symlink to itself"
   exit 1
fi

# run the test-suite
# echo "Running integrated tests"
xvfb-run nosetests3

# test leftovers
# echo "Cleaning up after tests"
rm -f ./tests/data-sources-list-test/apt.log
rm -f ./tests/data-sources-list-test/Ubuntu.mirrors

# update demotions
# echo "Running demotions"
(cd utils && ./demotions.py kinetic lunar > demoted.cfg)

# when this gets enabled, make sure to add symlink in DistUpgrade
# echo "Running lts demotions"
(cd utils && ./demotions.py jammy lunar > demoted.cfg.jammy)

# update apt_btrfs_snapshot.py copy, this needs an installed
# apt-btrfs-snapshot on the build machine
if [ ! -e /usr/lib/python3/dist-packages/apt_btrfs_snapshot.py ]; then
    echo "please sudo apt-get install apt-btrfs-snapshot"
    exit 1
fi
echo "copying apt_btrfs_snapshot.py for the upgrader tarball"
cp /usr/lib/python3/dist-packages/apt_btrfs_snapshot.py DistUpgrade

# update invoke-rc.d copy, requires init-system-helpers
if [ ! -e /usr/sbin/invoke-rc.d ]; then
    echo "please sudo apt install init-system-helpers"
    exit 1
fi
if [ ! -e /usr/bin/patch ]; then
    echo "please sudo apt install patch"
    exit 1
fi
echo "copying invoke-rc.d for the upgrader tarball"
cp /usr/sbin/invoke-rc.d DistUpgrade/imported/
# now patch the file so the upgrade can continue even if there are errors
patch --fuzz=0 -p0 DistUpgrade/imported/invoke-rc.d DistUpgrade/imported/invoke-rc.d.diff || { echo "patch didn't apply cleanly" && exit 1; }

# update the translations
cd po; make update-po; cd ../

# (auto) generate the required html
if [ ! -x /usr/bin/parsewiki ]; then
    echo "please sudo apt-get install parsewiki"
    exit 1
fi
# confirm we have the release version appearing the right number of times in each Announcement
DEBRELEASE=$(LC_ALL=C dpkg-parsechangelog | sed -n -e '/^Distribution:/s/^Distribution: //p' | sed s/-.\*//)
(cd DistUpgrade;
 if [ $(grep -ic $DEBRELEASE DevelReleaseAnnouncement) != 1 ]; then
    echo "Confirm $DEBRELEASE is correct in DevelReleaseAnnouncement"
    exit 1
 fi
 parsewiki DevelReleaseAnnouncement > DevelReleaseAnnouncement.html;
 if [ $(grep -ic $DEBRELEASE ReleaseAnnouncement) != 3 ]; then
    echo "Confirm $DEBRELEASE is correct in ReleaseAnnouncement"
    exit 1
 fi
 parsewiki ReleaseAnnouncement > ReleaseAnnouncement.html;
 if [ $(grep -ic $DEBRELEASE EOLReleaseAnnouncement) != 1 ]; then
    echo "Confirm $DEBRELEASE is correct in EOLReleaseAnnouncement"
    exit 1
 fi
 parsewiki EOLReleaseAnnouncement > EOLReleaseAnnouncement.html;
)

# cleanup
rm -rf utils/apt/lists utils/apt/*.bin utils/apt/sources.list
# echo "Running update mirrors"
(cd utils && ./update_mirrors.py ../data/mirrors.cfg)

# update version
DEBVER=$(LC_ALL=C dpkg-parsechangelog |sed -n -e '/^Version:/s/^Version: //p' | sed s/.*://)
echo "VERSION = '$DEBVER'" > DistUpgrade/DistUpgradeVersion.py
