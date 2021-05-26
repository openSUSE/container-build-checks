.ONESHELL:
.SHELLFLAGS = -ec

TESTFILES = $(wildcard tests/*/Dockerfile)

all: container-build-checks.py

install: container-build-checks.py
	install -Dm0755 container-build-checks.py $(DESTDIR)/usr/lib/build/post-build-checks/container-build-checks

# Some test containers depend on other test containers. Make sure those are built first.
tests/proper-derived/built: tests/proper-base/built

tests/%/built: tests/%/Dockerfile
	@dir=$$(dirname $@)
	pushd $$dir >/dev/null
	testname=$$(basename $$dir)
	echo Building $$testname
	# Build the container
	podman build --squash -t "c-b-c-tests/$$testname" --build-arg DISTURL="obs://container:build:checks/$$testname" .
	podman save "c-b-c-tests/$$testname" > $$testname.tar
	popd >/dev/null
	touch $@

tests/%/tested: tests/%/built | all
	@dir=$$(dirname $@)
	testname=$$(basename $$dir)	
	export CBC_CONFIG_DIR=$$PWD/tests
	pushd $$dir >/dev/null
	echo "Testing $$testname"
	ret=0
	../../container-build-checks.py &>checks.new || ret=$$?
	echo "Exited with $$ret" >>checks.new
	popd >/dev/null
	[ -e $${dir}/checks.out ] || >$${dir}/checks.out
	diff -u $${dir}/checks.{out,new}

tests/%/regen: tests/%/built | all
	@dir=$$(dirname $@)
	testname=$$(basename $$dir)	
	export CBC_CONFIG_DIR=$$PWD/tests
	pushd $$dir >/dev/null
	echo "Testing $$testname (regen)"
	ret=0
	../../container-build-checks.py &>checks.out || ret=$$?
	echo "Exited with $$ret" >>checks.out
	popd >/dev/null

lint: container-build-checks.py
	flake8 $^ --max-line-length=120

clean:
	rm -f tests/*/{built,*.tar,checks.new}

test: $(subst /Dockerfile,/tested,$(TESTFILES))
test-regen: $(subst /Dockerfile,/regen,$(TESTFILES))

.PRECIOUS: $(subst /Dockerfile,/built,$(TESTFILES))
.PHONY: clean install test

# For some reason, marking /tested as PHONY makes it a noop???
#.PHONY: clean install test $(subst /Dockerfile,/tested,$(TESTFILES))
