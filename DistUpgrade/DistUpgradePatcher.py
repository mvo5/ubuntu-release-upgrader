# DistUpgradeEdPatcher.py 
#  
#  Copyright (c) 2011 Canonical
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

import string
import hashlib

class PatchError(Exception):
    """ Error during the patch process """
    pass

def patch(orig, edpatch, result_md5sum=None):
    """ python implementation of enough "ed" to apply ed-style
        patches. Note that this patches in memory so its *not*
        suitable for big files
    """

    # we only have two states, waiting for command or reading data
    (STATE_EXPECT_COMMAND,
     STATE_EXPECT_DATA) = range(2)

    # this is inefficient for big files
    orig_lines = open(orig).readlines()
    start = end = 0

    # we start in wait-for-commend state
    state = STATE_EXPECT_COMMAND
    for line in open(edpatch):
        if state == STATE_EXPECT_COMMAND:
            # in commands get rid of whitespace, 
            line = line.strip()
            command = line[-1]
            # read address
            (start_str, sep, end_str) = line[:-1].partition(",")
            # ed starts with 1 while python with 0
            start = int(start_str)
            start -= 1
            # if we don't have end, set it to the next line
            if end_str is "":
                end = start+1
            else:
                end = int(end_str)
            # interpret command
            if command == "c":
                del orig_lines[start:end]
                state = STATE_EXPECT_DATA
            elif command == "a":
                # not allowed to have a range in append
                state = STATE_EXPECT_DATA
                start += 1
            elif command == "d":
                del orig_lines[start:end]
            else:
                raise PatchError("unknown command: '%s'" % line)
        elif state == STATE_EXPECT_DATA:
            # this is the data end marker
            if line == ".\n":
                state = STATE_EXPECT_COMMAND
            else:
                # copy line verbatim and increase position
                orig_lines.insert(start, line)
                start += 1

    # done with the patching, (optional) verify and write result
    result = "".join(orig_lines)
    if result_md5sum:
        md5 = hashlib.md5()
        md5.update(result)
        if md5sum.hexdigest() != result_md5sum:
            raise PatchError("patch did not patch to the expected data")
    open(orig, "w").write(result)
    return True
