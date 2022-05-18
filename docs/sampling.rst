Sampling
========

In this section we explain in detail what sampling profiling is and how it is implemented
in Memray.

Bernoulli process
-----------------

The idea is that in order to avoid having to record all allocations we decide to
sample them randomly. Instead of randomly deciding whether or not to take
individual allocations (which can be of different sizes) we think of the bytes
individually as a stream. We roll some dice to decide if each byte will be recorded
or not. When you do this for a very very large amount of bytes where the
probability of choosing any byte remains constant this is called a
"Bernoulli process". The reason we use this statistical approach, as opposed to
taking every nth byte, is that there may be regular allocation patterns in the
code that may be missed by a correspondingly regular sampling. For instance, if
the code loops forever creating one 20 byte object then one 80 byte object,
sampling every 100 bytes would always see the same one of those allocations on
each loop iteration.

To account for the sampling process, we need to scale every byte that we decide
to sample to the correct scale by multiplying by the sampling size
(the inverse of the probability of choosing a byte). For example if we sample a
byte with probability of 40%, then each byte sampled represents statistically 40
bytes allocated.

The implementation is a bit different, though. The reason is that throwing a
random number for every single byte allocated is too expensive to do in
practice. We could sample from the Poisson distribution, which would tell us the
number of samples that we need to take per allocation (how many bytes we need to
sample from a collection of "n bytes" that make up a complete allocation) but this is
still too expensive, because it forces us to still throw a random number from
the Poisson distribution (which is expensive) per allocation. What we (and many
other sampling profilers) do instead is use the Exponential distribution.
The exponential distribution tells us the amount of bytes we need to wait before
taking the next sample. This is much better than throwing a random
number per allocation, because this way we only roll one random number per
sample, then keep substracting bytes from this number until it reaches zero - at
which point we record a new sample, roll a new random number, and start over.
This minimizes the amount of random numbers we need to generate.

As is customary in this method, an optimization here is that if a given
allocation is bigger than the average ammount of bytes we need to wait until the
next sample, we take it directly as it's very likely that we are going to sample
it at least once.

This process is entirely dependent on the probability of sampling a single byte in
the Bernoulli process, which is the inverse of how many bytes on average we need
to wait until the next sample. Choosing this number wisely is very important for
good results.

.. note:: 

    This random distribution approach has several advantages: first, its
    statistical properties make it very easy to estimate actual statistical
    characteristics of the heap -- indeed, we certainly want to weight large
    allocated blocks more than small ones. Second, Poisson processes are
    relatively easy to simulate with reasonable performance.

Algorithm
---------

Like many other profilers that implement sampling using this method, the algorithm Memray
follows is:

* We draw a random number from the exponential distribution with a given sample rate. This tells us how many bytes
  we must wait until before taking our next sample.

* When an allocation occurs with a size bigger than the sampling size, we sample the entire allocation with its original size. We do
  this becuse the probability that we are going to take at least one sample is very high and so this is a good performance
  optimization.

* When an allocation occurs for a size smaller than our sampling size, we substract the size of the allocation from the amount of bytes
    we must wait until before taking our next sample. If this number reaches zero, we take a sample and we draw another random number from
  the exponential distribution. The amount of times we had to draw from the exponential distribution is the number of samples
  the allocation should count as.

* We multiply the number of samples we drew within the allocation by the sampling rate to get an estimate of the statistical
  size of the allocation. We record this allocation and its stack as if the allocation had the statistical size that we obtained.

Performance
-----------

Sampling ``1/p`` bytes (where ``p`` is the probability of choosing a given byte)
has an impact on the coverage of the bytes we sample and therefore on the
accuracy of the results. For example, choosing a very small value for ``p``
(which means we will wait a lot for taking samples) will give us a lot of speed
(because we won't be sampling many allocations) but will cost us a lot in
accuracy. On the other hand, setting ``p=1`` will give us perfect accuracy, as
we will be sampling every single byte. We need to understand how ``p`` impacts
our accuracy so we can choose the right value for every situation.

In the following figure, you can see the probability of taking a sample
for different sampling sizes, depending on the allocation size.  We can
see from the chart below that if raise our sample size by a factor of 16 from
32B to 512B we have a 95% chance of collecting at least 1 sample after
allocating 1.5KiB. If we multiply it by a factor of 64 to 2048B we still have
an 80% chance of collecting at least 1 sample after 3.5KiB are allocated.

.. image:: _static/images/sampling_probability.png
    :align: center


In the following figure, the `Mean absolute percentage error
<https://en.wikipedia.org/wiki/Mean_absolute_percentage_error>`_ is displayed
for different sampling sizes and different allocation sizes under the assumption
that the allocations have at least one sample. These are the allocations that
will be dumped to the result file. You can read the graph in the following way:
"Given a particular sampling rate and an allocation size, when the sampler finally
decides to take a sample, how far off can our approximation of the allocation size
be from its true size?". For example, considering allocations of 1 byte
and a sampling size of 1024 bytes, as the sampler sees the first allocations it
will do nothing because the sampling size is much bigger (1024 bytes vs 1 bytes)
but when it finally decides to take a sample (how many bytes it will wait for
is determined by a random number from the exponential distribution) then it will
weight that single byte as if it were an allocation of 1024 bytes. As the
algorithm samples the entire allocation if its size is bigger or equal than the
sampling size, dashed vertical lines are displayed in these points. For a given
line, all points to the right of the vertical line have in reality an error of
zero.

.. image:: _static/images/sampling_error.png
    :align: center

References
----------

* `Bernoulli process <https://en.wikipedia.org/wiki/Bernoulli_process>`_
* `Bernoulli sampling <https://en.wikipedia.org/wiki/Bernoulli_sampling>`_
* `Statistically profiling memory in OCaml <https://jhjourdan.mketjh.fr/pdf/jourdan2016statistically.pdf>`_
* `Perfetto design document <https://perfetto.dev/docs/design-docs/heapprofd-sampling>`_
