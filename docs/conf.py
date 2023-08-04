"""Sphinx configuration file for memray's documentation."""

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
