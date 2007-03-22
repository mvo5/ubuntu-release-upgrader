# DistUpgradeControler.py 
#  
#  Copyright (c) 2004-2006 Canonical
#  
#  Author: Michael Vogt <michael.vogt@ubuntu.com>
# 
#  This program is free software; you can redistribute it and/or 
#  modify it under the terms of the GNU General Public License as 
#  published by the Free Software Foundation; either version 2 of the
#  License, or (at your option) any later version.
# 
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
# 
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA 02111-1307
#  USA


import warnings
warnings.filterwarnings("ignore", "apt API not stable yet", FutureWarning)
import apt
import apt_pkg
import sys
import os
import subprocess
import logging
import re
import statvfs
import shutil
import glob
import time
from DistUpgradeConfigParser import DistUpgradeConfig

from sourceslist import SourcesList, SourceEntry, is_mirror
from distro import Distribution, get_distro

from gettext import gettext as _
import gettext
from DistUpgradeCache import MyCache
from DistUpgradeApport import *

class AptCdrom(object):
    def __init__(self, view, path):
        self.view = view
        self.cdrompath = path
        
    def restoreBackup(self, backup_ext):
        " restore the backup copy of the cdroms.list file (*not* sources.list)! "
        cdromstate = os.path.join(apt_pkg.Config.FindDir("Dir::State"),
                                  apt_pkg.Config.Find("Dir::State::cdroms"))
        if os.path.exists(cdromstate+backup_ext):
            shutil.copy(cdromstate+backup_ext, cdromstate)
        # mvo: we don't have to care about restoring the sources.list here because
        #      aptsources will do this for us anyway
        
    def add(self, backup_ext=None):
        " add a cdrom to apts database "
        logging.debug("AptCdrom.add() called with '%s'", self.cdrompath)
        # do backup (if needed) of the cdroms.list file
        if backup_ext:
            cdromstate = os.path.join(apt_pkg.Config.FindDir("Dir::State"),
                                      apt_pkg.Config.Find("Dir::State::cdroms"))
            if os.path.exists(cdromstate):
                shutil.copy(cdromstate, cdromstate+backup_ext)
        # do the actual work
        apt_pkg.Config.Set("Acquire::cdrom::mount",self.cdrompath)
        apt_pkg.Config.Set("APT::CDROM::NoMount","true")
        cdrom = apt_pkg.GetCdrom()
        # FIXME: add cdrom progress here for the view
        progress = self.view.getCdromProgress()
        try:
            res = cdrom.Add(progress)
        except SystemError, e:
            logging.error("can't add cdrom: %s" % e)
            self.view.error(_("Failed to add the CD"),
                             _("There was a error adding the CD, the "
                               "upgrade will abort. Please report this as "
                               "a bug if this is a valid Ubuntu CD.\n\n"
                               "The error message was:\n'%s'") % e)
            return False
        logging.debug("AptCdrom.add() returned: %s" % res)
        return res

    def __nonzero__(self):
        """ helper to use this as 'if cdrom:' """
        return self.cdrompath is not None

