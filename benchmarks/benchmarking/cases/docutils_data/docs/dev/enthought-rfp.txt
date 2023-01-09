==================================
 Enthought API Documentation Tool
==================================
-----------------------
 Request for Proposals
-----------------------

:Author: Janet Swisher, Senior Technical Writer
:Organization: `Enthought, Inc. <http://www.enthought.com>`_
:Copyright: 2004 by Enthought, Inc.
:License: `Enthought License`_ (BSD Style)

.. _Enthought License: https://docutils.sourceforge.io/licenses/enthought.txt

The following is excerpted from the full RFP, and is published here
with permission from `Enthought, Inc.`_  See the `Plan for Enthought
API Documentation Tool`__.

__ enthought-plan.html

.. contents::
.. sectnum::


Requirements
============

The documentation tool will address the following high-level goals:


Documentation Extraction
------------------------

1. Documentation will be generated directly from Python source code,
   drawing from the code structure, docstrings, and possibly other
   comments.

2. The tool will extract logical constructs as appropriate, minimizing
   the need for comments that are redundant with the code structure.
   The output should reflect both documented and undocumented
   elements.


Source Format
-------------

1. The docstrings will be formatted in as terse syntax as possible.
   Required tags, syntax, and white space should be minimized.

2. The tool must support the use of Traits.  Special comment syntax
   for Traits may be necessary.  Information about the Traits package
   is available at http://code.enthought.com/traits/.  In the
   following example, each trait definition is prefaced by a plain
   comment::

       __traits__ = {

       # The current selection within the frame.
       'selection' : Trait([], TraitInstance(list)),

       # The frame has been activated or deactivated.
       'activated' : TraitEvent(),

       'closing' : TraitEvent(),

       # The frame is closed.
       'closed' : TraitEvent(),
       }

3. Support for ReStructuredText (ReST) format is desirable, because
   much of the existing docstrings uses ReST.  However, the complete
   ReST specification need not be supported, if a subset can achieve
   the project goals.  If the tool does not support ReST, the
   contractor should also provide a tool or path to convert existing
   docstrings.


Output Format
-------------

1. Documentation will be output as a navigable suite of HTML
   files.

2. The style of the HTML files will be customizable by a cascading
   style sheet and/or a customizable template.

3. Page elements such as headers and footer should be customizable, to
   support differing requirements from one documentation project to
   the next.


Output Structure and Navigation
-------------------------------

1. The navigation scheme for the HTML files should not rely on frames,
   and should harmonize with conversion to Microsoft HTML Help (.chm)
   format.

2. The output should be structured to make navigable the architecture
   of the Python code.  Packages, modules, classes, traits, and
   functions should be presented in clear, logical hierarchies.
   Diagrams or trees for inheritance, collaboration, sub-packaging,
   etc. are desirable but not required.

3. The output must include indexes that provide a comprehensive view
   of all packages, modules, and classes.  These indexes will provide
   readers with a clear and exhaustive view of the code base.  These
   indexes should be presented in a way that is easily accessible and
   allows easy navigation.

4. Cross-references to other documented elements will be used
   throughout the documentation, to enable the reader to move quickly
   relevant information.  For example, where type information for an
   element is available, the type definition should be
   cross-referenced.

5. The HTML suite should provide consistent navigation back to the
   home page, which will include the following information:

   * Bibliographic information

     - Author
     - Copyright
     - Release date
     - Version number

   * Abstract

   * References

     - Links to related internal docs (i.e., other docs for the same
       product)

     - Links to related external docs (e.g., supporting development
       docs, Python support docs, docs for included packages)

   It should be possible to specify similar information at the top
   level of each package, so that packages can be included as
   appropriate for a given application.


License
=======

Enthought intends to release the software under an open-source
("BSD-style") license.
