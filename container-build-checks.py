#!/usr/bin/python3
# SPDX-FileCopyrightText: 2021 SUSE LLC
# SPDX-License-Identifier: GPL-2.0-or-later

import configparser
import contextlib
import glob
import json
import os
import re
import sys
import tarfile

class Image:
	"""Information about the image to be tested."""
	def __init__(self, containerinfo, tarfile, config):
		self.containerinfo = containerinfo
		self.tarfile = tarfile
		self.config = config

@contextlib.contextmanager
def image_from_containerinfo(path):
	"""Create an Image instance for the .containerinfo file in path."""
	with open(path, "rb") as cifile:
		ci_dict=json.load(cifile)

	# Open the tarball and look inside
	dir=os.path.dirname(os.path.realpath(path))
	with tarfile.open(f"{dir}/{ci_dict['file']}") as tar:
		manifest=json.load(tar.extractfile("manifest.json"))
		if len(manifest) != 1:
			raise Exception("Manifest doesn't have exactly one entry")

		imgconfig=json.load(tar.extractfile(manifest[0]["Config"]))
		yield Image(ci_dict, tar, imgconfig)

class LabelInfo:
	"""
	Information about a given label/OCI annotation:
	prefix: Prefix used by the "most derived" provider of the label,
	        usually the OCI annotation if available.
	suffix: Suffix used by all providers of the label.
	mandatory: Whether this label has to be set by at least one layer.
	mandatory_derived: Whether this label has to be set by the top layer.
	verifier: A function 
	"""
	def __init__(self, prefix, suffix, mandatory=True, mandatory_derived=True, verifier=None):
		self.prefix = prefix
		self.suffix = suffix
		self.mandatory = mandatory
		self.mandatory_derived = mandatory_derived
		self.verifier = verifier

	def oci(self):
		return f"{self.prefix}.{self.suffix}"

def verify_disturl(image, result, value):
	if value != image.containerinfo["disturl"]:
		result.error("org.openbuildservice.disturl not set correctly, bug in OBS?")

# Split a reference (e.g. registry.opensuse.org/foo/bar:tag01) into (registry, repo, tag)
REFERENCE_RE=re.compile("([^/]+)/([^:]+):([^:]+)")

def verify_reference(image, result, value):
	reference=value
	reference_match=REFERENCE_RE.fullmatch(reference)
	# Verify org.opensuse.reference matches
	if reference_match is None:
		error(f"The value of the org.opensuse.reference label ({reference}) is invalid")
		return

	(registry, repo, tag) = reference_match.groups()
	if config["General"]["Registry"] and registry != config["General"]["Registry"]:
		result.warn(f"The org.opensuse.reference label ({reference}) does not refer to {config['General']['Registry']}")

		if f"{repo}:{tag}" not in image.containerinfo["tags"]:
			tags=", ".join(image.containerinfo["tags"])
			result.warn(f"The org.opensuse.reference label ({reference}) does not refer to an existing tag ({tags})")
		elif image.containerinfo["release"] not in tag:
			result.warn(f"The org.opensuse.reference label ({reference}) does not refer to a tag identifying a specific build")

LABEL_INFO=[
	LabelInfo("org.openbuildservice", "disturl", verifier=verify_disturl),
	LabelInfo("org.opencontainers.image", "title"),
	LabelInfo("org.opencontainers.image", "description"),
	LabelInfo("org.opencontainers.image", "version"),
	LabelInfo("org.opencontainers.image", "created"),
	LabelInfo("org.opencontainers.image", "vendor", mandatory_derived=False),
	LabelInfo("org.opencontainers.image", "url", mandatory_derived=False),
	LabelInfo("org.opensuse", "reference", verifier=verify_reference),
	]

class CheckResult:
	"""Class to track count of issues"""
	def __init__(self):
		self.hints=0
		self.warnings=0
		self.errors=0

	def hint(self, msg):
		print(f"Hint: {msg}")
		self.hints+=1

	def warn(self, msg):
		print(f"Warning: {msg}")
		self.warnings+=1

	def error(self, msg):
		print(f"Error: {msg}")
		self.errors+=1

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

