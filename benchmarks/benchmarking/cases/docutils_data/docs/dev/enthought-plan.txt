===========================================
 Plan for Enthought API Documentation Tool
===========================================

:Author: David Goodger
:Contact: docutils-develop@lists.sourceforge.net
:Date: $Date$
:Revision: $Revision$
:Copyright: 2004 by `Enthought, Inc. <http://www.enthought.com>`_
:License: `Enthought License`_ (BSD-style)

.. _Enthought License: https://docutils.sourceforge.io/licenses/enthought.txt

This document should be read in conjunction with the `Enthought API
Documentation Tool RFP`__ prepared by Janet Swisher.

__ enthought-rfp.html

.. contents::
.. sectnum::


Introduction
============

In March 2004 at I met Eric Jones, president and CTO of `Enthought,
Inc.`_, at `PyCon 2004`_ in Washington DC.  He told me that Enthought
was using reStructuredText_ for source code documentation, but they
had some issues.  He asked if I'd be interested in doing some work on
a customized API documentation tool.  Shortly after PyCon, Janet
Swisher, Enthought's senior technical writer, contacted me to work out
details.  Some email, a trip to Austin in May, and plenty of Texas
hospitality later, we had a project.  This document will record the
details, milestones, and evolution of the project.

In a nutshell, Enthought is sponsoring the implementation of an open
source API documentation tool that meets their needs.  Fortuitously,
their needs coincide well with the "Python Source Reader" description
in `PEP 258`_.  In other words, Enthought is funding some significant
improvements to Docutils, improvements that were planned but never
implemented due to time and other constraints.  The implementation
will take place gradually over several months, on a part-time basis.

This is an ideal example of cooperation between a corporation and an
open-source project.  The corporation, the project, I personally, and
the community all benefit.  Enthought, whose commitment to open source
is also evidenced by their sponsorship of SciPy_, benefits by
obtaining a useful piece of software, much more quickly than would
have been possible without their support.  Docutils benefits directly
from the implementation of one of its core subsystems.  I benefit from
the funding, which allows me to justify the long hours to my wife and
family.  All the corporations, projects, and individuals that make up
the community will benefit from the end result, which will be great.

All that's left now is to actually do the work!

.. _PyCon 2004: http://pycon.org/dc2004/
.. _reStructuredText: https://docutils.sourceforge.io/rst.html
.. _SciPy: http://www.scipy.org/


Development Plan
================

1. Analyze prior art, most notably Epydoc_ and HappyDoc_, to see how
   they do what they do.  I have no desire to reinvent wheels
   unnecessarily.  I want to take the best ideas from each tool,
   combined with the outline in `PEP 258`_ (which will evolve), and
   build at least the foundation of the definitive Python
   auto-documentation tool.

   .. _Epydoc: http://epydoc.sourceforge.net/
   .. _HappyDoc: http://happydoc.sourceforge.net/
   .. _PEP 258:
      https://docutils.sourceforge.io/docs/peps/pep-0258.html#python-source-reader

2. Decide on a base platform.  The best way to achieve Enthought's
   goals in a reasonable time frame may be to extend Epydoc or
   HappyDoc.  Or it may be necessary to start fresh.

3. Extend the reStructuredText parser.  See `Proposed Changes to
   reStructuredText`_ below.

4. Depending on the base platform chosen, build or extend the
   docstring & doc comment extraction tool.  This may be the biggest
   part of the project, but I won't be able to break it down into
   details until more is known.


Repository
==========

If possible, all software and documentation files will be stored in
the Subversion repository of Docutils and/or the base project, which
are all publicly-available via anonymous pserver access.

The Docutils project is very open about granting Subversion write
access; so far, everyone who asked has been given access.  Any
Enthought staff member who would like Subversion write access will get
it.

If either Epydoc or HappyDoc is chosen as the base platform, I will
ask the project's administrator for CVS access for myself and any
Enthought staff member who wants it.  If sufficient access is not
granted -- although I doubt that there would be any problem -- we may
have to begin a fork, which could be hosted on SourceForge, on
Enthought's Subversion server, or anywhere else deemed appropriate.


Copyright & License
===================

Most existing Docutils files have been placed in the public domain, as
follows::

    :Copyright: This document has been placed in the public domain.

This is in conjunction with the "Public Domain Dedication" section of
COPYING.txt__.

__ https://docutils.sourceforge.io/COPYING.html

The code and documentation originating from Enthought funding will
have Enthought's copyright and license declaration.  While I will try
to keep Enthought-specific code and documentation separate from the
existing files, there will inevitably be cases where it makes the most
sense to extend existing files.

I propose the following:

1. New files related to this Enthought-funded work will be identified
   with the following field-list headers::

       :Copyright: 2004 by Enthought, Inc.
       :License: Enthought License (BSD Style)

   The license field text will be linked to the license file itself.

