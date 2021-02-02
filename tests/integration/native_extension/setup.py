import os
from distutils.core import Extension
from distutils.core import setup

ROOT = os.path.realpath(os.path.dirname(__file__))

setup(
    name="native_ext",
    version="0.0",
    ext_modules=[
        Extension(
            "native_ext",
            language="c++",
            sources=[os.path.join(ROOT, "native_ext.cpp")],
        ),
    ],
    zip_safe=False,
)
