# Minimal makefile for Sphinx documentation
#

SPHINXAUTOBUILD = sphinx-autobuild

# You can set these variables from the command line.
SPHINXOPTS    = -n -W --keep-going
SPHINXBUILD   = sphinx-build
SPHINXPROJ    = memray
SOURCEDIR     = .
BUILDDIR      = _build

# Internal variables.
PAPEROPT_a4     = -D latex_paper_size=a4
PAPEROPT_letter = -D latex_paper_size=letter
ALLSPHINXOPTS   = -d $(BUILDDIR)/doctrees $(PAPEROPT_$(PAPER)) $(SPHINXOPTS) .

.PHONY: clean
clean:
	rm -rf $(BUILDDIR)/*

.PHONY: html
html:
	$(SPHINXBUILD) -W -b html $(ALLSPHINXOPTS) $(BUILDDIR)/html
	@echo
	@echo "Build finished. The HTML pages are in $(BUILDDIR)/html."

.PHONY: man
man:
	$(SPHINXBUILD) -b man -D exclude_patterns= $(ALLSPHINXOPTS) $(BUILDDIR)/man
	@echo
	@echo "Build finished. The man pages are in $(BUILDDIR)/man."

.PHONY: livehtml
livehtml:
	$(SPHINXAUTOBUILD) -a $(ALLSPHINXOPTS) $(BUILDDIR)/html
