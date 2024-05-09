What to learn about next
========================

We've now introduced ourselves with Memray, had a look at how it can be used in development workflows and when diagnosing unexpected memory issues. This section will briefly introduce you to a few more features offered by Memray which you can explore further in your own time.


Pytest Plugin
----------------

Memray offers a really helpful pytest plugin ``pytest-memray`` which has a couple notable features:

- ``@pytest.mark.limit_memory()`` marks tests as failed if the execution of said test allocates more memory than allowed. We used these markers throughout the unit tests in the three tutorial exercises. It will also print a helpful overview of which function calls used up the most memory for the failed test cases.
- ``pytest --memray`` the memray flag when running your tests using pytest will generate a report with a high level overview of the memory allocated and will list a few top memory using functions


Try to utilise the plugin in your unit tests, and have them run as a part of your CI/CD.

Read more about the memray pytest plugin in the `official documentation <https://pypi.org/project/memray>`_


Reporters
----------------

As a part of this study guide, we've worked with flamegraphs. However, memray offers numerous other types of reporters. If you would like to learn about different types of reports available, check out the :doc:`Reporters </live>` section on the left-hand side of this page.
