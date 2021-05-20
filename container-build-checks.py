#!/usr/bin/python3
# SPDX-FileCopyrightText: 2021 SUSE LLC
# SPDX-License-Identifier: GPL-2.0-or-later

import configparser
import glob
import os
import sys
import tarfile

# Counters shown at the end
hints=0
warnings=0
errors=0

def hint(msg):
	global hints
	print("Hint: %s" % msg)
	hints+=1

def warn(msg):
	global warnings
	print("Warning: %s" % msg)
	warnings+=1

def error(msg):
	global errors
	print("Error: %s" % msg)
	errors+=1

# Load the configuration
configdir=os.environ.get("CBC_CONFIG_DIR", "/usr/share/container-build-checks/")
config=configparser.ConfigParser()
config.read_dict({"General": {"FatalWarnings": False, "Vendor": ""}})
config.read(sorted(glob.iglob(glob.escape(configdir) + "/*.conf")))

if not config["General"]["Vendor"]:
	warn("No Vendor defined in the configuration")

def containerinfos():
	"""Return a list of .containerinfo files to check."""
	if "BUILD_ROOT" not in os.environ:
		# Not running in an OBS build container
		return glob.glob("*.containerinfo")

	# Running in an OBS build container
	buildroot=os.environ["BUILD_ROOT"]
	topdir="/usr/src/packages"
	if os.path.isdir(buildroot + "/.build.packages"):
		topdir="/.build.packages"
	if os.path.islink(buildroot + "/.build.packages"):
		topdir="/" + os.readlink(buildroot + "/.build.packages")

	return glob.glob(f"{buildroot}{topdir}/DOCKER/*.containerinfo") + \
	       glob.glob(f"{buildroot}{topdir}/KIWI/*.containerinfo")

# Do checks
for containerinfo in containerinfos():
	print(f"Looking at {containerinfo}")
	# TODO!

# Checking done, show a summary and exit
ret=0
print(f"container-build-checks done. Hints: {hints} Warnings: {warnings} Errors: {errors}")
if warnings > 0:
	if config["General"].getboolean("FatalWarnings"):
		print("Treating warnings as fatal due to project configuration.")
		ret=1
	else:
		print("Warnings found, but those are only fatal in certain projects.")

if errors > 0:
	print("Fatal errors found.")
	ret=1

sys.exit(ret)