2. For significant or major changes to an existing file (more than 10%
   change), the headers shall change as follows (for example)::

       :Copyright: 2001-2004 by David Goodger
       :Copyright: 2004 by Enthought, Inc.
       :License: BSD-style

   If the Enthought-funded portion becomes greater than the previously
   existing portion, Enthought's copyright line will be shown first.

3. In cases of insignificant or minor changes to an existing file
   (less than 10% change), the public domain status shall remain
   unchanged.

A section describing all of this will be added to the Docutils
`COPYING`__ instructions file.

If another project is chosen as the base project, similar changes
would be made to their files, subject to negotiation.

__ https://docutils.sourceforge.io/COPYING.html


Proposed Changes to reStructuredText
====================================

Doc Comment Syntax
------------------

The "traits" construct is implemented as dictionaries, where
standalone strings would be Python syntax errors.  Therefore traits
require documentation in comments.  We also need a way to
differentiate between ordinary "internal" comments and documentation
comments (doc comments).

Javadoc uses the following syntax for doc comments::

    /**
     * The first line of a multi-line doc comment begins with a slash
     * and *two* asterisks.  The doc comment ends normally.
     */

Python doesn't have multi-line comments; only single-line.  A similar
convention in Python might look like this::

    ##
    # The first line of a doc comment begins with *two* hash marks.
    # The doc comment ends with the first non-comment line.
    'data' : AnyValue,

    ## The double-hash-marks could occur on the first line of text,
    #  saving a line in the source.
    'data' : AnyValue,

How to indicate the end of the doc comment? ::

    ##
    # The first line of a doc comment begins with *two* hash marks.
    # The doc comment ends with the first non-comment line, or another
    # double-hash-mark.
    ##
    # This is an ordinary, internal, non-doc comment.
    'data' : AnyValue,

    ## First line of a doc comment, terse syntax.
    #  Second (and last) line.  Ends here: ##
    # This is an ordinary, internal, non-doc comment.
    'data' : AnyValue,

Or do we even need to worry about this case?  A simple blank line
could be used::

    ## First line of a doc comment, terse syntax.
    #  Second (and last) line.  Ends with a blank line.

    # This is an ordinary, internal, non-doc comment.
    'data' : AnyValue,

Other possibilities::

    #" Instead of double-hash-marks, we could use a hash mark and a
    #  quotation mark to begin the doc comment.
    'data' : AnyValue,

    ## We could require double-hash-marks on every line.  This has the
    ## added benefit of delimiting the *end* of the doc comment, as
    ## well as working well with line wrapping in Emacs
    ## ("fill-paragraph" command).
    # Ordinary non-doc comment.
    'data' : AnyValue,

    #" A hash mark and a quotation mark on each line looks funny, and
    #" it doesn't work well with line wrapping in Emacs.
    'data' : AnyValue,

These styles (repeated on each line) work well with line wrapping in
Emacs::

    ##  #>  #|  #-  #%  #!  #*

These styles do *not* work well with line wrapping in Emacs::

    #"  #'  #:  #)  #.  #/  #@  #$  #^  #=  #+  #_  #~

The style of doc comment indicator used could be a runtime, global
and/or per-module setting.  That may add more complexity than it's
worth though.


Recommendation
``````````````

I recommend adopting "#*" on every line::

    # This is an ordinary non-doc comment.

    #* This is a documentation comment, with an asterisk after the
    #* hash marks on every line.
    'data' : AnyValue,

I initially recommended adopting double-hash-marks::

    # This is an ordinary non-doc comment.

    ## This is a documentation comment, with double-hash-marks on
    ## every line.
    'data' : AnyValue,

But Janet Swisher rightly pointed out that this could collide with
ordinary comments that are then block-commented.  This applies to
double-hash-marks on the first line only as well.  So they're out.

On the other hand, the JavaDoc-comment style ("##" on the first line
only, "#" after that) is used in Fredrik Lundh's PythonDoc_.  It may
be worthwhile to conform to this syntax, reinforcing it as a standard.
PythonDoc does not support terse doc comments (text after "##" on the
first line).

.. _PythonDoc: http://effbot.org/zone/pythondoc.htm


Update
``````

Enthought's Traits system has switched to a metaclass base, and traits
are now defined via ordinary attributes.  Therefore doc comments are
no longer absolutely necessary; attribute docstrings will suffice.
Doc comments may still be desirable though, since they allow
documentation to precede the thing being documented.


Docstring Density & Whitespace Minimization
-------------------------------------------

One problem with extensively documented classes & functions, is that
there is a lot of screen space wasted on whitespace.  Here's some
current Enthought code (from lib/cp/fluids/gassmann.py)::

    def max_gas(temperature, pressure, api, specific_gravity=.56):
        """
        Computes the maximum dissolved gas in oil using Batzle and
        Wang (1992).

        Parameters
        ----------
        temperature : sequence
            Temperature in degrees Celsius
        pressure : sequence
            Pressure in MPa
        api : sequence
            Stock tank oil API
        specific_gravity : sequence
            Specific gravity of gas at STP, default is .56

        Returns
        -------
        max_gor : sequence
            Maximum dissolved gas in liters/liter

        Description
        -----------
        This estimate is based on equations given by Mavko, Mukerji,
        and Dvorkin, (1998, pp. 218-219, or 2003, p. 236) obtained
        originally from Batzle and Wang (1992).
        """
        code...

The docstring is 24 lines long.

Rather than using subsections, field lists (which exist now) can save
6 lines::

    def max_gas(temperature, pressure, api, specific_gravity=.56):
        """
        Computes the maximum dissolved gas in oil using Batzle and
        Wang (1992).

        :Parameters:
            temperature : sequence
                Temperature in degrees Celsius
            pressure : sequence
                Pressure in MPa
            api : sequence
                Stock tank oil API
            specific_gravity : sequence
                Specific gravity of gas at STP, default is .56
        :Returns:
            max_gor : sequence
                Maximum dissolved gas in liters/liter
        :Description: This estimate is based on equations given by
            Mavko, Mukerji, and Dvorkin, (1998, pp. 218-219, or 2003,
            p. 236) obtained originally from Batzle and Wang (1992).
        """
        code...

As with the "Description" field above, field bodies may begin on the
same line as the field name, which also saves space.

The output for field lists is typically a table structure.  For
example:

    :Parameters:
        temperature : sequence
            Temperature in degrees Celsius
        pressure : sequence
            Pressure in MPa
        api : sequence
            Stock tank oil API
        specific_gravity : sequence
            Specific gravity of gas at STP, default is .56
    :Returns:
        max_gor : sequence
            Maximum dissolved gas in liters/liter
    :Description:
        This estimate is based on equations given by Mavko,
        Mukerji, and Dvorkin, (1998, pp. 218-219, or 2003, p. 236)
        obtained originally from Batzle and Wang (1992).

But the definition lists describing the parameters and return values
are still wasteful of space.  There are a lot of half-filled lines.

Definition lists are currently defined as::

    term : classifier
        definition

Where the classifier part is optional.  Ideas for improvements:

1. We could allow multiple classifiers::

       term : classifier one : two : three ...
           definition

2. We could allow the definition on the same line as the term, using
   some embedded/inline markup:

   * "--" could be used, but only in limited and well-known contexts::

         term -- definition

     This is the syntax used by StructuredText (one of
     reStructuredText's predecessors).  It was not adopted for
     reStructuredText because it is ambiguous -- people often use "--"
     in their text, as I just did.  But given a constrained context,
     the ambiguity would be acceptable (or would it?).  That context
     would be: in docstrings, within a field list, perhaps only with
     certain well-defined field names (parameters, returns).

   * The "constrained context" above isn't really enough to make the
     ambiguity acceptable.  Instead, a slightly more verbose but far
     less ambiguous syntax is possible::

         term === definition

     This syntax has advantages.  Equals signs lend themselves to the
     connotation of "definition".  And whereas one or two equals signs
     are commonly used in program code, three equals signs in a row
     have no conflicting meanings that I know of.  (Update: there
     *are* uses out there.)

   The problem with this approach is that using inline markup for
   structure is inherently ambiguous in reStructuredText.  For
   example, writing *about* definition lists would be difficult::

       ``term === definition`` is an example of a compact definition list item

   The parser checks for structural markup before it does inline
   markup processing.  But the "===" should be protected by its inline
   literal context.

3. We could allow the definition on the same line as the term, using
   structural markup.  A variation on bullet lists would work well::

       : term :: definition
       : another term :: and a definition that
         wraps across lines

   Some ambiguity remains::

       : term ``containing :: double colons`` :: definition

   But the likelihood of such cases is negligible, and they can be
   covered in the documentation.

   Other possibilities for the definition delimiter include::

       : term : classifier -- definition
       : term : classifier --- definition
       : term : classifier : : definition
       : term : classifier === definition

The third idea currently has the best chance of being adopted and
implemented.


Recommendation
``````````````

Combining these ideas, the function definition becomes::

    def max_gas(temperature, pressure, api, specific_gravity=.56):
        """
        Computes the maximum dissolved gas in oil using Batzle and
        Wang (1992).

        :Parameters:
            : temperature : sequence :: Temperature in degrees Celsius
            : pressure : sequence :: Pressure in MPa
            : api : sequence :: Stock tank oil API
            : specific_gravity : sequence :: Specific gravity of gas at
              STP, default is .56
        :Returns:
            : max_gor : sequence :: Maximum dissolved gas in liters/liter
        :Description: This estimate is based on equations given by
            Mavko, Mukerji, and Dvorkin, (1998, pp. 218-219, or 2003,
            p. 236) obtained originally from Batzle and Wang (1992).
        """
        code...

The docstring is reduced to 14 lines, from the original 24.  For
longer docstrings with many parameters and return values, the
difference would be more significant.
