Table Reporter
==============

The table reporter provides a simple tabular representation of memory allocations in the target at the time when
the memory usage was at its peak.


.. image:: _static/images/table_example.png


The table can be sorted by each column and searched in the search field. The columns show the following data:

- Thread ID: thread where the allocation happened
- Size: total amount of memory used by all of these allocations
- Allocator: allocator or deallocator function which acquired the memory
- Allocations: total number of allocations performed by this entry
- Location: function name, file and line of the allocation or "???" if unknown
