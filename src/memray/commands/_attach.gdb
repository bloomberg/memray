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
# Apply commands to all 8 breakpoints above
commands 1-8
    disable breakpoints
    call (void*)dlopen($libpath, $rtld_now)
    p (char*)dlerror()
    eval "sharedlibrary %s", $libpath
    p (int)memray_spawn_client($port) ? "FAILURE" : "SUCCESS"
end
continue
