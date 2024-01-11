"""Sphinx configuration file for memray's documentation."""

import os

import memray.commands

# -- General configuration ------------------------------------------------------------

# The name of a reST role (builtin or Sphinx extension) to use as the default role,
# that is, for text marked up `like this`. This can be set to 'py:obj' to make `filter`
# a cross-reference to the Python function “filter”. The default is None,
# which doesn’t reassign the default role.
default_role = "py:obj"

extensions = [
    # first-party extensions
    "sphinx.ext.autodoc",
    "sphinx.ext.doctest",
    "sphinx.ext.extlinks",
    "sphinx.ext.githubpages",
    "sphinx.ext.intersphinx",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
    # third-party extensions
    "sphinxarg.ext",
]

# Don't build our manpage document when we're using the HTML builder.
# We override this setting when we build with the manpage builder.
exclude_patterns = ["manpage.rst"]

# General information about the project.
project = "memray"
author = "Pablo Galindo Salgado"

# -- Options for HTML -----------------------------------------------------------------

html_title = project
html_theme = "furo"
html_static_path = ["_static", "_static/flamegraphs"]
html_logo = "_static/images/logo.png"
html_theme_options = {
    "sidebar_hide_name": True,
}

templates_path = ["_templates"]
html_additional_pages = {
    "index": "index.html",
}
html_favicon = "favicon.ico"

# -- Options for man pages ------------------------------------------------------------
man_pages = [
    ("manpage", "memray", "Python memory profiler", "", 1),
]

# -- Options for smartquotes ----------------------------------------------------------

# Disable the conversion of dashes so that long options like "--find-links" won't
# render as "-find-links" if included in the text.The default of "qDe" converts normal
# quote characters ('"' and "'"), en and em dashes ("--" and "---"), and ellipses "..."
smartquotes_action = "qe"

# -- Options for intersphinx ----------------------------------------------------------

intersphinx_mapping = {
    "python": (
        "https://docs.python.org/3",
        (None,),
    ),
}

# -- Options for sphinx-argparse ------------------------------------------------------

# Limit the width of usage messages. argparse defaults to the terminal width,
# but we don't want different output depending on the terminal width where the
# docs were built.
os.environ["COLUMNS"] = "88"

# -- Improving man page generation ----------------------------------------------------

# The :manpage: mode of sphinx-argparse doesn't allow you to fully override the
# parser's description with a custom reStructuredText one as it should. Work
# around this by providing the first sentence of our desired description as the
# parser's description, and then letting the argparse role append the rest of
# the intended description. This description doesn't go into the HTML docs.
memray.commands._DESCRIPTION = "Memray is a memory profiler for Python applications."
