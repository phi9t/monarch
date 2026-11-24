# Minimal makefile for Sphinx documentation
#

# You can set these variables from the command line, and also
# from the environment for the first two.
SPHINXOPTS    ?=
SPHINXBUILD   ?= sphinx-build
SOURCEDIR     = source
BUILDDIR      = build

.DEFAULT_GOAL := help

# The docs build runs Sphinx and deletes generated output, so it must run inside
# a controlled execution domain. This private guard is not overridable from the
# command line, and every real target depends on it, so an overridden
# SPHINXBUILD or a clean cannot run outside the rootfs.
.PHONY: _rootfs-guard
_rootfs-guard:
	@../scripts/rootfs/execution_contract.sh require-controlled

help: _rootfs-guard
	@$(SPHINXBUILD) -M help "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

# Build HTML documentation, including the books directory. Sphinx Gallery owns
# example generation from conf.py; this target does not run Cargo doc or mdBook.
html: _rootfs-guard
	@echo "Building HTML documentation with books directory..."
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

.PHONY: help Makefile html clean

# Catch-all target: route all unknown targets to Sphinx using the new
# "make mode" option.  $(O) is meant as a shortcut for $(SPHINXOPTS).
%: Makefile _rootfs-guard
	@$(SPHINXBUILD) -M $@ "$(SOURCEDIR)" "$(BUILDDIR)" $(SPHINXOPTS) $(O)

clean: _rootfs-guard
	@echo "Cleaning up build and generated directories..."
	@rm -rf "$(BUILDDIR)"
	@rm -rf "$(SOURCEDIR)/generated"
