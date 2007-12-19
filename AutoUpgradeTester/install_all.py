#!/usr/bin/python

import os
import apt
import apt_pkg

def blacklisted(name):
   # we need to blacklist linux-image-* as it does not install
   # cleanly in the chroot (postinst failes)
   blacklist = [
      # file-overwrite problem with libc6-dev
      "libpthread-dev",
      # FUBAR (was removed in feisty)
      "glibc-doc-reference",
      # has a funny "can not be upgraded automatically" policy
      # see debian #368226
      "quagga",
      # the following packages try to access /lib/modules/`uname -r` and fail
      "vmware-player-kernel-",
      # not installable on a regular machine
      "ltsp-client",
      ]
   for b in blacklist:
	   if name.startswith(b):
		   return True
   return False

def clear(cache):
   cache._depcache.Init()

def reapply(cache, pkgnames):
   for name in pkgnames:
      cache[name].markInstall(False)

# ----------------------------------------------------------------

#apt_pkg.Config.Set("Dir::State::status","./empty")

print "install_all.py"
os.environ["DEBIAN_FRONTEND"] = "noninteractive"
os.environ["APT_LISTCHANGES_FRONTEND"] = "none"

cache = apt.Cache()

# dapper does not have this yet 
try:
   group = apt_pkg.GetPkgActionGroup(cache._depcache)
except:
   pass
#print [pkg.name for pkg in cache if pkg.isInstalled]

# see what gives us problems
troublemaker = set()
best = set()

# first install all of main, then the rest
for comp in ["main","universe"]:
   for pkg in cache:
      if pkg.candidateOrigin:
         for c in pkg.candidateOrigin:
            if comp == None or c.component == comp:
               current = set([p.name for p in cache if p.markedInstall])
               if not (pkg.isInstalled or blacklisted(pkg.name)):
                  try:
                     pkg.markInstall()
                  except SystemError, e:
                     print "Installing '%s' cause problems: %s" % (pkg.name, e)
                  new = set([p.name for p in cache if p.markedInstall])
                  #if not pkg.markedInstall or len(new) < len(current):
                  if not (pkg.isInstalled or pkg.markedInstall):
                     print "Can't install: %s" % pkg.name
                  if len(current-new) > 0:
                     troublemaker.add(pkg.name)
                     print "Installing '%s' caused removals %s" % (pkg.name, current - new)
                  # FIXME: instead of len() use score() and score packages
                  #        according to criteria like "in main", "priority" etc
                  if len(new) >= len(best):
                     best = new
                  else:
                     print "Installing '%s' reduced the set (%s < %s)" % (pkg.name, len(new), len(best))
                     clear(cache)
                     reapply(cache, best)

print len(troublemaker)
for pkg in ["ubuntu-desktop", "ubuntu-minimal", "ubuntu-standard"]:
    cache[pkg].markInstall()

# make sure we don't install blacklisted stuff
for pkg in cache:
	if blacklisted(pkg.name):
		pkg.markKeep()

print "We can install:"
print len([pkg.name for pkg in cache if pkg.markedInstall])
print "Download: "
pm = apt_pkg.GetPackageManager(cache._depcache)
fetcher = apt_pkg.GetAcquire()
pm.GetArchives(fetcher, cache._list, cache._records)
print apt_pkg.SizeToStr(fetcher.FetchNeeded)
print "Total space: ", apt_pkg.SizeToStr(cache._depcache.UsrSize)

# write out file with all pkgs
outf = "all_pkgs.cfg"
print "writing out file with the selected package names to '%s'" % outf
f = open(outf, "w")
f.write("\n".join([pkg.name for pkg in cache if pkg.markedInstall]))
f.close()

# go and install
res = False
current = 0
maxRetries = 5
while current < maxRetries:
    try:
        res = cache.commit(apt.progress.TextFetchProgress(),
                           apt.progress.InstallProgress())    
    except IOError, e:
        # fetch failed, will be retried
        current += 1
        print "Retrying to fetch: ", current
        continue
    except SystemError, e:
        print "Error installing packages! "
        print e
    print "Install result: ",res
    break
