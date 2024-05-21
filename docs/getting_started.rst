Getting started
===============

Installation
------------

Memray can easily be installed from PyPI.

PyPI
~~~~

When installing Memray with ``pip`` you need to install it with the
Python interpreter you intend to run your profiled application with. In
this case example we're installing it for use with Python 3.9:

.. code:: shell

    python3.9 -m pip install memray

Using the CLI
-------------

You can invoke Memray the following way:

.. code:: shell

  python3.9 -m memray

Or alternatively through the version-qualified ``memrayX.Y`` script:

.. code:: shell

  memray3.9

You can also invoke Memray without version-qualifying it:

.. code:: shell

  memray

The downside to the unqualified ``memray`` script is that it's not immediately
clear what Python interpreter will be used to execute Memray. If you're using
a virtual environment that's not a problem because you know exactly what interpreter is
in use, but otherwise you need to be careful to ensure that ``memray`` is
running with the interpreter you meant to use.

Profiling with Memray should be done in two steps:

1. Run the application to track allocations and deallocations and save the results
2. Generate the desired report from the captured results

Running the Analysis
--------------------

To run memray on the ``example.py`` script, use :doc:`the run subcommand <run>`.

.. code:: shell

  memray3.9 run example.py

This will execute the script and track its memory allocations, displaying the name of the file where results are being recorded with a message like:

.. code:: text

  Writing profile results into memray-example.py.4131.bin

Generating a Flame Graph
------------------------

To generate a flame graph displaying memory usage across the application, we can run ``memray flamegraph`` and specify
the results file:

.. code:: shell

  memray3.9 flamegraph memray-example.py.4131.bin

This will generate the ``memray-flamegraph-example.py.4131.html`` file in the current directory. See the :doc:`flamegraph`
documentation which explains how to interpret flame graphs.

Next Steps
----------

The "Hands-on Tutorial" section of our sidebar includes :doc:`a set of lessons <tutorials/index>` you can use to
practice working with Memray by debugging example Python applications with surprising memory allocation behavior. You
can also try Memray out on our :doc:`example applications <examples/README>`.

If you instead want to jump directly into debugging one of your own applications, the "Concepts" section of our sidebar
gives background information to help you use Memray more effectively. Reading about :doc:`the run subcommand <run>` will
tell you what options to use for debugging memory leaks, or for seeing the native stack traces corresponding to
allocations. Interpreting the generated memory profiles will be much easier if you understand :doc:`the Python
allocators <python_allocators>` as well as :doc:`some general memory concepts <memory>`.

If you find any bugs, you can `file a bug report`_. If you aren't sure whether something is a bug or expected behavior,
or if you want to suggest an idea or discuss things with the maintainers, you should `start a discussion`_ instead.

Good luck, and happy debugging!

.. _file a bug report: https://github.com/bloomberg/memray/issues/new?&labels=bug&template=---bug-report.yaml
.. _start a discussion: https://github.com/bloomberg/memray/discussions/new/choose
