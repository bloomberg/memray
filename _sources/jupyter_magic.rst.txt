.. _Jupyter integration:

Jupyter Integration
===================

We provide an IPython extension that adds a new Jupyter cell magic. This lets
you create Memray flame graphs directly in Jupyter notebooks.

memray_flamegraph
-----------------

To load our IPython plugin, you simply need to run::

    %load_ext memray

Once it's loaded, you'll have access to the ``%%memray_flamegraph`` cell magic.
You can fill a Jupyter cell with ``%%memray_flamegraph`` on its own line,
followed by some code whose memory usage you want to profile. Memray will run
that cell's code, tracking its memory allocations, and then display a flame
graph directly in Jupyter for you to analyze.

It's also possible to provide arguments on the ``%%memray_flamegraph`` line.
For instance, ``%%memray_flamegraph --trace-python-allocators --leaks`` would
let you look for memory not freed by the code in the cell::

    %%memray_flamegraph --trace-python-allocators --leaks
    def a():
        return "a" * 10_000

    def bc():
        return "bc" * 10_000

    x = a() + bc()

Arguments
---------

.. argparse::
   :ref: memray._ipython.flamegraph.argument_parser
   :prog: %%memray_flamegraph
