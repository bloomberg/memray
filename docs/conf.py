"""Sphinx configuration file for memray's documentation."""

# -- General configuration ------------------------------------------------------------

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

# -- Options for smartquotes ----------------------------------------------------------

# Disable the conversion of dashes so that long options like "--find-links" won't
# render as "-find-links" if included in the text.The default of "qDe" converts normal
# quote characters ('"' and "'"), en and em dashes ("--" and "---"), and ellipses "..."
smartquotes_action = "qe"
