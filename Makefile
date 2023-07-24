PYTHON ?= python
NPM ?= npm
CLANG_FORMAT ?= clang-format

# Doc generation variables
UPSTREAM_GIT_REMOTE ?= origin
DOCSBUILDDIR := docs/_build
HTMLDIR := $(DOCSBUILDDIR)/html
PIP_INSTALL=$(PYTHON) -m pip install

reporters_path := ./src/memray/reporters
js_files := $(wildcard $(reporters_path)/assets/*.js)
generated_js_files := \
    $(reporters_path)/templates/assets/flamegraph_common.js \
    $(reporters_path)/templates/assets/flamegraph.js \
    $(reporters_path)/templates/assets/temporal_flamegraph.js \
    $(reporters_path)/templates/assets/table.js
cpp_files := $(shell find src/memray/_memray -name \*.cpp -o -name \*.h)

# Use this to inject arbitrary commands before the make targets (e.g. docker)
ENV :=

.PHONY: build
build: build-js build-ext  ## (default) Build package extensions and assets in-place

.PHONY: build-ext
build-ext:  ## Build package extensions in-place
	$(PYTHON) setup.py build_ext --inplace

$(reporters_path)/templates/assets/%.js: $(reporters_path)/assets/%.js
	$(NPM) install
	$(NPM) run-script build
	touch $(generated_js_files)

.PHONY: build-js
build-js: $(generated_js_files)  ## Build package assets in-place

.PHONY: dist
dist:  ## Generate Python distribution files
	$(PYTHON) -m build --wheel .

.PHONY: install-sdist
install-sdist: dist  ## Install from source distribution
	$(ENV) $(PIP_INSTALL) $(wildcard dist/*.tar.gz)

.PHONY: test-install
test-install: build-js ## Install with test dependencies
	$(ENV) CYTHON_TEST_MACROS=1 $(PIP_INSTALL) -e .[test]

.PHONY: dev-install
dev-install: build-js ## Install with dev dependencies
	$(ENV) CYTHON_TEST_MACROS=1 $(PIP_INSTALL) -e .[dev]

.PHONY: check
check: check-python check-js  ## Run all the tests

.PHONY: check-python  ## Run the Python tests
check-python:
	$(PYTHON) -m pytest -vvv --log-cli-level=info -s --color=yes $(PYTEST_ARGS) tests

.PHONY: check-js  ## Run the Javascript tests
check-js:
	$(NPM) install jest --save-dev
	$(NPM) run-script test

.PHONY: pycoverage
pycoverage:  ## Run the test suite, with Python code coverage
	$(PYTHON) -m pytest \
		-vvv \
		--log-cli-level=info \
		-s \
		--color=yes \
		--cov=memray \
		--cov=tests \
		--cov-config=pyproject.toml \
		--cov-report=term \
		--cov-fail-under=90 \
		--cov-append $(PYTEST_ARGS) \
		tests
	$(PYTHON) -m coverage lcov -i -o pycoverage.lcov
	genhtml *coverage.lcov  --branch-coverage --output-directory memray-coverage $(GENHTMLOPTS)

.PHONY: valgrind
valgrind:  ## Run valgrind, with the correct configuration
	PYTHONMALLOC=malloc valgrind \
		--suppressions=./valgrind.supp \
		--leak-check=full \
		--show-leak-kinds=definite \
		--error-exitcode=1 \
		--gen-suppressions=all \
		$(PYTHON) -m pytest tests -m valgrind -v

.PHONY: helgrind
helgrind:  ## Run helgrind, with the correct configuration
	PYTHONMALLOC=malloc valgrind  \
		--suppressions=./valgrind.supp \
		--tool=helgrind \
		--error-exitcode=1 \
		--gen-suppressions=all \
		$(PYTHON) -m pytest tests -m valgrind -v

.PHONY: ccoverage
ccoverage:  ## Run the test suite, with C++ code coverage
	$(MAKE) clean
	CFLAGS="$(CFLAGS) -O0 -pg --coverage" $(MAKE) build
	$(MAKE) check
	gcov -i build/*/src/memray/_memray -i -d
	lcov --capture --directory .  --output-file cppcoverage.lcov
	lcov --extract cppcoverage.lcov '*/src/memray/_memray/*' --output-file cppcoverage.lcov
	genhtml *coverage.lcov --branch-coverage --output-directory memray-coverage
	find . | grep -E '(\.gcda|\.gcno|\.gcov\.json\.gz)' | xargs rm -rf

.PHONY: format
format:  ## Autoformat all files
	$(PYTHON) -m pre_commit run --all-files

.PHONY: lint
lint:  ## Lint all files
	$(PYTHON) -m pre_commit run --all-files
	$(PYTHON) -m mypy -p memray --strict --ignore-missing-imports
	$(PYTHON) -m mypy tests --ignore-missing-imports

.PHONY: docs
docs:  ## Generate documentation
	$(MAKE) -C docs clean
	$(MAKE) -C docs html

.PHONY: docs-live
docs-live:  ## Serve documentation on localhost:8000, with live-reload
	$(MAKE) -C docs clean
	$(MAKE) -C docs livehtml

.PHONY: gh-pages
gh-pages:  ## Publish documentation on GitHub Pages
	$(eval GIT_REMOTE := $(shell git remote get-url $(UPSTREAM_GIT_REMOTE)))
	$(eval COMMIT_HASH := $(shell git rev-parse HEAD))
	touch $(HTMLDIR)/.nojekyll
	@echo -n "Documentation ready, push to $(GIT_REMOTE)? [Y/n] " && read ans && [ $${ans:-Y} == Y ]
	git init $(HTMLDIR)
	GIT_DIR=$(HTMLDIR)/.git GIT_WORK_TREE=$(HTMLDIR) git add -A
	GIT_DIR=$(HTMLDIR)/.git git commit -m "Documentation for commit $(COMMIT_HASH)"
	GIT_DIR=$(HTMLDIR)/.git git push $(GIT_REMOTE) HEAD:gh-pages --force
	rm -rf $(HTMLDIR)/.git


.PHONY: clean
clean:  ## Clean any built/generated artifacts
	find . | grep -E '(\.o|\.gcda|\.gcno|\.gcov\.json\.gz)' | xargs rm -rf
	find . | grep -E '(__pycache__|\.pyc|\.pyo)' | xargs rm -rf
	rm -rf build
	rm -f src/memray/_test_utils.*.so
	rm -f src/memray/_memray.*.so
	rm -f src/memray/_inject.*.so
	rm -f src/memray/_memray.cpp
	rm -rf memray-coverage
	rm -rf node_modules
	rm -f cppcoverage.lcov

.PHONY: bump_version
bump_version:
	bump2version $(RELEASE)
	$(eval NEW_VERSION := $(shell bump2version \
	                                --allow-dirty \
	                                --dry-run \
	                                --list $(RELEASE) \
	                                | tail -1 \
	                                | sed s,"^.*=",,))
	git commit --amend --no-edit

.PHONY: gen_news
gen_news:
	$(eval CURRENT_VERSION := $(shell bump2version \
	                            --allow-dirty \
	                            --dry-run \
	                            --list $(RELEASE) \
	                            | grep current_version \
	                            | sed s,"^.*=",,))
	$(PYEXEC) towncrier build --version $(CURRENT_VERSION) --name memray
	git commit --amend --no-edit

.PHONY: release-patch
release-patch: RELEASE=patch
release-patch: bump_version gen_news  ## Prepare patch version release

.PHONY: release-minor
release-minor: RELEASE=minor
release-minor: bump_version gen_news  ## Prepare minor version release

.PHONY: release-major
release-major: RELEASE=major
release-major: bump_version gen_news ## Prepare major version release

.PHONY: benchmark
benchmark:  ## Benchmark the head of current branch
	$(PYTHON) -m asv run
	$(PYTHON) -m asv publish

.PHONY: benchmark_new
benchmark_new:  ## Benchmark all commits since the latest benchmarked on this machine
	$(PYTHON) -m asv run NEW
	$(PYTHON) -m asv publish

.PHONY: help
help:  ## Print this message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'
