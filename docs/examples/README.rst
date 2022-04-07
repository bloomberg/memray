.. _example-applications:

Example Applications for Memray
=================================

The projects in the directories located here contain very simple
examples to demonstrate usage with Memray.

Make sure you install the required dependencies by running
``python3.9 -m pip install -r requirements.txt`` in the respective
directory. The examples below use the project in the ``mandelbrot`` folder, but
you can use the same instructions to launch the other examples as well.

To track memory allocations, invoke ``memray3.9 run``:

.. code:: shell

   python3.9 -m memray run numpy/example.py

Memray will print a message displaying the output file it creates.

.. code:: text

   Writing profile results into bas/memray-example.py.6570.bin

You can use this file to create various reports. To generate a flame
graph, use the following command:

.. code:: shell

   python3.9 -m memray flamegraph numpy/memray-basexample.py.6570.bin

The HTML file for the flame graph will be generated under
``memray-flamegraph-example.py.6570.html``. The flame graph displays the stack frames
in the application where allocations have occurred and shows the amount
of memory used in each frame.

You can see sample outputs of the resulting flame graphs:

- `Mandelbrot <../_static/flamegraphs/memray-flamegraph-mandelbrot.html>`_
