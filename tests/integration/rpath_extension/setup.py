import subprocess

from setuptools import Extension
from setuptools import setup

# Compile the shared library before building the extension
subprocess.run(
    ["gcc", "-shared", "-o", "sharedlibs/sharedlib.so", "sharedlibs/sharedlib.c"]
)


setup(
    name="ext",
    version="1.0",
    ext_modules=[
        Extension(
            "ext",
            sources=["ext.c"],
            extra_link_args=["-Wl,-rpath,$ORIGIN/sharedlibs"],
        )
    ],
)
