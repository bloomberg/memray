memray stats
==============

The ``stats`` subcommand generates high level allocation statistics
of the target at the time when the memory usage was at its peak. 
Optionally, it is possible to view the stats for *all* allocations
See :doc:`memray stats <../stats>` for more information.

General Form
------------

The ``stats`` subcommand takes the following form:

.. code:: shell

    memray3.x stats [-h] [-a] [-n NUM_LARGEST] results


The only positional argument the ``stats`` subcommand requires is the file
previously generated with the :doc:`run <run>` subcommand.

The output will be printed directly to the standard output of the terminal.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: stats
   :prog: memray
