.ONESHELL:
.SHELLFLAGS = -ec

TESTFILES = $(wildcard tests/*/Dockerfile)

all: container-build-checks

install: container-build-checks
	install -Dm0755 container-build-checks $(DESTDIR)/usr/lib/build/post-build-checks/

tests/%/built: tests/%/Dockerfile
	@dir=$$(dirname $^)
	pushd $$dir
	testname=$$(basename $$dir)
	echo Building $$testname
	# Build the container
	podman build --squash -t "c-b-c-tests/$$testname" --build-arg DISTURL="obs://container:build:checks/$$testname" .
	podman save "c-b-c-tests/$$testname" > $$testname.tar
	# Create containerinfo
	tagsarr=
	for tag in $$(awk '/^#!BuildTag/ {$$1=""; print}' Dockerfile); do
		[ "$${tag%%:*}" = "$${tag}" ] && tag="$${tag}:latest"
		tagsarr="$$tagsarr\"$$tag\","
	done
	tagsarr="$${tagsarr%%,}"
	cat <<EOF >$$testname.containerinfo
	{
	"disturl": "obs://container:build:checks/$$testname",
	"file": "$$testname.tar",
	"repos": [{"url": "obsrepositories:/"}],
	"tags": [$$tagsarr],
	"release": "1.2",
	"version": "42.0"
	}
	EOF
	popd
	touch $@

tests/%/tested: tests/%/built | all
	@dir=$$(dirname $^)
	testname=$$(basename $$dir)	
	pushd $$dir
	echo "Testing $$testname"
	ret=0
	../../container-build-checks &>checks.new || ret=$$?
	echo "Exited with $$ret" >>checks.new
	diff -u checks.out checks.new
	popd

tests/%/regen: tests/%/built | all
	@dir=$$(dirname $^)
	testname=$$(basename $$dir)	
	pushd $$dir
	echo "Testing $$testname (regen)"
	ret=0
	../../container-build-checks &>checks.out || ret=$$?
	echo "Exited with $$ret" >>checks.out
	popd

clean:
	rm -f tests/*/{built,*.containerinfo,*.tar}

test: $(subst /Dockerfile,/tested,$(TESTFILES))
test-regen: $(subst /Dockerfile,/regen,$(TESTFILES))

.PRECIOUS: $(subst /Dockerfile,/built,$(TESTFILES))
.PHONY: clean install test

# For some reason, marking /tested as PHONY makes it a noop???
#.PHONY: clean install test $(subst /Dockerfile,/tested,$(TESTFILES))