def check_labels(image, result):
	labels = image.config.get("config", {}).get("Labels", {})

	# Treat this specially, it is usually not set manually
	if "org.openbuildservice.disturl" not in labels:
		result.error("org.openbuildservice.disturl not set correctly, bug in OBS?")

	# Get the image specific label prefix by looking at the .reference
	labelprefix=None
	if "org.opensuse.reference" in labels:
		reference=labels["org.opensuse.reference"]
		reference_labels=[name for (name, value) in labels.items() if name != "org.opensuse.reference" and name.endswith(".reference") and value == reference]

		if len(reference_labels) == 0:
			result.warn(f"Could not find prefixed copy of the org.opensuse.reference label")
		elif len(reference_labels) > 1:
			result.warn(f"Unable to find which of those labels is the one corresponding to this image: f{reference_labels}")
		else:
			labelprefix=reference_labels[0][0:-len(".reference")]

	if not labelprefix:
		result.warn(f"Could not determine image specific label prefix, some checks will be skipped.")
	else:
		print(f"Detected image specific label prefix: {labelprefix}")

	for labelinfo in LABEL_INFO:
		# Are all mandatory labels present?
		if labelinfo.mandatory and labelinfo.oci() not in labels:
			result.warn(f"Label {labelinfo.oci()} is not set by the image or any of its bases")
			continue

		if labelinfo.verifier:
			labelinfo.verifier(image, result, labels[labelinfo.oci()])

		# Check prefixed labels
		if labelprefix:
			if f"{labelprefix}.{labelinfo.suffix}" in labels:
				if labelinfo.oci() not in labels:
					result.warn(f"Label {labelprefix}.{labelinfo.suffix} set but not {labelinfo.oci()}")
				elif labels[labelinfo.oci()] != labels[f"{labelprefix}.{labelinfo.suffix}"]:
					result.warn(f"Label {labelprefix}.{labelinfo.suffix} not identical to {labelinfo.oci()}")
			elif labelinfo.mandatory_derived:
				result.warn(f"Labels {labelinfo.oci()} and {labelprefix}.{labelinfo.suffix} not specified by this image")

def check_image(image, result):
	"""Perform checks on the given image"""
	# No manually defined repos which could escape the defined paths in e.g. openSUSE:Factory
	if "repos" in image.containerinfo and image.containerinfo["repos"] != [{"url": "obsrepositories:/"}]:
		urls=", ".join([repo["url"] for repo in image.containerinfo["repos"]])
		result.warn(f"Using manually defined repositories ({urls}) in the image. Only obsrepositories:/ is allowed.")

	# Make sure tags are namespaced and one of them contains the release
	releasetagfound=False
	for tag in image.containerinfo["tags"]:
		print(f"Tag: {tag}")
		if "/" not in tag:
			result.warn(f"Tag {tag} is not namespaced (e.g. opensuse/foo)")
		if image.containerinfo["release"] in tag:
			releasetagfound=True

	print(f"Release: {image.containerinfo['release']}")

	if not releasetagfound:
		result.warn(f"None of the tags are unique to a specific build of the image.\nMake sure that at least one tag contains the release.")

	check_labels(image, result)

result=CheckResult()

# Load the configuration
configdir=os.environ.get("CBC_CONFIG_DIR", "/usr/share/container-build-checks/")
config=configparser.ConfigParser()
config.read_dict({"General": {"FatalWarnings": False, "Vendor": "", "Registry": ""}})
config.read(sorted(glob.iglob(glob.escape(configdir) + "/*.conf")))

if not config["General"]["Vendor"]:
	result.warn("No Vendor defined in the configuration")

if not config["General"]["Registry"]:
	result.hint("No Registry defined in the configuration")

# Do checks
for containerinfo in containerinfos():
	print(f"Looking at {containerinfo}")
	with image_from_containerinfo(containerinfo) as image:
		check_image(image, result)
		print()

# Checking done, show a summary and exit
ret=0
print(f"container-build-checks done. Hints: {result.hints} Warnings: {result.warnings} Errors: {result.errors}")
if result.warnings > 0:
	if config["General"].getboolean("FatalWarnings"):
		print("Treating warnings as fatal due to project configuration.")
		ret=1
	else:
		print("Warnings found, but those are only fatal in certain projects.")

if result.errors > 0:
	print("Fatal errors found.")
	ret=1

sys.exit(ret)