class DistUpgradeControler(object):
    """ this is the controler that does most of the work """
    
    def __init__(self, distUpgradeView, options=None, datadir=None):
        # setup the pathes
        localedir = "/usr/share/locale/update-manager/"
        if datadir == None:
            datadir = os.getcwd()
            localedir = os.path.join(datadir,"mo")
            gladedir = datadir
        self.datadir = datadir

        self.options = options

        # init gettext
        gettext.bindtextdomain("update-manager",localedir)
        gettext.textdomain("update-manager")

        # setup the view
        self._view = distUpgradeView
        self._view.updateStatus(_("Reading cache"))
        self.cache = None

        if not self.options or self.options.withNetwork == None:
            self.useNetwork = True
        else:
            self.useNetwork = self.options.withNetwork
        if options:
            cdrompath = options.cdromPath
        else:
            cdrompath = None
        self.aptcdrom = AptCdrom(distUpgradeView, cdrompath)

        # we act differently in server mode
        self.serverMode = False
        if self.options and self.options.mode == "server":
            self.serverMode = True
        
        # the configuration
        self.config = DistUpgradeConfig(datadir)
        self.sources_backup_ext = "."+self.config.get("Files","BackupExt")
        
        # some constants here
        self.fromDist = self.config.get("Sources","From")
        self.toDist = self.config.get("Sources","To")
        self.origin = self.config.get("Sources","ValidOrigin")

        # forced obsoletes
        self.forced_obsoletes = self.config.getlist("Distro","ForcedObsoletes")

        # turn on debuging in the cache
        apt_pkg.Config.Set("Debug::pkgProblemResolver","true")
        apt_pkg.Config.Set("Debug::pkgDepCache::AutoInstall","true")
        fd = os.open("/var/log/dist-upgrade/apt.log",
                     os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_SYNC, 0644)
        os.dup2(fd,2)
        #os.dup2(fd,1)

    def openCache(self):
        self.cache = MyCache(self.config, self._view.getOpCacheProgress())

    def _sshMagic(self):
        """ this will check for server mode and if we run over ssh.
            if this is the case, we will ask and spawn a additional
            daemon (to be sure we have a spare one around in case
            of trouble)
        """
        if (self.serverMode and
            (os.environ.has_key("SSH_CONNECTION") or
             os.environ.has_key("SSH_TTY"))):
            port = 9004
            res = self._view.askYesNoQuestion(
                _("Continue running under SSH?"),
                _("This session appears to be running under ssh. "
                  "It is not recommended to perform a upgrade "
                  "over ssh currently because in case of failure "
                "it is harder to recover.\n\n"
                  "If you continue, a additional ssh daemon will be "
                  "started at port '%s'.\n"
                  "Do you want to continue?") % port)
            # abort
            if res == False:
                sys.exit(1)
            res = subprocess.call(["/usr/sbin/sshd","-p",str(port)])
            if res == 0:
                self._view.information(
                    _("Starting additional sshd"),
                    _("To make recovery in case of failure easier a "
                      "additional sshd will be started on port '%s'. "
                      "If anything goes wrong with the running ssh "
                      "you can still connect to the additional one.\n"
                      ) % port)

    def _tryUpdateSelf(self):
        """ this is a helper that is run if we are started from a CD
            and we have network - we will then try to fetch a update
            of ourself
        """  
        from MetaRelease import MetaReleaseCore
        from DistUpgradeFetcherSelf import DistUpgradeFetcherSelf
        # FIXME: during testing, we want "useDevelopmentRelease"
        #        but not after the release
        m = MetaReleaseCore(useDevelopmentRelease=False)
        # this will timeout eventually
        while m.downloading:
            time.sleep(0.5)
        if m.new_dist is None:
            logging.error("No new dist found")
            return False
        # we have a new dist
        progress = self._view.getFetchProgress()
        fetcher = DistUpgradeFetcherSelf(new_dist=m.new_dist,
                                         progress=progress,
                                         options=self.options,
                                         view=self._view)
        fetcher.run()
    
    def prepare(self):
        """ initial cache opening, sanity checking, network checking """
        self._sshMagic()
        try:
            self.openCache()
        except SystemError, e:
            logging.error("openCache() failed: '%s'" % e)
            return False
        if not self.cache.sanityCheck(self._view):
            return False
        # FIXME: we may try to find out a bit more about the network
        # connection here and ask more  inteligent questions
        if self.aptcdrom and self.options and self.options.withNetwork == None:
            res = self._view.askYesNoQuestion(_("Include latest updates from the Internet?"),
                                              _("The upgrade process can automatically download "
                                                "the latest updates and install them during the "
                                                "upgrade.  The upgrade will take longer, but when "
                                                "it is complete, your system will be fully up to "
                                                "date.  You can choose not to do this, but you "
                                                "should install the latest updates soon after "
                                                "upgrading."),
                                              'Yes'
                                              )
            self.useNetwork = res
            logging.debug("useNetwork: '%s' (selected by user)" % res)
            if res:
                self._tryUpdateSelf()
        return True

    def rewriteSourcesList(self, mirror_check=True):
        logging.debug("rewriteSourcesList()")

        # enable main (we always need this!)
        distro = get_distro()
        # FIXME: get_sources() needs to be called to init
        #        self.main_sources, this should be fixed in python-apt
        distro.get_sources(self.sources)
        # make sure that main is enabled
        distro.enable_component("main")

        # this must map, i.e. second in "from" must be the second in "to"
        # (but they can be different, so in theory we could exchange
        #  component names here)
        fromDists = [self.fromDist,
                     self.fromDist+"-security",
                     self.fromDist+"-updates",
                     self.fromDist+"-proposed",
                     self.fromDist+"-backports",
                     self.fromDist+"-commercial"
                    ]
        toDists = [self.toDist,
                   self.toDist+"-security",
                   self.toDist+"-updates",
                   self.toDist+"-proposed",
                   self.toDist+"-backports",
                   self.toDist+"-commercial"
                   ]

        # list of valid mirrors that we can add
        valid_mirrors = self.config.getListFromFile("Sources","ValidMirrors")

        self.sources_disabled = False

        # look over the stuff we have
        foundToDist = False
        for entry in self.sources:

            # ignore invalid records or disabled ones
            if entry.invalid or entry.disabled:
                continue
            
            # we disable breezy cdrom sources to make sure that demoted
            # packages are removed
            if entry.uri.startswith("cdrom:") and entry.dist == self.fromDist:
                entry.disabled = True
                continue
            # ignore cdrom sources otherwise
            elif entry.uri.startswith("cdrom:"):
                continue

            logging.debug("examining: '%s'" % entry)
            # check if it's a mirror (or offical site)
            validMirror = False
            for mirror in valid_mirrors:
                if not mirror_check or is_mirror(mirror,entry.uri):
                    validMirror = True
                    # security is a special case
                    res = not entry.uri.startswith("http://security.ubuntu.com") and not entry.disabled
                    if entry.dist in toDists:
                        # so the self.sources.list is already set to the new
                        # distro
                        logging.debug("entry '%s' is already set to new dist" % entry)
                        foundToDist |= res
                    elif entry.dist in fromDists:
                        foundToDist |= res
                        entry.dist = toDists[fromDists.index(entry.dist)]
                        logging.debug("entry '%s' updated to new dist" % entry)
                    else:
                        # disable all entries that are official but don't
                        # point to either "to" or "from" dist
                        entry.disabled = True
                        self.sources_disabled = True
                        logging.debug("entry '%s' was disabled (unknown dist)" % entry)
                    # it can only be one valid mirror, so we can break here
                    break
            # disable anything that is not from a official mirror
            if not validMirror:
                entry.disabled = True
                self.sources_disabled = True
                logging.debug("entry '%s' was disabled (unknown mirror)" % entry)
        return foundToDist

    def updateSourcesList(self):
        logging.debug("updateSourcesList()")
        self.sources = SourcesList(matcherPath=".")
        if not self.rewriteSourcesList(mirror_check=True):
            logging.error("No valid mirror found")
            res = self._view.askYesNoQuestion(_("No valid mirror found"),
                             _("While scanning your repository "
                               "information no mirror entry for "
                               "the upgrade was found."
                               "This cam happen if you run a internal "
                               "mirror or if the mirror information is "
                               "out of date.\n\n"
                               "Do you want to rewrite your "
                               "'sources.list' file anyway? If you choose "
                               "'Yes' here it will update all '%s' to '%s' "
                               "entries.\n"
                               "If you select 'no' the update will cancel."
                               ) % (self.fromDist, self.toDist))
            if res:
                # re-init the sources and try again
                self.sources = SourcesList(matcherPath=".")
                if not self.rewriteSourcesList(mirror_check=False):
                    #hm, still nothing useful ...
                    prim = _("Generate default sources?")
                    secon = _("After scanning your 'sources.list' no "
                              "valid entry for '%s' was found.\n\n"
                              "Should default entries for '%s' be "
                              "added? If you select 'No' the update "
                              "will cancel.") % (self.fromDist, self.toDist)
                    if not self._view.askYesNoQuestion(prim, secon):
                        self.abort()

                    # add some defaults here
                    # FIXME: find mirror here
                    uri = "http://archive.ubuntu.com/ubuntu"
                    comps = ["main","restricted"]
                    self.sources.add("deb", uri, self.toDist, comps)
                    self.sources.add("deb", uri, self.toDist+"-updates", comps)
                    self.sources.add("deb",
                                     "http://security.ubuntu.com/ubuntu/",
                                     self.toDist+"-security", comps)
            else:
                self.abort()

        # write (well, backup first ;) !
        self.sources.backup(self.sources_backup_ext)
        self.sources.save()

        # re-check if the written self.sources are valid, if not revert and
        # bail out
        # TODO: check if some main packages are still available or if we
        #       accidently shot them, if not, maybe offer to write a standard
        #       sources.list?
        try:
            sourceslist = apt_pkg.GetPkgSourceList()
            sourceslist.ReadMainList()
        except SystemError:
            logging.error("Repository information invalid after updating (we broke it!)")
            self._view.error(_("Repository information invalid"),
                             _("Upgrading the repository information "
                               "resulted in a invalid file. Please "
                               "report this as a bug."))
            return False

        if self.sources_disabled:
            self._view.information(_("Third party sources disabled"),
                             _("Some third party entries in your sources.list "
                               "were disabled. You can re-enable them "
                               "after the upgrade with the "
                               "'software-properties' tool or "
                               "your package manager."
                               ))
        return True

    def _logChanges(self):
        # debuging output
        logging.debug("About to apply the following changes")
        inst = []
        up = []
        rm = []
        held = []
        for pkg in self.cache:
            if pkg.markedInstall: inst.append(pkg.name)
            elif pkg.markedUpgrade: up.append(pkg.name)
            elif pkg.markedDelete: rm.append(pkg.name)
            elif (pkg.isInstalled and pkg.isUpgradable): held.append(pkg.name)
        logging.debug("Held-back: %s" % " ".join(held))
        logging.debug("Remove: %s" % " ".join(rm))
        logging.debug("Install: %s" % " ".join(inst))
        logging.debug("Upgrade: %s" % " ".join(up))
        

    def doPreUpgrade(self):
        # FIXME: check out what packages are downloadable etc to
        # compare the list after the update again
        self.obsolete_pkgs = self.cache._getObsoletesPkgs()
        self.foreign_pkgs = self.cache._getForeignPkgs(self.origin, self.fromDist, self.toDist)
        if self.serverMode:
            self.tasks = self.cache.installedTasks
        logging.debug("Foreign: %s" % " ".join(self.foreign_pkgs))
        logging.debug("Obsolete: %s" % " ".join(self.obsolete_pkgs))

    def doUpdate(self):
        if not self.useNetwork:
            logging.debug("doUpdate() will not use the network because self.useNetwork==false")
            return True
        self.cache._list.ReadMainList()
        progress = self._view.getFetchProgress()
        # FIXME: retry here too? just like the DoDistUpgrade?
        #        also remove all files from the lists partial dir!
        currentRetry = 0
        maxRetries = self.config.getint("Network","MaxRetries")
        while currentRetry < maxRetries:
            try:
                res = self.cache.update(progress)
            except IOError, e:
                logging.error("IOError in cache.update(): '%s'. Retrying (currentRetry: %s)" % (e,currentRetry))
                currentRetry += 1
                continue
            # no exception, so all was fine, we are done
            return True

        logging.error("doUpdate() failed complettely")
        self._view.error(_("Error during update"),
                         _("A problem occured during the update. "
                           "This is usually some sort of network "
                           "problem, please check your network "
                           "connection and retry."), "%s" % e)
        return False


    def _checkFreeSpace(self):
        " this checks if we have enough free space on /var and /usr"
        err_sum = _("Not enough free disk space")
        err_long= _("The upgrade aborts now. "
                    "Please free at least %s of disk space on %s. "
                    "Empty your trash and remove temporary "
                    "packages of former installations using "
                    "'sudo apt-get clean'.")

        class FreeSpace(object):
            " helper class that represents the free space on each mounted fs "
            def __init__(self, initialFree):
                self.free = initialFree

        # build fs_free
        # it has a map of the dirs we are interessted in and it
        # contains FreeSpace objects
        fs_free = {}
        mnt_map = {}
        archivedir = apt_pkg.Config.FindDir("Dir::Cache::archives")
        for d in ["/","/usr","/var","/boot", archivedir, "/home"]:
            st = os.statvfs(d)
            free = st[statvfs.F_BAVAIL]*st[statvfs.F_FRSIZE]
            if st in mnt_map:
                logging.debug("Dir %s mounted on %s" % (d,mnt_map[st]))
                fs_free[d] = fs_free[mnt_map[st]]
            else:
                logging.debug("Free space on %s: %s" % (d,free))
                mnt_map[st] = d
                fs_free[d] = FreeSpace(free)
        del mnt_map
        logging.debug("fs_free contains: '%s'" % fs_free)

        # we check for various sizes:
        # archivedir is were we download the debs
        # /usr is assumed to get *all* of the install space (incorrect,
        #      but as good as we can do currently + savety buffer
        # /boot is assumed to get at least 50 Mb
        # /     has a small savety buffer as well
        for (dir, size) in [(archivedir, self.cache.requiredDownload),
                            ("/usr", self.cache.additionalRequiredSpace),
                            ("/usr", 50*1024*1024),  # savetfy buffer /usr
                            ("/boot", 40*1024*1024), # savetfy buffer /boot
                            ("/", 10*1024*1024),     # small savetfy buffer /
                           ]:
            logging.debug("dir '%s' needs '%s' of '%s' (%f)" % (dir, size, fs_free[dir], fs_free[dir].free))
            fs_free[dir].free -= size
            if fs_free[dir].free < 0:
                free_at_least = apt_pkg.SizeToStr(float(abs(fs_free[dir].free)+1))
                logging.error("not enough free space on %s (missing %s)" % (dir, free_at_least))
                self._view.error(err_sum, err_long % (free_at_least,dir))
                return False

            
        return True

    def askDistUpgrade(self):
        if not self.cache.distUpgrade(self._view, self.serverMode):
            return False
        if self.serverMode:
            if not self.cache.installTasks(self.tasks):
                return False
        changes = self.cache.getChanges()
        # log the changes for debuging
        self._logChanges()
        # check if we have enough free space 
        if not self._checkFreeSpace():
            return False
        # ask the user if he wants to do the changes
        res = self._view.confirmChanges(_("Do you want to start the upgrade?"),
                                        changes,
                                        self.cache.requiredDownload)
        return res

    def doDistUpgrade(self):
        if self.options and self.options.haveBackports:
            backportsdir = os.getcwd()+"/backports"
            apt_pkg.Config.Set("Dir::Bin::dpkg",backportsdir+"/usr/bin/dpkg");
        currentRetry = 0
        fprogress = self._view.getFetchProgress()
        iprogress = self._view.getInstallProgress(self.cache)
        # retry the fetching in case of errors
        maxRetries = self.config.getint("Network","MaxRetries")
        while currentRetry < maxRetries:
            try:
                res = self.cache.commit(fprogress,iprogress)
            except SystemError, e:
                logging.error("SystemError from cache.commit(): %s" % e)
                # check if the installprogress catched a pkgfailure, if not, generate a fallback here
                if iprogress.pkg_failures == 0:
                    errormsg = "SystemError in cache.commit(): %s" % e
                    apport_pkgfailure("update-manager", errormsg)
                # installing the packages failed, can't be retried
                self._view.getTerminal().call(["dpkg","--configure","-a"])
                # invoke the frontend now
                msg = _("The upgrade aborts now. Your system "
                        "could be in an unusable state. A recovery "
                        "was run (dpkg --configure -a).")
                if not run_apport():
                    msg += _("\n\nPlease report this bug against the 'update-manager' "
                             "package and include the files in /var/log/dist-upgrade/ "
                             "in the bugreport.\n"
                             "%s" % e)
                self._view.error(_("Could not install the upgrades"), msg)
                return False
            except IOError, e:
                # fetch failed, will be retried
                logging.error("IOError in cache.commit(): '%s'. Retrying (currentTry: %s)" % (e,currentRetry))
                currentRetry += 1
                continue
            # no exception, so all was fine, we are done
            return True
        
        # maximum fetch-retries reached without a successful commit
        logging.error("giving up on fetching after maximum retries")
        self._view.error(_("Could not download the upgrades"),
                         _("The upgrade aborts now. Please check your "\
                           "internet connection or "\
                           "installation media and try again. "),
                           "%s" % e)
        # abort here because we want our sources.list back
        self.abort()



    def doPostUpgrade(self):
        self.openCache()
        # check out what packages are cruft now
        # use self.{foreign,obsolete}_pkgs here and see what changed
        now_obsolete = self.cache._getObsoletesPkgs()
        now_foreign = self.cache._getForeignPkgs(self.origin, self.fromDist, self.toDist)
        logging.debug("Obsolete: %s" % " ".join(now_obsolete))
        logging.debug("Foreign: %s" % " ".join(now_foreign))
        # check if we actually want obsolete removal
        if not self.config.getWithDefault("Distro","RemoveObsoletes", True):
            logging.debug("Skipping obsolete Removal")
            return True

        # now get the meta-pkg specific obsoletes and purges
        for pkg in self.config.getlist("Distro","MetaPkgs"):
            if self.cache.has_key(pkg) and self.cache[pkg].isInstalled:
                self.forced_obsoletes.extend(self.config.getlist(pkg,"ForcedObsoletes"))
        logging.debug("forced_obsoletes: %s", self.forced_obsoletes)

        # check what packages got demoted
        demotions = set()
        demotions_file = self.config.get("Distro","Demotions")
        if os.path.exists(demotions_file):
            map(lambda pkgname: demotions.add(pkgname.strip()),
                filter(lambda line: not line.startswith("#"),
                       open(demotions_file).readlines()))
        installed_demotions = filter(lambda pkg: pkg.isInstalled and pkg.name in demotions, self.cache)
        if len(installed_demotions) > 0:
            demoted = [pkg.name for pkg in installed_demotions]	
	    demoted.sort()
            logging.debug("demoted: '%s'" % " ".join(demoted))
            self._view.information(_("Support for some applications ended"),
                                   _("Canonical Ltd. no longer provides "
                                     "support for the following software "
                                     "packages. You can still get support "
                                     "from the community.\n\n"
                                     "If you have not enabled community "
                                     "maintained software (universe), "
                                     "these packages will be suggested for "
                                     "removal in the next step."),
                                   "\n".join(demoted))
       
        # mark packages that are now obsolete (and where not obsolete
        # before) to be deleted. make sure to not delete any foreign
        # (that is, not from ubuntu) packages
        if self.useNetwork:
            # we can only do the obsoletes calculation here if we use a
            # network. otherwise after rewriting the sources.list everything
            # that is not on the CD becomes obsolete (not-downloadable)
            remove_candidates = now_obsolete - self.obsolete_pkgs
        else:
            # initial remove candidates when no network is used should
            # be the demotions to make sure we don't leave potential
            # unsupported software
            remove_candidates = set(installed_demotions)
        remove_candidates |= set(self.forced_obsoletes)
        logging.debug("remove_candidates: '%s'" % remove_candidates)
        logging.debug("Start checking for obsolete pkgs")
        for pkgname in remove_candidates:
            if pkgname not in self.foreign_pkgs:
                if not self.cache._tryMarkObsoleteForRemoval(pkgname, remove_candidates, self.foreign_pkgs):
                    logging.debug("'%s' scheduled for remove but not in remove_candiates, skipping", pkgname)
        logging.debug("Finish checking for obsolete pkgs")

        # get changes
        changes = self.cache.getChanges()
        logging.debug("The following packages are remove candidates: %s" % " ".join([pkg.name for pkg in changes]))
        summary = _("Remove obsolete packages?")
        actions = [_("_Skip This Step"), _("_Remove")]
        # FIXME Add an explanation about what obsolete pacages are
        #explanation = _("")
        if len(changes) > 0 and \
               self._view.confirmChanges(summary, changes, 0, actions):
            fprogress = self._view.getFetchProgress()
            iprogress = self._view.getInstallProgress(self.cache)
            try:
                res = self.cache.commit(fprogress,iprogress)
            except (SystemError, IOError), e:
                logging.error("cache.commit() in doPostUpgrade() failed: %s" % e)
                self._view.error(_("Error during commit"),
                                 _("A problem occured during the clean-up. "
                                   "Please see the below message for more "
                                   "information. "),
                                   "%s" % e)
            
    def abort(self):
        """ abort the upgrade, cleanup (as much as possible) """
        if hasattr(self, "sources"):
            self.sources.restoreBackup(self.sources_backup_ext)
        if hasattr(self, "aptcdrom"):
            self.aptcdrom.restoreBackup(self.sources_backup_ext)
        # generate a new cache
        self._view.updateStatus(_("Restoring original system state"))
        self._view.abort()
        self.openCache()
        sys.exit(1)

    def getRequiredBackports(self):
        " download the backports specified in DistUpgrade.cfg "
        # add the backports sources.list fragment
        shutil.copy(self.config.get("Backports","SourcesList"),
                    apt_pkg.Config.FindDir("Dir::Etc::sourceparts"))
        # run update
        self.doUpdate()
        self.openCache()
        
        # save cachedir and setup new one
        cachedir = apt_pkg.Config.Find("Dir::Cache::archives")
        cwd = os.getcwd()
        backportsdir = os.path.join(os.getcwd(),"backports")
        if not os.path.exists(backportsdir):
            os.mkdir(backportsdir)
        if not os.path.exists(os.path.join(backportsdir,"partial")):
            os.mkdir(os.path.join(backportsdir,"partial"))
        os.chdir(backportsdir)
        apt_pkg.Config.Set("Dir::Cache::archives",backportsdir)

        # mark the backports for upgrade and get them
        fetcher = apt_pkg.GetAcquire(self._view.getFetchProgress())
        # FIXME: add a version line to the cfg file to make sure
        #        we get the right version file! and add sanity checking
        #        that we don't get (accidently) the edgy version
        for pkgname in self.config.getlist("Backports","Packages"):
            pkg = self.cache[pkgname]
            # look for the right version (backport)
            for ver in pkg._pkg.VersionList:
                if self.config.get("Backports","VersionIdent") in ver.VerStr:
                    break
            else:
                # FIXME: be more clever here (exception)
                raise Exception, "No backport found!?!"
                return False
            if ver.FileList == None:
                return False
            f, index = ver.FileList.pop(0)
            pkg._records.Lookup((f,index))
            path = apt_pkg.ParseSection(pkg._records.Record)["Filename"]
            for (packagefile,i) in ver.FileList:
		indexfile = self.cache._list.FindIndex(packagefile)
		if indexfile:
                    match = re.match(r"<.*ArchiveURI='(.*)'>$",
                                    str(indexfile))
                    if match:
                        uri = match.group(1) + path
                        apt_pkg.GetPkgAcqFile(fetcher, uri=uri,
                                              size=ver.Size,
                                              descr=_("Fetching backport of '%s'") % pkgname)
        res = fetcher.Run()
        if res != fetcher.ResultContinue:
            # ick! error ...
            return False

        # reset the cache dir
        os.unlink(apt_pkg.Config.FindDir("Dir::Etc::sourceparts")+"/backport-source.list")
        apt_pkg.Config.Set("Dir::Cache::archives",cachedir)
        os.chdir(cwd)
        # unpack it
        for deb in glob.glob(backportsdir+"/*.deb"):
            ret = os.system("dpkg-deb -x %s %s" % (deb, backportsdir))
            # FIXME: do error checking
        return self.setupRequiredBackports(backportsdir)

    def setupRequiredBackports(self, backportsdir):
        " setup the required backports in a evil way "
        # setup some pathes to make sure the new stuff is used
        os.environ["LD_LIBRARY_PATH"] = backportsdir+"/usr/lib"
        os.environ["PYTHONPATH"] = backportsdir+"/usr/lib/python2.4/site-packages/"
        os.environ["PATH"] = "%s:%s" % (backportsdir+"/usr/bin",
                                        os.getenv("PATH"))

        # now exec self again
        args = sys.argv+["--have-backports"]
        if self.useNetwork:
            args.append("--with-network")
        else:
            args.append("--without-network")
        os.execve(sys.argv[0],args, os.environ)

    # this is the core
    def fullUpgrade(self):
        # sanity check (check for ubuntu-desktop, brokenCache etc)
        self._view.updateStatus(_("Checking package manager"))
        self._view.setStep(1)
        
        if not self.prepare():
            logging.error("self.prepared() failed")
            self._view.error(_("Preparing the upgrade failed"),
                             _("Preparing the system for the upgrade "
                               "failed. Please report this as a bug "
                               "against the 'update-manager' "
                               "package and include the files in "
                               "/var/log/dist-upgrade/ "
                               "in the bugreport." ))
            sys.exit(1)

        # mvo: commented out for now, see #54234, this needs to be
        #      refactored to use a arch=any tarball
        #if self.options and self.options.haveBackports == False:
        #    # get backported packages (if needed)
        #    self.getRequiredBackports()

        # run a "apt-get update" now
        if not self.doUpdate():
            sys.exit(1)

        # do pre-upgrade stuff (calc list of obsolete pkgs etc)
        self.doPreUpgrade()

        # update sources.list
        self._view.setStep(2)
        self._view.updateStatus(_("Updating repository information"))
        if not self.updateSourcesList():
            self.abort()

        # add cdrom (if we have one)
        if (self.aptcdrom and
            not self.aptcdrom.add(self.sources_backup_ext)):
            sys.exit(1)

        # then update the package index files
        if not self.doUpdate():
            self.abort()

        # then open the cache (again)
        self._view.updateStatus(_("Checking package manager"))
        self.openCache()
        # now check if we still have some key packages after the update
        # if not something went seriously wrong
        for pkg in self.config.getlist("Distro","BaseMetaPkgs"):
            if not self.cache.has_key(pkg):
                # FIXME: we could offer to add default source entries here,
                #        but we need to be careful to not duplicate them
                #        (i.e. the error here could be something else than
                #        missing sources entires but network errors etc)
                logging.error("No '%s' after sources.list rewrite+update")
                self._view.error(_("Invalid package information"),
                                 _("After your package information was "
                                   "updated the essential package '%s' can "
                                   "not be found anymore.\n"
                                   "This indicates a serious error, please "
                                   "report this bug against the 'update-manager' "
                                   "package and include the files in /var/log/dist-upgrade/ "
                                   "in the bugreport.") % pkg)
                self.abort()

        # calc the dist-upgrade and see if the removals are ok/expected
        # do the dist-upgrade
        self._view.setStep(3)
        self._view.updateStatus(_("Asking for confirmation"))
        if not self.askDistUpgrade():
            self.abort()

        # kill update-notifier now to supress reboot required
        subprocess.call(["killall","update-notifier"])
        # no do the upgrade
        self._view.updateStatus(_("Upgrading"))
        if not self.doDistUpgrade():
            # don't abort here, because it would restore the sources.list
            sys.exit(1) 
            
        # do post-upgrade stuff
        self._view.setStep(4)
        self._view.updateStatus(_("Searching for obsolete software"))
        self.doPostUpgrade()

        # done, ask for reboot
        self._view.setStep(5)
        self._view.updateStatus(_("System upgrade is complete."))            
        # FIXME should we look into /var/run/reboot-required here?
        if self._view.confirmRestart():
            p = subprocess.Popen("/sbin/reboot")
            sys.exit(0)
        
    def run(self):
        self.fullUpgrade()


if __name__ == "__main__":
    from DistUpgradeView import DistUpgradeView
    v = DistUpgradeView()
    dc = DistUpgradeControler(v)
    dc._checkFreeSpace()
