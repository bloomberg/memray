Report interrupted object lifetime tracking when another tool replaces or removes
the Python reference tracer, and preserve the replacement tracer during cleanup.
On free-threaded Python, leave Memray's callback installed but inactive to avoid
racing with another tool installing its tracer.
