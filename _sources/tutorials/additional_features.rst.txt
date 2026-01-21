What to learn about next
========================

We've now acquainted ourselves with Memray, and had a look at how it can be used in development
workflows and for diagnosing unexpected memory issues. This section will briefly introduce you to
a few more features offered by Memray which you can explore further in your own time.

Essential Concepts
------------------

Check out the more detailed descriptions of the most essential concepts used in Memray by
exploring the :doc:`concepts <../run>` section on the sidebar. It goes into detail about the
``memray`` subcommands and features available, as well as memory management in Python.

pytest Plugin
-------------

Memray offers a helpful pytest plugin, ``pytest-memray``, which has a couple of notable
features:

- ``@pytest.mark.limit_memory()`` marks tests as failed if the execution of said test allocates more
  memory than allowed. We used these markers throughout the unit tests in the three tutorial
  exercises. It will also print a helpful overview of which function calls used up the most memory
  for the failed test cases.
- Running your tests as ``pytest --memray`` will generate a report with a high level overview of the
  memory allocated and will list a few top memory using functions.

Try to utilize the plugin in your unit tests, and have them run as a part of your CI/CD pipeline.

Read more about the memray pytest plugin in the `official documentation
<https://pytest-memray.readthedocs.io/en/latest/>`_.

Reporters
---------

As a part of this study guide, we've worked with flame graphs. However, Memray offers numerous other
types of reports for you to explore:

  - :doc:`Live Graphs <../live>`
  - :doc:`Summary Reporter <../summary>`
  - :doc:`Flame Graph Reporter <../flamegraph>`
  - :doc:`Table Reporter <../table>`
  - :doc:`Tree Reporter <../tree>`
  - :doc:`Stats Reporter <../stats>`
  - :doc:`Transform Reporter <../transform>`
