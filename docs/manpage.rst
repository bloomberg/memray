:orphan:

Overview
========

.. argparse::
   :ref: memray.commands.get_argument_parser
   :manpage:
   :nosubcommands:

   Memray can track memory allocations in Python code, in native extension modules, and in the Python
   interpreter itself. It can generate several different types of reports to help you analyze the captured
   memory usage data. While commonly used as a CLI tool, it can also be used as a library to perform more
   fine-grained profiling tasks.

   Most commonly you will use the ``memray run`` subcommand to create a capture file, and then use a reporter
   like the ``memray flamegraph`` subcommand to analyze it.

   .. note::

       This manual page only documents usage of the Memray subcommands that can be invoked from the command line.
       See `<https://bloomberg.github.io/memray/overview.html>`_ for the full Memray documentation, which
       includes advice for interpreting Memray reports, example programs, API documentation, information about
       integrating Memray into Jupyter notebooks and pytest test suites, explanations to help you understand how
       Python uses memory and how Memray gathers information about memory usage, and more.

RUN SUB-COMMAND
---------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: run
   :nodefaultconst:
   :noepilog:

FLAMEGRAPH SUB-COMMAND
----------------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: flamegraph
   :nodefaultconst:
   :noepilog:

TABLE SUB-COMMAND
-----------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: table
   :nodefaultconst:
   :noepilog:

LIVE SUB-COMMAND
----------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: live
   :nodefaultconst:
   :noepilog:

TREE SUB-COMMAND
----------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: tree
   :nodefaultconst:
   :noepilog:

PARSE SUB-COMMAND
-----------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: parse
   :nodefaultconst:
   :noepilog:

SUMMARY SUB-COMMAND
-------------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: summary
   :nodefaultconst:
   :noepilog:

STATS SUB-COMMAND
-----------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: stats
   :nodefaultconst:
   :noepilog:

TRANSFORM SUB-COMMAND
---------------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: transform
   :nodefaultconst:
   :noepilog:

ATTACH SUB-COMMAND
------------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: attach
   :nodefaultconst:
   :noepilog:

DETACH SUB-COMMAND
------------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: detach
   :nodefaultconst:
   :noepilog:
