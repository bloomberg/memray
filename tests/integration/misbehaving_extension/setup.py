import os
from distutils.core import Extension
from distutils.core import setup

ROOT = os.path.realpath(os.path.dirname(__file__))

setup(
    name="misbehaving",
    version="0.0",
    ext_modules=[
        Extension(
            "misbehaving",
            language="c++",
            sources=[os.path.join(ROOT, "misbehaving.cpp")],
        ),
    ],
    zip_safe=False,
)
