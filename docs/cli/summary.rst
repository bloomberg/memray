memray summary
================

The ``summary`` subcommand provides a quick view on some statistics of the
highest watermark allocation records as well as a table showing different
statistics and relationships among functions that allocate memory.

See the :ref:`Live Tracking` section for more information on the table formatting.

General Form
------------

The ``summary`` (where x is the minor Python version) subcommand takes the
following form:

.. code:: shell

    usage: memray3.x summary [-h] [-s SORT_COLUMN] [-r MAX_ROWS] results

The only positional argument the ``summary`` subcommand requires is the file
previously generated with the :doc:`run <run>` subcommand.


The output will be printed directly to the standard output of the terminal.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: summary
   :prog: memray

