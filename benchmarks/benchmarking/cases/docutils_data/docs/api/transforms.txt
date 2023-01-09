=====================
 Docutils Transforms
=====================

:Author: David Goodger
:Contact: docutils-develop@lists.sourceforge.net
:Revision: $Revision$
:Date: $Date$
:Copyright: This document has been placed in the public domain.


.. contents::

Transforms change the document tree in-place, add to the tree, or prune it.
Transforms resolve references and footnote numbers, process interpreted
text, and do other context-sensitive processing. Each transform is a
subclass of ``docutils.transforms.Transform``.

There are `transforms added by components`_, others (e.g.
``parts.Contents``) are added by the parser, if a corresponding directive is
found in the document.

To add a transform, components (objects inheriting from
Docutils.Component like Readers, Parsers, Writers, Input, Output) overwrite
the ``get_transforms()`` method of their base class. After the Reader has
finished processing, the Publisher calls
``Transformer.populate_from_components()`` with a list of components and all
transforms returned by the component's ``get_transforms()`` method are
stored in a `transformer object` attached to the document tree.


For more about transforms and the Transformer object, see also `PEP
258`_. (The ``default_transforms()`` attribute of component classes mentioned
there is deprecated. Use the ``get_transforms()`` method instead.)

.. _PEP 258: ../peps/pep-0258.html#transformer


Transforms Listed in Priority Order
===================================

Transform classes each have a default_priority attribute which is used by
the Transformer to apply transforms in order (low to high). The default
priority can be overridden when adding transforms to the Transformer object.


==============================  ============================  ========
Transform: module.Class         Added By                      Priority
==============================  ============================  ========
misc.class                      "class" (d/p)                 210

references.Substitutions        standalone (r), pep (r)       220

references.PropagateTargets     standalone (r), pep (r)       260

frontmatter.DocTitle            standalone (r)                320

frontmatter.DocInfo             standalone (r)                340

frontmatter.SectSubTitle        standalone (r)                350

peps.Headers                    pep (r)                       360

peps.Contents                   pep (r)                       380

universal.StripClasses...       Writer (w)                    420

references.AnonymousHyperlinks  standalone (r), pep (r)       440

references.IndirectHyperlinks   standalone (r), pep (r)       460

peps.TargetNotes                pep (r)                       520

references.TargetNotes          peps.TargetNotes (t/p)        0

misc.CallBack                   peps.TargetNotes (t/p)        1

references.TargetNotes          "target-notes" (d/p)          540

references.Footnotes            standalone (r), pep (r)       620

references.ExternalTargets      standalone (r), pep (r)       640

references.InternalTargets      standalone (r), pep (r)       660

parts.SectNum                   "sectnum" (d/p)               710

parts.Contents                  "contents" (d/p),             720
                                peps.Contents (t/p)

universal.StripComments         Reader (r)                    740

peps.PEPZero                    peps.Headers (t/p)            760

components.Filter               *not used*                    780

universal.Decorations           Reader (r)                    820

misc.Transitions                standalone (r), pep (r)       830

universal.ExposeInternals       Reader (r)                    840

references.DanglingReferences   standalone (r), pep (r)       850

universal.SmartQuotes           Parser                        855

universal.Messages              Writer (w)                    860

universal.FilterMessages        Writer (w)                    870

universal.TestMessages          DocutilsTestSupport           880

writer_aux.Compound             *not used, to be removed*     910

writer_aux.Admonitions          html4css1 (w),                920
                                latex2e (w)

misc.CallBack                   n/a                           990
==============================  ============================  ========

Key:

* (r): Reader
* (w): Writer
* (d): Directive
* (t): Transform
* (/p): Via a "pending" node


Transform Priority Range Categories
===================================

====  ====  ================================================
 Priority
----------  ------------------------------------------------
From   To   Category
====  ====  ================================================
   0    99  immediate execution (added by another transform)
 100   199  very early (non-standard)
 200   299  very early
 300   399  early
 400   699  main
 700   799  late
 800   899  very late
 900   999  very late (non-standard)
====  ====  ================================================


Transforms added by components
===============================


readers.Reader:
  | universal.Decorations,
  | universal.ExposeInternals,
  | universal.StripComments

readers.ReReader:
  None

readers.standalone.Reader:
  | references.Substitutions,
  | references.PropagateTargets,
  | frontmatter.DocTitle,
  | frontmatter.SectionSubTitle,
  | frontmatter.DocInfo,
  | references.AnonymousHyperlinks,
  | references.IndirectHyperlinks,
  | references.Footnotes,
  | references.ExternalTargets,
  | references.InternalTargets,
  | references.DanglingReferences,
  | misc.Transitions

readers.pep.Reader:
  | references.Substitutions,
  | references.PropagateTargets,
  | references.AnonymousHyperlinks,
  | references.IndirectHyperlinks,
  | references.Footnotes,
  | references.ExternalTargets,
  | references.InternalTargets,
  | references.DanglingReferences,
  | misc.Transitions,
  | peps.Headers,
  | peps.Contents,
  | peps.TargetNotes

parsers.rst.Parser
  universal.SmartQuotes

writers.Writer:
  | universal.Messages,
  | universal.FilterMessages,
  | universal.StripClassesAndElements

writers.UnfilteredWriter
  None

writers.latex2e.Writer
  writer_aux.Admonitions

writers.html4css1.Writer:
  writer_aux.Admonitions

writers.odf_odt.Writer:
  removes references.DanglingReferences
