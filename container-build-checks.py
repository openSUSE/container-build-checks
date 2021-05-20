#!/usr/bin/python3
# SPDX-FileCopyrightText: 2021 SUSE LLC
# SPDX-License-Identifier: GPL-2.0-or-later

import configparser
import glob
import json
import os
import sys
import tarfile

class LabelInfo:
	"""
	Information about a given label/oci annotation:
	prefix: Prefix used by the "most derived" provider of the label,
	        usually the OCI annotation if available.
	suffix: Suffix used by all providers of the label.
	mandatory: Whether this label has to be set by at least one layer.
	mandatory_derived: Whether this label has to be set by the top layer.
	"""
	def __init__(self, prefix, suffix, mandatory, mandatory_derived):
		self.prefix = prefix
		self.suffix = suffix
		self.mandatory = mandatory
		self.mandatory_derived = mandatory_derived

	def oci(self):
		return f"{self.prefix}.{self.suffix}"

LABEL_INFO=[
	LabelInfo("org.opencontainers", "image.title", True, False),
	LabelInfo("org.opencontainers", "image.description", True, True),
	LabelInfo("org.opencontainers", "image.version", True, True),
	LabelInfo("org.opencontainers", "image.created", True, True),
	LabelInfo("org.opencontainers", "image.vendor", True, False),
	LabelInfo("org.opencontainers", "image.url", True, False),
	LabelInfo("org.openbuildservice", "disturl", True, True),
	LabelInfo("org.opensuse", "reference", True, True),
	]

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

	return (glob.glob(f"{buildroot}{topdir}/DOCKER/*.containerinfo")
	        + glob.glob(f"{buildroot}{topdir}/KIWI/*.containerinfo"))

# Do checks
for containerinfo in containerinfos():
	print(f"Looking at {containerinfo}")
	with open(containerinfo, "rb") as cifile:
		ci_dict=json.load(cifile)

	# No manually defined repos which could escape the defined paths in e.g. openSUSE:Factory
	if ci_dict["repos"] != [{"url": "obsrepositories:/"}]:
		urls=", ".join([repo["url"] for repo in ci_dict["repos"]])
		warn(f"Using manually defined repositories ({urls}) in the image. Only obsrepositories:/ is allowed.")

	# Make sure tags are namespaced and one of them contains the release
	releasetagfound=False
	for tag in ci_dict["tags"]:
		print(f"Tag: {tag}")
		if "/" not in tag:
			warn(f"Tag {tag} is not namespaced (e.g. opensuse/foo)")
		if ci_dict["release"] in tag:
			releasetagfound=True

	print(f"Release: {ci_dict['release']}")

	if not releasetagfound:
		warn(f"None of the tags are unique to a specific build of the image.\nMake sure that at least one tag contains the release.")

	# Now open the tarball and look inside
	dir=os.path.dirname(os.path.realpath(containerinfo))
	with tarfile.open(f"{dir}/{ci_dict['file']}") as tar:
		manifest=json.load(tar.extractfile("manifest.json"))
		if len(manifest) != 1:
			raise Exception("Manifest doesn't have exactly one entry")

		imgconfig=json.load(tar.extractfile(manifest[0]["Config"]))

		# Check labels
		labels=imgconfig["config"]["Labels"]

		if ("org.openbuildservice.disturl" not in labels
		    or labels["org.openbuildservice.disturl"] != ci_dict["disturl"]):
			error("org.openbuildservice.disturl not set correctly, bug in OBS?")

		# Get the image specific label prefix by looking at the .reference
		labelprefix=None
		if "org.opensuse.reference" in labels:
			reference=labels["org.opensuse.reference"]
			reference_labels=[name for (name, value) in labels.items() if name != "org.opensuse.reference" and name.endswith(".reference") and value == reference]

			if len(reference_labels) == 0:
				warn(f"Could not find prefixed copy of the org.opensuse.reference label")
			elif len(reference_labels) > 1:
				warn(f"Unable to find which of those labels is the one corresponding to this image: f{reference_labels}")
			else:
				labelprefix=reference_labels[0][0:-len(".reference")]

		if not labelprefix:
			warn(f"Could not determine image specific label prefix, some checks will be skipped.")
		else:
			print(f"Detected image specific label prefix: f{labelprefix}")

		for labelinfo in LABEL_INFO:
			# Are all mandatory labels present?
			if labelinfo.mandatory and labelinfo.oci() not in labels:
				warn(f"Label {labelinfo.oci()} is not set by the image or any of its bases")
				continue

		# TODO: Finish label checks

		# TODO: Inspect content for broken symlinks, sparse files, size of /var/log etc.

	print()

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
