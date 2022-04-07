Usage
=====

Installation
------------

Memray can easily be installed from PyPI.

PyPI
~~~~~~~~~~~~~~

When installing memray with ``pip`` you need to install it with the Python interpreter you intend to run your profiled application with.
In this case example this is Python 3.9:

.. code:: shell

    > python3.9 -m pip install memray

Using the CLI
-------------

You can invoke memray the following way:

.. code:: shell

  > python3.9 -m memray


Or alternatively through the version-qualified ``memrayX.Y`` script:

.. code:: shell
  
  > memray3.9

Profiling with memray should be done in two steps:

1. Run the application to track allocations and deallocations and save the results
2. Generate the desired report type from the saved results

Running the Analysis
--------------------

To run memray on the ``example.py`` script, use the ``run`` subcommand:

.. code:: shell
  
  > python3.9 -m memray run example.py

  Writing profile results into memray-example.py.4131.bin
  ...


This will execute the script and track memory allocations and display the name of the file where results are stored.


Generating a Flame Graph
------------------------

To generate a flame graph displaying memory usage across the application, we can run ``memray flamegraph`` and specify
the results file:

.. code:: shell
  
  > python3.9 -m memray flamegraph memray-example.py.4131.bin


This will generate the ``memray-example.py.4131.html`` file in the current directory. See the :doc:`flamegraph`
section which explains how to interpret flame graphs.

