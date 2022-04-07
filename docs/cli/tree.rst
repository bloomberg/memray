memray tree
=============

The ``tree`` subcommand generates a simplified representation of the
allocation structure in the target at the time when the memory usage was at its
peak. See :doc:`memray tree <../tree>` for more information.

General Form
------------

The ``tree`` subcommand takes the following form:

.. code:: shell

    memray3.x tree [-h] [--biggest-allocs BIGGEST_ALLOCS] results


The only positional argument the ``tree`` subcommand requires is the file
previously generated with the :doc:`run <run>` subcommand.


The output will be printed directly to the standard output of the terminal.


CLI Reference
-------------

.. argparse::
   :ref: memray.commands.get_argument_parser
   :path: tree
   :prog: memray
