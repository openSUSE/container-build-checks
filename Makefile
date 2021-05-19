.ONESHELL:
.SHELLFLAGS = -ec

TESTFILES = $(wildcard tests/*/Dockerfile)

all: container-build-checks.py

install: container-build-checks.py
	install -Dm0755 container-build-checks.py $(DESTDIR)/usr/lib/build/post-build-checks/

tests/%/built: tests/%/Dockerfile
	@dir=$$(dirname $^)
	pushd $$dir
	testname=$$(basename $$dir)
	echo Building $$testname
	# Build the container
	podman build --squash -t "c-b-c-tests/$$testname" --build-arg DISTURL="obs://container:build:checks/$$testname" .
	podman save "c-b-c-tests/$$testname" > $$testname.tar
	popd
	touch $@

tests/%/tested: tests/%/built | all
	@dir=$$(dirname $^)
	testname=$$(basename $$dir)	
	export CBC_CONFIG_DIR=$PWD/tests
	pushd $$dir
	echo "Testing $$testname"
	ret=0
	../../container-build-checks.py &>checks.new || ret=$$?
	echo "Exited with $$ret" >>checks.new
	diff -u checks.out checks.new
	popd

tests/%/regen: tests/%/built | all
	@dir=$$(dirname $^)
	testname=$$(basename $$dir)	
	export CBC_CONFIG_DIR=$PWD/tests
	pushd $$dir
	echo "Testing $$testname (regen)"
	ret=0
	export CBC_CONFIG_DIR=$PWD
	../../container-build-checks.py &>checks.out || ret=$$?
	echo "Exited with $$ret" >>checks.out
	popd

clean:
	rm -f tests/*/{built,*.tar}

test: $(subst /Dockerfile,/tested,$(TESTFILES))
test-regen: $(subst /Dockerfile,/regen,$(TESTFILES))

.PRECIOUS: $(subst /Dockerfile,/built,$(TESTFILES))
.PHONY: clean install test

# For some reason, marking /tested as PHONY makes it a noop???
#.PHONY: clean install test $(subst /Dockerfile,/tested,$(TESTFILES))
