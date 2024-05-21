p "MEMRAY: Attached to process."

set unwindonsignal on
sharedlibrary libc
sharedlibrary libdl
sharedlibrary musl
sharedlibrary libpython
info sharedlibrary

p "MEMRAY: Checking if process is Python 3.7+."

p PyMem_Malloc
p PyMem_Calloc
p PyMem_Realloc
p PyMem_Free

p "MEMRAY: Process is Python 3.7+."
set scheduler-locking on
call (int)Py_AddPendingCall(&PyCallable_Check, (void*)0)

# When updating this list, also update the "commands" call below,
# and the breakpoints hardcoded for lldb in attach.py
b malloc
b calloc
b realloc
b free
b PyMem_Malloc
b PyMem_Calloc
b PyMem_Realloc
b PyMem_Free
b PyErr_CheckSignals
b PyCallable_Check
# Apply commands to all 10 breakpoints above
commands 1-10
    bt
    disable breakpoints
    delete breakpoints
    call (void*)dlopen($libpath, $rtld_now)
    p (char*)dlerror()
    eval "sharedlibrary %s", $libpath
    p (int)memray_spawn_client($port) ? "FAILURE" : "SUCCESS"
end
set scheduler-locking off
continue
