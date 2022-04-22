PYTHON ?= python
NPM ?= npm
CLANG_FORMAT ?= clang-format
PRETTIER ?= prettier --no-editorconfig

# Doc generation variables
UPSTREAM_GIT_REMOTE ?= origin
DOCSBUILDDIR := docs/_build
HTMLDIR := $(DOCSBUILDDIR)/html
PKG_CONFIG_PATH ?= /opt/bb/lib64/pkgconfig
PIP_INSTALL=PKG_CONFIG_PATH="$(PKG_CONFIG_PATH)" $(PYTHON) -m pip install

reporters_path := ./src/memray/reporters
js_files := $(wildcard $(reporters_path)/assets/*.js)
generated_js_files := \
    $(reporters_path)/templates/assets/flamegraph.js \
    $(reporters_path)/templates/assets/table.js
css_files := 'src/**/*.css'
markdown_files := $(shell find . -name \*.md -not -path '*/\.*' -not -path './src/vendor/*')
cpp_files := $(shell find src/memray/_memray -name \*.cpp -o -name \*.h)
python_files := $(shell find . -name \*.py -not -path '*/\.*')
cython_files := $(shell find src -name \*.pyx -or -name \*.pxd -not -path '*/\.*')
type_files := $(shell find src -name \*.pyi -not -path '*/\.*')

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
		--cov-config=tox.ini \
		--cov-report=term \
		--cov-fail-under=80 \
		--cov-append $(PYTEST_ARGS) \
		tests

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
	lcov --capture --directory .  --output-file memray.info
	lcov --extract memray.info '*/src/memray/*' --output-file memray.info
	genhtml memray.info --output-directory memray-coverage
	find . | grep -E '(\.gcda|\.gcno|\.gcov\.json\.gz)' | xargs rm -rf

.PHONY: format-python
format-python:  ## Autoformat Python files
	$(PYTHON) -m isort $(python_files) $(cython_files) $(type_files)
	$(PYTHON) -m black $(python_files)
	$(PYTHON) -m black $(type_files)

.PHONY: format-markdown
format-markdown:  ## Autoformat markdown files
	$(PRETTIER) --write $(markdown_files)

.PHONY: format-assets
format-assets:  ## Autoformat CSS and JS files
	$(PRETTIER) --write $(js_files) $(css_files)

.PHONY: format
format: format-python format-markdown format-assets  ## Autoformat all files
	$(CLANG_FORMAT) -i $(cpp_files)

.PHONY: lint-python
lint-python:  ## Lint Python files
	$(PYTHON) -m isort --check $(python_files) $(cython_files) $(type_files)
	$(PYTHON) -m flake8 $(python_files)
	$(PYTHON) -m black --check $(python_files)
	$(PYTHON) -m black --check $(type_files)
	$(PYTHON) -m mypy -p memray --strict --ignore-missing-imports
	$(PYTHON) -m mypy tests --ignore-missing-imports

.PHONY: lint-markdown
lint-markdown:  ## Lint markdown files
	$(PRETTIER) --check $(markdown_files)

.PHONY: lint-assets
lint-assets:  ## Lint CSS and JS files
	$(PRETTIER) --check $(js_files) $(css_files)

.PHONY: lint
lint: lint-python lint-markdown lint-assets  ## Lint all files
	$(CLANG_FORMAT) --Werror --dry-run $(cpp_files)
	$(PYTHON) -m check_manifest

.PHONY: docs
docs:  ## Generate documentation
	$(MAKE) -C docs clean
	$(MAKE) -C docs html

.PHONY: docs-live
docs-live:  ## Serve documentation on localhost:8000, with live-reload
	$(MAKE) -C docs clean
	$(MAKE) -C docs livehtml

.PHONY: gh-pages
gh-pages:  ## Publish documentation on BBGitHub Pages
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
	find . | grep -E '(\.o|\.so|\.gcda|\.gcno|\.gcov\.json\.gz)' | xargs rm -rf
	find . | grep -E '(__pycache__|\.pyc|\.pyo)' | xargs rm -rf
	rm -f src/memray/_memray.cpp
	rm -f memray.info
	rm -rf memray-coverage
	rm -rf node_modules

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
