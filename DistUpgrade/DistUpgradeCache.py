import warnings
warnings.filterwarnings("ignore", "apt API not stable yet", FutureWarning)
import apt
import apt_pkg
import os
import os.path
import re
import logging
import string
import time
import gettext
import datetime
import threading
import ConfigParser
from subprocess import Popen, PIPE

from DistUpgradeGettext import gettext as _
from DistUpgradeGettext import ngettext
from DistUpgradeConfigParser import DistUpgradeConfig
from DistUpgradeView import FuzzyTimeToStr


class CacheException(Exception):
    pass
class CacheExceptionLockingFailed(CacheException):
    pass
class CacheExceptionDpkgInterrupted(CacheException):
    pass

class MyCache(apt.Cache):
    ReInstReq = 1
    HoldReInstReq = 3

    # init
    def __init__(self, config, view, progress=None, lock=True):
        apt.Cache.__init__(self, progress)
        self.to_install = []
        self.to_remove = []
        self.view = view
        self.lock = False
        self.config = config
        self.metapkgs = self.config.getlist("Distro","MetaPkgs")
        # acquire lock
        self._listsLock = -1
        if lock:
            try:
                apt_pkg.PkgSystemLock()
                self.lockListsDir()
                self.lock = True
            except SystemError, e:
                # checking for this is ok, its not translatable
                if "dpkg was interrupted" in str(e):
                    raise CacheExceptionDpkgInterrupted, e
                raise CacheExceptionLockingFailed, e
        # a list of regexp that are not allowed to be removed
        self.removal_blacklist = config.getListFromFile("Distro","RemovalBlacklistFile")
        self.uname = Popen(["uname","-r"],stdout=PIPE).communicate()[0].strip()
        self._initAptLog()
        # from hardy on we use recommends by default, so for the 
        # transition to the new dist we need to enable them now
        if (config.get("Sources","From") == "hardy" and 
            not "RELEASE_UPGRADE_NO_RECOMMENDS" in os.environ):
            apt_pkg.Config.Set("APT::Install-Recommends","true")

    @property
    def reqReinstallPkgs(self):
        " return the packages not downloadable packages in reqreinst state "
        reqreinst = set()
        for pkg in self:
            if (not pkg.candidateDownloadable and 
                (pkg._pkg.InstState == self.ReInstReq or
                 pkg._pkg.InstState == self.HoldReInstReq)):
                reqreinst.add(pkg.name)
        return reqreinst

    def fixReqReinst(self, view):
        " check for reqreinst state and offer to fix it "
        reqreinst = self.reqReinstallPkgs
        if len(reqreinst) > 0:
            header = ngettext("Remove package in bad state",
                              "Remove packages in bad state", 
                              len(reqreinst))
            summary = ngettext("The package '%s' is in an inconsistent "
                               "state and needs to be reinstalled, but "
                               "no archive can be found for it. "
                               "Do you want to remove this package "
                               "now to continue?",
                               "The packages '%s' are in an inconsistent "
                               "state and needs to be reinstalled, but "
                               "no archives can be found for them. Do you "
                               "want to remove these packages now to "
                               "continue?",
                               len(reqreinst)) % ", ".join(reqreinst)
            if view.askYesNoQuestion(header, summary):
                self.releaseLock()
                cmd = ["dpkg","--remove","--force-remove-reinstreq"] + list(reqreinst)
                view.getTerminal().call(cmd)
                self.getLock()
                return True
        return False

    # logging stuff
    def _initAptLog(self):
        " init logging, create log file"
        logdir = self.config.getWithDefault("Files","LogDir",
                                            "/var/log/dist-upgrade")
        apt_pkg.Config.Set("Dir::Log",logdir)
        apt_pkg.Config.Set("Dir::Log::Terminal","apt-term.log")
        self.logfd = os.open(os.path.join(logdir,"apt.log"),
                             os.O_RDWR|os.O_CREAT|os.O_APPEND|os.O_SYNC, 0644)
        os.write(self.logfd, "Log time: %s\n" % datetime.datetime.now())
        # turn on debugging in the cache
        apt_pkg.Config.Set("Debug::pkgProblemResolver","true")
        apt_pkg.Config.Set("Debug::pkgDepCache::AutoInstall","true")
    def _startAptResolverLog(self):
        if hasattr(self, "old_stdout"):
            os.close(self.old_stdout)
            os.close(self.old_stderr)
        self.old_stdout = os.dup(1)
        self.old_stderr = os.dup(2)
        os.dup2(self.logfd, 1)
        os.dup2(self.logfd, 2)
    def _stopAptResolverLog(self):
        os.fsync(1)
        os.fsync(2)
        os.dup2(self.old_stdout, 1)
        os.dup2(self.old_stderr, 2)
    # use this decorator instead of the _start/_stop stuff directly
    # FIXME: this should probably be a decorator class where all
    #        logging is moved into?
    def withResolverLog(f):
        " decorator to ensure that the apt output is logged "
        def wrapper(*args, **kwargs):
            args[0]._startAptResolverLog()
            res = f(*args, **kwargs)
            args[0]._stopAptResolverLog()
            return res
        return wrapper

    # properties
    @property
    def requiredDownload(self):
        """ get the size of the packages that are required to download """
        pm = apt_pkg.GetPackageManager(self._depcache)
        fetcher = apt_pkg.GetAcquire()
        pm.GetArchives(fetcher, self._list, self._records)
        return fetcher.FetchNeeded
    @property
    def additionalRequiredSpace(self):
        """ get the size of the additional required space on the fs """
        return self._depcache.UsrSize
    @property
    def isBroken(self):
        """ is the cache broken """
        return self._depcache.BrokenCount > 0

    # methods
    def lockListsDir(self):
        name = apt_pkg.Config.FindDir("Dir::State::Lists") + "lock"
        self._listsLock = apt_pkg.GetLock(name)
        if self._listsLock < 0:
            e = "Can not lock '%s' " % name
            raise CacheExceptionLockingFailed, e
    def unlockListsDir(self):
        if self._listsLock > 0:
            os.close(self._listsLock)
            self._listsLock = -1
    def update(self, fprogress=None):
        """
        our own update implementation is required because we keep the lists
        dir lock
        """
        self.unlockListsDir()
        apt.Cache.update(self, fprogress)
        self.lockListsDir()

    def commit(self, fprogress, iprogress):
        logging.info("cache.commit()")
        if self.lock:
            self.releaseLock()
        apt.Cache.commit(self, fprogress, iprogress)

    def releaseLock(self, pkgSystemOnly=True):
        if self.lock:
            try:
                apt_pkg.PkgSystemUnLock()
                self.lock = False
            except SystemError, e:
                logging.debug("failed to SystemUnLock() (%s) " % e)

    def getLock(self, pkgSystemOnly=True):
        if not self.lock:
            try:
                apt_pkg.PkgSystemLock()
                self.lock = True
            except SystemError, e:
                logging.debug("failed to SystemLock() (%s) " % e)

    def downloadable(self, pkg, useCandidate=True):
        " check if the given pkg can be downloaded "
        if useCandidate:
            ver = self._depcache.GetCandidateVer(pkg._pkg)
        else:
            ver = pkg._pkg.CurrentVer
        if ver == None:
            logging.warning("no version information for '%s' (useCandidate=%s)" % (pkg.name, useCandidate))
            return False
        return ver.Downloadable
    
    def fixBroken(self):
        """ try to fix broken dependencies on the system, may throw
            SystemError when it can't"""
        return self._depcache.FixBroken()

    def create_snapshot(self):
        """ create a snapshot of the current changes """
        self.to_install = []
        self.to_remove = []
        for pkg in self.getChanges():
            if pkg.markedInstall or pkg.markedUpgrade:
                self.to_install.append(pkg.name)
            if pkg.markedDelete:
                self.to_remove.append(pkg.name)

    def clear(self):
        self._depcache.Init()

    def restore_snapshot(self):
        """ restore a snapshot """
        actiongroup = apt_pkg.GetPkgActionGroup(self._depcache)
        self.clear()
        for name in self.to_remove:
            pkg = self[name]
            pkg.markDelete()
        for name in self.to_install:
            pkg = self[name]
            pkg.markInstall(autoFix=False, autoInst=False)

    def needServerMode(self):
        """ 
        This checks if we run on a desktop or a server install.
        
        A server install has more freedoms, for a desktop install
        we force a desktop meta package to be install on the upgrade.

        We look for a installed desktop meta pkg and for key 
        dependencies, if none of those are installed we assume
        server mode
        """
        #logging.debug("needServerMode() run")
        # check for the MetaPkgs (e.g. ubuntu-desktop)
        metapkgs = self.config.getlist("Distro","MetaPkgs")
        for key in metapkgs:
            # if it is installed we are done
            if self.has_key(key) and self[key].isInstalled:
                logging.debug("needServerMode(): run in 'desktop' mode, (because of pkg '%s')" % key)
                return False
            # if it is not installed, but its key depends are installed 
            # we are done too (we auto-select the package later)
            deps_found = True
            for pkg in self.config.getlist(key,"KeyDependencies"):
                deps_found &= self.has_key(pkg) and self[pkg].isInstalled
            if deps_found:
                logging.debug("needServerMode(): run in 'desktop' mode, (because of key deps for '%s')" % key)
                return False
        logging.debug("needServerMode(): can not find a desktop meta package or key deps, running in server mode")
        return True

    def sanityCheck(self, view):
        """ check if the cache is ok and if the required metapkgs
            are installed
        """
        if self.isBroken:
            try:
                logging.debug("Have broken pkgs, trying to fix them")
                self.fixBroken()
            except SystemError:
                view.error(_("Broken packages"),
                                 _("Your system contains broken packages "
                                   "that couldn't be fixed with this "
                                   "software. "
                                   "Please fix them first using synaptic or "
                                   "apt-get before proceeding."))
                return False
        return True

    def markInstall(self, pkg, reason=""):
        logging.debug("Installing '%s' (%s)" % (pkg, reason))
        if self.has_key(pkg):
            self[pkg].markInstall()
            if not (self[pkg].markedInstall or self[pkg].markedUpgrade):
                logging.error("Installing/upgrading '%s' failed" % pkg)
                #raise (SystemError, "Installing '%s' failed" % pkg)
    def markRemove(self, pkg, reason=""):
        logging.debug("Removing '%s' (%s)" % (pkg, reason))
        if self.has_key(pkg):
            self[pkg].markDelete()
    def markPurge(self, pkg, reason=""):
        logging.debug("Purging '%s' (%s)" % (pkg, reason))
        if self.has_key(pkg):
            self._depcache.MarkDelete(self[pkg]._pkg,True)

    def keepInstalledRule(self):
        """ run after the dist-upgrade to ensure that certain
            packages are kept installed """
        def keepInstalled(self, pkgname, reason):
            if (self.has_key(pkgname)
                and self[pkgname].isInstalled
                and self[pkgname].markedDelete):
                self.markInstall(pkgname, reason)
                
        # first the global list
        for pkgname in self.config.getlist("Distro","KeepInstalledPkgs"):
            keepInstalled(self, pkgname, "Distro KeepInstalledPkgs rule")
        # the the per-metapkg rules
        for key in self.metapkgs:
            if self.has_key(key) and (self[key].isInstalled or
                                      self[key].markedInstall):
                for pkgname in self.config.getlist(key,"KeepInstalledPkgs"):
                    keepInstalled(self, pkgname, "%s KeepInstalledPkgs rule" % key)

        # only enforce section if we have a network. Otherwise we run
        # into CD upgrade issues for installed language packs etc
        if self.config.get("Options","withNetwork") == "True":
            logging.debug("Running KeepInstalledSection rules")
            # now the KeepInstalledSection code
            for section in self.config.getlist("Distro","KeepInstalledSection"):
                for pkg in self:
                    if pkg.markedDelete and pkg.section == section:
                        keepInstalled(self, pkg.name, "Distro KeepInstalledSection rule: %s" % section)
            for key in self.metapkgs:
                if self.has_key(key) and (self[key].isInstalled or
                                          self[key].markedInstall):
                    for section in self.config.getlist(key,"KeepInstalledSection"):
                        for pkg in self:
                            if pkg.markedDelete and pkg.section == section:
                                keepInstalled(self, pkg.name, "%s KeepInstalledSection rule: %s" % (key, section))
        

    def postUpgradeRule(self):
        " run after the upgrade was done in the cache "
        for (rule, action) in [("Install", self.markInstall),
                               ("Remove", self.markRemove),
                               ("Purge", self.markPurge)]:
            # first the global list
            for pkg in self.config.getlist("Distro","PostUpgrade%s" % rule):
                action(pkg, "Distro PostUpgrade%s rule" % rule)
            for key in self.metapkgs:
                if self.has_key(key) and (self[key].isInstalled or
                                          self[key].markedInstall):
                    for pkg in self.config.getlist(key,"PostUpgrade%s" % rule):
                        action(pkg, "%s PostUpgrade%s rule" % (key, rule))

        # get the distro-specific quirks handler and run it
        for quirksFuncName in ("%sQuirks" % self.config.get("Sources","To"),
                               "from_%sQuirks" % self.config.get("Sources","From")):
            func = getattr(self, quirksFuncName, None)
            if func is not None:
                func()

    def from_dapperQuirks(self):
        self.hardyQuirks()
        self.gutsyQuirks()
        self.feistyQuirks()
        self.edgyQuirks()

    def _checkAndRemoveEvms(self):
        " check if evms is in use and if not, remove it "
        logging.debug("running _checkAndRemoveEvms")
        for line in open("/proc/mounts"):
            line = line.strip()
            if line == '' or line.startswith("#"):
                continue
            try:
                (device, mount_point, fstype, options, a, b) = line.split()
            except Exception, e:
                logging.error("can't parse line '%s'" % line)
                continue
            if "evms" in device:
                logging.debug("found evms device in line '%s', skipping " % line)
                return False
        # if not in use, nuke it
        for pkg in ["evms","libevms-2.5","libevms-dev",
                    "evms-ncurses", "evms-ha",
                    "evms-bootdebug",
                    "evms-gui", "evms-cli",
                    "linux-patch-evms"]:
            if self.has_key(pkg) and self[pkg].isInstalled:
                self[pkg].markDelete()
        return True

    def identifyObsoleteKernels(self):
        # we have a funny policy that we remove security updates
        # for the kernel from the archive again when a new ABI
        # version hits the archive. this means that we have
        # e.g. 
        # linux-image-2.6.24-15-generic 
        # is obsolete when 
        # linux-image-2.6.24-19-generic
        # is available
        # ...
        # This code tries to identify the kernels that can be removed
        logging.debug("identifyObsoleteKernels()")
        obsolete_kernels = set()
        version = self.config.get("KernelRemoval","Version")
        basenames = self.config.getlist("KernelRemoval","BaseNames")
        types = self.config.getlist("KernelRemoval","Types")
        for pkg in self:
            for base in basenames:
                basename = "%s-%s-" % (base,version)
                for type in types:
                    if (pkg.name.startswith(basename) and 
                        pkg.name.endswith(type) and
                        pkg.isInstalled):
                        if (pkg.name == "%s-%s" % (base,self.uname)):
                            logging.debug("skipping running kernel %s" % pkg.name)
                            continue
                        logging.debug("removing obsolete kernel '%s'" % pkg.name)
                        obsolete_kernels.add(pkg.name)
        logging.debug("identifyObsoleteKernels found '%s'" % obsolete_kernels)
        return obsolete_kernels

    def intrepidQuirks(self):
        """ 
        this function works around quirks in the 
        hardy->intrepid upgrade 
        """
        logging.debug("intrepidQuirks")
        # for kde we need to switch from 
        # kubuntu-desktop-kde4 
        # to
        # kubuntu-desktop
        frompkg = "kubuntu-desktop-kde4"
        topkg = "kubuntu-desktop"
        if (self.has_key(frompkg) and
            self[frompkg].isInstalled):
            logging.debug("transitioning %s to %s" % (frompkg, topkg))
            self[topkg].markInstall()
        # landscape-client (in desktop mode) goes away (was a stub
        # anyway)
        name = "landscape-client"
        ver = "0.1"
        if not self.serverMode:
            if (self.has_key(name) and
                self[name].installedVersion == ver):
                self.markRemove(name, 
                                "custom landscape stub removal rule")
                self.markRemove("landscape-common", 
                                "custom landscape stub removal rule")

    def hardyQuirks(self):
        """ 
        this function works around quirks in the 
        {dapper,gutsy}->hardy upgrade 
        """
        logging.debug("running hardyQuirks handler")
        # deal with gnome-translator and help apt with the breaks
        if (self.has_key("nautilus") and
            self["nautilus"].isInstalled and
            not self["nautilus"].markedUpgrade):
            # uninstallable and gutsy apt is unhappy about this
            # breaks because it wants to upgrade it and gives up
            # if it can't
            for broken in ("link-monitor-applet"):
                if self.has_key(broken) and self[broken].isInstalled:
                    self[broken].markDelete()
            self["nautilus"].markInstall()
        # evms gives problems, remove it if it is not in use
        self._checkAndRemoveEvms()
        # give the language-support-* packages a extra kick
        # (if we have network, otherwise this will not work)
        if self.config.get("Options","withNetwork") == "True":
            for pkg in self:
                if (pkg.name.startswith("language-support-") and
                    pkg.isInstalled and
                    not pkg.markedUpgrade):
                    self.markInstall(pkg.name,"extra language-support- kick")

    def gutsyQuirks(self):
        """ this function works around quirks in the feisty->gutsy upgrade """
        logging.debug("running gutsyQuirks handler")
        # lowlatency kernel flavour vanished from feisty->gutsy
        try:
            (version, build, flavour) = self.uname.split("-")
            if (flavour == 'lowlatency' or 
                flavour == '686' or
                flavour == 'k7'):
                kernel = "linux-image-generic"
                if not (self[kernel].isInstalled or self[kernel].markedInstall):
                    logging.debug("Selecting new kernel '%s'" % kernel)
                    self[kernel].markInstall()
        except Exception, e:
            logging.warning("problem while transitioning lowlatency kernel (%s)" % e)
        # fix feisty->gutsy utils-linux -> nfs-common transition (LP: #141559)
        try:
            for line in map(string.strip, open("/proc/mounts")):
                if line == '' or line.startswith("#"):
                    continue
                try:
                    (device, mount_point, fstype, options, a, b) = line.split()
                except Exception, e:
                    logging.error("can't parse line '%s'" % line)
                    continue
                if "nfs" in fstype:
                    logging.debug("found nfs mount in line '%s', marking nfs-common for install " % line)
                    self["nfs-common"].markInstall()
                    break
        except Exception, e:
            logging.warning("problem while transitioning util-linux -> nfs-common (%s)" % e)

    def feistyQuirks(self):
        """ this function works around quirks in the edgy->feisty upgrade """
        logging.debug("running feistyQuirks handler")
        # ndiswrapper changed again *sigh*
        for (fr, to) in [("ndiswrapper-utils-1.8","ndiswrapper-utils-1.9")]:
            if self.has_key(fr) and self.has_key(to):
                if self[fr].isInstalled and not self[to].markedInstall:
                    try:
                        self.markInstall(to,"%s->%s quirk upgrade rule" % (fr, to))
                    except SystemError, e:
                        logging.warning("Failed to apply %s->%s install (%s)" % (fr, to, e))
            

    def edgyQuirks(self):
        """ this function works around quirks in the dapper->edgy upgrade """
        logging.debug("running edgyQuirks handler")
        for pkg in self:
            # deal with the python2.4-$foo -> python-$foo transition
            if (pkg.name.startswith("python2.4-") and
                pkg.isInstalled and
                not pkg.markedUpgrade):
                basepkg = "python-"+pkg.name[len("python2.4-"):]
                if (self.has_key(basepkg) and 
                    self[basepkg].candidateDownloadable and
                    not self[basepkg].markedInstall):
                    try:
                        self.markInstall(basepkg,
                                         "python2.4->python upgrade rule")
                    except SystemError, e:
                        logging.debug("Failed to apply python2.4->python install: %s (%s)" % (basepkg, e))
            # xserver-xorg-input-$foo gives us trouble during the upgrade too
            if (pkg.name.startswith("xserver-xorg-input-") and
                pkg.isInstalled and
                not pkg.markedUpgrade):
                try:
                    self.markInstall(pkg.name, "xserver-xorg-input fixup rule")
                except SystemError, e:
                    logging.debug("Failed to apply fixup: %s (%s)" % (pkg.name, e))
            
        # deal with held-backs that are unneeded
        for pkgname in ["hpijs", "bzr", "tomboy"]:
            if (self.has_key(pkgname) and self[pkgname].isInstalled and
                self[pkgname].isUpgradable and not self[pkgname].markedUpgrade):
                try:
                    self.markInstall(pkgname,"%s quirk upgrade rule" % pkgname)
                except SystemError, e:
                    logging.debug("Failed to apply %s install (%s)" % (pkgname,e))
        # libgl1-mesa-dri from xgl.compiz.info (and friends) breaks the
	# upgrade, work around this here by downgrading the package
        if self.has_key("libgl1-mesa-dri"):
            pkg = self["libgl1-mesa-dri"]
            # the version from the compiz repo has a "6.5.1+cvs20060824" ver
            if (pkg.candidateVersion == pkg.installedVersion and
                "+cvs2006" in pkg.candidateVersion):
                for ver in pkg._pkg.VersionList:
                    # the "official" edgy version has "6.5.1~20060817-0ubuntu3"
                    if "~2006" in ver.VerStr:
			# ensure that it is from a trusted repo
			for (VerFileIter, index) in ver.FileList:
				indexfile = self._list.FindIndex(VerFileIter)
				if indexfile and indexfile.IsTrusted:
					logging.info("Forcing downgrade of libgl1-mesa-dri for xgl.compz.info installs")
		                        self._depcache.SetCandidateVer(pkg._pkg, ver)
					break
                                    
        # deal with general if $foo is installed, install $bar
        for (fr, to) in [("xserver-xorg-driver-all","xserver-xorg-video-all")]:
            if self.has_key(fr) and self.has_key(to):
                if self[fr].isInstalled and not self[to].markedInstall:
                    try:
                        self.markInstall(to,"%s->%s quirk upgrade rule" % (fr, to))
                    except SystemError, e:
                        logging.debug("Failed to apply %s->%s install (%s)" % (fr, to, e))
                    
                    
                                  
    def dapperQuirks(self):
        """ this function works around quirks in the breezy->dapper upgrade """
        logging.debug("running dapperQuirks handler")
        if (self.has_key("nvidia-glx") and self["nvidia-glx"].isInstalled and
            self.has_key("nvidia-settings") and self["nvidia-settings"].isInstalled):
            logging.debug("nvidia-settings and nvidia-glx is installed")
            self.markRemove("nvidia-settings")
            self.markInstall("nvidia-glx")


    def checkForNvidia(self):
        """ 
        this checks for nvidia hardware and checks what driver is needed
        """
        logging.debug("nvidiaUpdate()")
        # if the free drivers would give us a equally hard time, we would
        # never be able to release
        try:
            from NvidiaDetector.nvidiadetector import NvidiaDetection
        except ImportError, e:
            logging.error("NvidiaDetector can not be imported %s" % e)
            return False
        try:
            # get new detection module and use the modalises files
            # from within the release-upgrader
            nv = NvidiaDetection(datadir="modaliases/")
            #nv = NvidiaDetection()
            # check if a binary driver is installed now
            for oldDriver in nv.oldPackages:
                if self.has_key(oldDriver) and self[oldDriver].isInstalled:
                    break
            else:
                logging.info("no nvidia driver installed before, installing none")
                return False
            # check which one to use
            driver = nv.selectDriver()
            if (self.has_key(driver) and not
                (self[driver].markedInstall or self[driver].markedUpgrade)):
                self[driver].markInstall()
                logging.info("installing %s as suggested by NvidiaDetector" % driver)
                return True
        except Exception, e:
            logging.error("NvidiaDetection returned a error: %s" % e)
        return False

    def checkForKernel(self):
        """ check for the running kernel and try to ensure that we have
            an updated version
        """
        logging.debug("Kernel uname: '%s' " % self.uname)
        try:
            (version, build, flavour) = self.uname.split("-")
        except Exception, e:
            logging.warning("Can't parse kernel uname: '%s' (self compiled?)" % e)
            return False
        # now check if we have a SMP system
        dmesg = Popen(["dmesg"],stdout=PIPE).communicate()[0]
        if "WARNING: NR_CPUS limit" in dmesg:
            logging.debug("UP kernel on SMP system!?!")
            flavour = "generic"
        kernel = "linux-image-%s" % flavour
        if not self.has_key(kernel):
            logging.warning("No kernel: '%s'" % kernel)
            return False
        if not (self[kernel].isInstalled or self[kernel].markedInstall):
            logging.debug("Selecting new kernel '%s'" % kernel)
            self[kernel].markInstall()
        return True

    def checkPriority(self):
        # tuple of priorities we require to be installed 
        need = ('required', )
        # stuff that its ok not to have
        removeEssentialOk = self.config.getlist("Distro","RemoveEssentialOk")
        # check now
        for pkg in self:
            # WORKADOUND bug on the CD/python-apt #253255
            ver = pkg._depcache.GetCandidateVer(pkg._pkg)
            if ver and ver.Priority == 0:
                logging.error("Package %s has no priority set" % pkg.name)
                continue
            if (pkg.candidateDownloadable and
                not (pkg.isInstalled or pkg.markedInstall) and
                not pkg.name in removeEssentialOk and
                pkg.priority in need):
                self.markInstall(pkg.name, "priority in required set '%s' but not scheduled for install" % need)

    # FIXME: make this a decorator (just like the withResolverLog())
    def updateGUI(self, view, lock):
        while lock.locked():
            view.processEvents()
            time.sleep(0.01)

    @withResolverLog
    def distUpgrade(self, view, serverMode, partialUpgrade):
        self.serverMode = serverMode
        # keep the GUI alive
        lock = threading.Lock()
        lock.acquire()
        t = threading.Thread(target=self.updateGUI, args=(self.view, lock,))
        t.start()
        try:
            # upgrade (and make sure this way that the cache is ok)
            self.upgrade(True)

            # check that everything in priority required is installed
            self.checkPriority()

            # see if our KeepInstalled rules are honored
            self.keepInstalledRule()

            # and if we have some special rules
            self.postUpgradeRule()

            # check if we got a new kernel
            self.checkForKernel()

            # check for nvidia stuff
            self.checkForNvidia()

            # install missing meta-packages (if not in server upgrade mode)
            if not serverMode:
                if not self._installMetaPkgs(view):
                    raise SystemError, _("Can't upgrade required meta-packages")

            # see if it all makes sense
            if not self._verifyChanges():
                raise SystemError, _("A essential package would have to be removed")
        except SystemError, e:
            # this should go into a finally: line, see below for the 
            # rationale why it doesn't 
            lock.release()
            t.join()
            # FIXME: change the text to something more useful
            details =  _("An unresolvable problem occurred while "
                         "calculating the upgrade.\n\n "
                         "This can be caused by:\n"
                         " * Upgrading to a pre-release version of Ubuntu\n"
                         " * Running the current pre-release version of Ubuntu\n"
                         " * Unofficial software packages not provided by Ubuntu\n"
                         "\n")
            # we never have partialUpgrades (including removes) on a stable system
            # with only ubuntu sources so we do not recommend reporting a bug
            if partialUpgrade:
                details += _("This is most likely a transient problem, "
                             "please try again later.")
            else:
                details += _("If none of this applies, then please report this bug against "
                             "the 'update-manager' package and include the files in "
                             "/var/log/dist-upgrade/ in the bugreport.")
            # make the text available again
            self._stopAptResolverLog()
            view.error(_("Could not calculate the upgrade"), details)
            self._startAptResolverLog()            
            logging.error("Dist-upgrade failed: '%s'", e)
            return False
        # would be nice to be able to use finally: here, but we need
        # to run on python2.4 too 
        #finally:
        # wait for the gui-update thread to exit
        lock.release()
        t.join()
        
        # check the trust of the packages that are going to change
        untrusted = []
        for pkg in self.getChanges():
            if pkg.markedDelete:
                continue
            # special case because of a bug in pkg.candidateOrigin
            if pkg.markedDowngrade:
                for ver in pkg._pkg.VersionList:
                    # version is lower than installed one
                    if apt_pkg.VersionCompare(ver.VerStr, pkg.installedVersion) < 0:
                        for (verFileIter,index) in ver.FileList:
                            indexfile = pkg._list.FindIndex(verFileIter)
                            if indexfile and not indexfile.IsTrusted:
                                untrusted.append(pkg.name)
                                break
                continue
            origins = pkg.candidateOrigin
            trusted = False
            for origin in origins:
                #print origin
                trusted |= origin.trusted
            if not trusted:
                untrusted.append(pkg.name)
        # check if the user overwrote the unauthenticated warning
        try:
            b = self.config.getboolean("Distro","AllowUnauthenticated")
            if b:
                logging.warning("AllowUnauthenticated set!")
                return True
        except ConfigParser.NoOptionError, e:
            pass
        if len(untrusted) > 0:
            untrusted.sort()
            logging.error("Unauthenticated packages found: '%s'" % \
                          " ".join(untrusted))
            # FIXME: maybe ask a question here? instead of failing?
            view.error(_("Error authenticating some packages"),
                       _("It was not possible to authenticate some "
                         "packages. This may be a transient network problem. "
                         "You may want to try again later. See below for a "
                         "list of unauthenticated packages."),
                       "\n".join(untrusted))
            return False
        return True

    def _verifyChanges(self):
        """ this function tests if the current changes don't violate
            our constrains (blacklisted removals etc)
        """
        removeEssentialOk = self.config.getlist("Distro","RemoveEssentialOk")
        for pkg in self.getChanges():
            if pkg.markedDelete and self._inRemovalBlacklist(pkg.name):
                logging.debug("The package '%s' is marked for removal but it's in the removal blacklist", pkg.name)
                return False
            if pkg.markedDelete and (pkg._pkg.Essential == True and
                                     not pkg.name in removeEssentialOk):
                logging.debug("The package '%s' is marked for removal but it's a ESSENTIAL package", pkg.name)
                return False
        return True

    @property
    def installedTasks(self):
        tasks = {}
        installed_tasks = set()
        for pkg in self:
            if not pkg._lookupRecord():
                logging.debug("no PkgRecord found for '%s', skipping " % pkg.name)
                continue
            for line in pkg._records.Record.split("\n"):
                if line.startswith("Task:"):
                    for task in (line[len("Task:"):]).split(","):
                        task = task.strip()
                        if not tasks.has_key(task):
                            tasks[task] = set()
                        tasks[task].add(pkg.name)
        for task in tasks:
            installed = True
            for pkgname in tasks[task]:
                if not self[pkgname].isInstalled:
                    installed = False
                    break
            if installed:
                installed_tasks.add(task)
        return installed_tasks
            
    def installTasks(self, tasks):
        logging.debug("running installTasks")
        for pkg in self:
            if pkg.markedInstall or pkg.isInstalled:
                continue
            pkg._lookupRecord()
            if not (hasattr(pkg._records,"Record") and pkg._records.Record):
                logging.warning("can not find Record for '%s'" % pkg.name)
                continue
            for line in pkg._records.Record.split("\n"):
                if line.startswith("Task:"):
                    for task in (line[len("Task:"):]).split(","):
                        task = task.strip()
                        if task in tasks:
                            pkg.markInstall()
        return True
    
    def _installMetaPkgs(self, view):

        def metaPkgInstalled():
            """ 
            internal helper that checks if at least one meta-pkg is 
            installed or marked install
            """
            for key in metapkgs:
                if self.has_key(key):
                    pkg = self[key]
                    if pkg.isInstalled and pkg.markedDelete:
                        logging.debug("metapkg '%s' installed but markedDelete" % pkg.name)
                    if ((pkg.isInstalled and not pkg.markedDelete) 
                        or self[key].markedInstall):
                        return True
            return False

        # now check for ubuntu-desktop, kubuntu-desktop, edubuntu-desktop
        metapkgs = self.config.getlist("Distro","MetaPkgs")

        # we never go without ubuntu-base
        for pkg in self.config.getlist("Distro","BaseMetaPkgs"):
            self[pkg].markInstall()

        # every meta-pkg that is installed currently, will be marked
        # install (that result in a upgrade and removes a markDelete)
        for key in metapkgs:
            try:
                if self.has_key(key) and self[key].isInstalled:
                    logging.debug("Marking '%s' for upgrade" % key)
                    self[key].markUpgrade()
            except SystemError, e:
                logging.debug("Can't mark '%s' for upgrade (%s)" % (key,e))
                return False
        # check if we have a meta-pkg, if not, try to guess which one to pick
        if not metaPkgInstalled():
            logging.debug("none of the '%s' meta-pkgs installed" % metapkgs)
            for key in metapkgs:
                deps_found = True
                for pkg in self.config.getlist(key,"KeyDependencies"):
                    deps_found &= self.has_key(pkg) and self[pkg].isInstalled
                if deps_found:
                    logging.debug("guessing '%s' as missing meta-pkg" % key)
                    try:
                        self[key].markInstall()
                    except (SystemError, KeyError), e:
                        logging.error("failed to mark '%s' for install (%s)" % (key,e))
                        view.error(_("Can't install '%s'" % key),
                                   _("It was impossible to install a "
                                     "required package. Please report "
                                     "this as a bug. "))
                        return False
                    logging.debug("markedInstall: '%s' -> '%s'" % (key, self[key].markedInstall))
        # check if we actually found one
        if not metaPkgInstalled():
            # FIXME: provide a list
            view.error(_("Can't guess meta-package"),
                       _("Your system does not contain a "
                         "ubuntu-desktop, kubuntu-desktop, xubuntu-desktop or "
                         "edubuntu-desktop package and it was not "
                         "possible to detect which version of "
                        "Ubuntu you are running.\n "
                         "Please install one of the packages "
                         "above first using synaptic or "
                         "apt-get before proceeding."))
            return False
        return True

    def _inRemovalBlacklist(self, pkgname):
        for expr in self.removal_blacklist:
            if re.compile(expr).match(pkgname):
                return True
        return False

    @withResolverLog
    def tryMarkObsoleteForRemoval(self, pkgname, remove_candidates, foreign_pkgs):
        logging.debug("tryMarkObsoleteForRemoval(): %s" % pkgname)
        # sanity check, first see if it looks like a running kernel pkg
        if pkgname.endswith(self.uname):
            logging.debug("skipping running kernel pkg '%s'" % pkgname)
            return False
        if self._inRemovalBlacklist(pkgname):
            logging.debug("skipping '%s' (in removalBlacklist)" % pkgname)
            return False
        # if we don't have the package anyway, we are fine (this can
        # happen when forced_obsoletes are specified in the config file)
        if not self.has_key(pkgname):
            #logging.debug("package '%s' not in cache" % pkgname)
            return True
        # check if we want to purge 
        try:
            purge = self.config.getboolean("Distro","PurgeObsoletes")
        except ConfigParser.NoOptionError, e:
            purge = False

        # this is a delete candidate, only actually delete,
        # if it dosn't remove other packages depending on it
        # that are not obsolete as well
        actiongroup = apt_pkg.GetPkgActionGroup(self._depcache)
        self.create_snapshot()
        try:
            self[pkgname].markDelete(purge=purge)
            logging.debug("marking '%s' for removal" % pkgname)
            for pkg in self.getChanges():
                if (pkg.name not in remove_candidates or 
                      pkg.name in foreign_pkgs or 
                      self._inRemovalBlacklist(pkg.name)):
                    logging.debug("package '%s' has unwanted removals, skipping" % pkgname)
                    self.restore_snapshot()
                    return False
        except (SystemError,KeyError),e:
            logging.warning("_tryMarkObsoleteForRemoval failed for '%s' (%s: %s)" % (pkgname, repr(e), e))
            self.restore_snapshot()
            return False
        return True
    
    def _getObsoletesPkgs(self):
        " get all package names that are not downloadable "
        obsolete_pkgs =set()        
        for pkg in self:
            if pkg.isInstalled: 
                # check if any version is downloadable. we need to check
                # for older ones too, because there might be
                # cases where e.g. firefox in gutsy-updates is newer
                # than hardy
                if not self.anyVersionDownloadable(pkg):
                    obsolete_pkgs.add(pkg.name)
        return obsolete_pkgs

    def anyVersionDownloadable(self, pkg):
        " helper that checks if any of the version of pkg is downloadable "
        for ver in pkg._pkg.VersionList:
            if ver.Downloadable:
                return True
        return False

    def _getUnusedDependencies(self):
        " get all package names that are not downloadable "
        unused_dependencies =set()        
        for pkg in self:
            if pkg.isInstalled and self._depcache.IsGarbage(pkg._pkg):
                unused_dependencies.add(pkg.name)
        return unused_dependencies

    def _getForeignPkgs(self, allowed_origin, fromDist, toDist):
        """ get all packages that are installed from a foreign repo
            (and are actually downloadable)
        """
        foreign_pkgs=set()        
        for pkg in self:
            if pkg.isInstalled and self.downloadable(pkg):
                # assume it is foreign and see if it is from the 
                # official archive
                foreign=True
                for origin in pkg.candidateOrigin:
                    # FIXME: use some better metric here
                    if fromDist in origin.archive and \
                           origin.origin == allowed_origin:
                        foreign = False
                    if toDist in origin.archive and \
                           origin.origin == allowed_origin:
                        foreign = False
                if foreign:
                    foreign_pkgs.add(pkg.name)
        return foreign_pkgs

if __name__ == "__main__":
	import DistUpgradeConfigParser
        import DistUpgradeView
        print "foo"
	c = MyCache(DistUpgradeConfigParser.DistUpgradeConfig("."),
                    DistUpgradeView.DistUpgradeView())
        #c.checkForNvidia()
        print c._identifyObsoleteKernels()
        sys.exit()
	c.clear()
        c.create_snapshot()
        c.installedTasks
        c.installTasks(["ubuntu-desktop"])
        print c.getChanges()
        c.restore_snapshot()
