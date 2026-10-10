Temporary allocations
=====================

Some reporters accept the ``--temporary-allocation-threshold=THRESHOLD`` and
``--temporary-allocations`` options. When one of these options is used, the
reporter will show where temporary allocations happened.

What are temporary allocations?
-------------------------------

We consider a memory allocation "temporary" if there are at most ``THRESHOLD``
other allocations performed between when it is allocated and when it is
deallocated. When the threshold is 0 an allocation is considered temporary
only if it is immediately deallocated. When the threshold is 1 an allocation
will be detected as temporary even if 1 other allocation occurs before it is
deallocated.

Seeing where temporary allocations are being performed can help you identify
areas of your code base that frequently perform small allocations and
deallocations. Sometimes these can be avoided by doing one big allocation
instead, or by using a memory pool.

The ``--temporary-allocations`` option behaves as though you passed
``--temporary-allocation-threshold=1``.  We think this is the most interesting
default threshold, because it lets you detect when elements are sequentially
added to a container. That's because growing a container is often performed by
allocating a new, larger buffer for the container, then copying over every
element from the old buffer and deallocating it. When iteratively adding new
elements to a container, each resize results in 1 allocation for a new buffer
before the previously allocated buffer can be freed, and so these buffers
wouldn't be seen as temporary with a threshold of 0.

Detecting inefficient allocation patterns
-----------------------------------------

Temporary allocation detection can help detect inefficient allocation patterns.
For example, consider the following code:

.. code-block:: python

    def foo(n):
        x = []
        for _ in range(n):
            x.append(None)
        return x

    foo(1_000_000)

If we run this code and check the output of the :doc:`the summary reporter </summary>`

.. code-block:: shell-session

    $ memray run -fo test.bin example.py
    $ memray summary test.bin --temporary-allocations
    ┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
    ┃                      ┃     <Total ┃      Total ┃            ┃ Own Memory ┃ Allocation ┃
    ┃ Location             ┃    Memory> ┃   Memory % ┃ Own Memory ┃          % ┃      Count ┃
    ┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
    │ foo at example.py    │   72.486MB │     99.93% │   72.486MB │     99.93% │         78 │
    │ ...                  │            │            │            │            │            │
    └──────────────────────┴────────────┴────────────┴────────────┴────────────┴────────────┘

we can see that our function ``foo()`` is responsible for making 78 allocations
which cumulatively allocate 72.48MB. This happens because the list needs to grow
as we append elements to it.

If we change how the list is built

.. code-block:: python

    def foo(n):
        return [None] * n

    foo(1_000_000)

and run the same commands as before

.. code-block:: shell-session

    $ memray run -fo test.bin example2.py
    $ memray summary test.bin --temporary-allocations
    ┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┳━━━━━━━━━━━━┓
    ┃                      ┃     <Total ┃      Total ┃            ┃ Own Memory ┃ Allocation ┃
    ┃ Location             ┃    Memory> ┃   Memory % ┃ Own Memory ┃          % ┃      Count ┃
    ┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━╇━━━━━━━━━━━━┩
    │ foo at example2.py   │    7.629MB │     99.29% │    7.629MB │     99.29% │          1 │
    │ ...                  │            │            │            │            │            │
    └──────────────────────┴────────────┴────────────┴────────────┴────────────┴────────────┘

we can see that ``foo()`` only made 1 allocation, and the total amount of memory
it allocates has been reduced by around 90%. This is because ``[None] * n``
knows how many elements will be present in the final result and allocates
a single chunk of memory large enough to hold all the elements right from the
start, instead of starting off with a small buffer and then repeatedly growing
it as needed.
