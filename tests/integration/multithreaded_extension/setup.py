import os
from distutils.core import Extension
from distutils.core import setup

ROOT = os.path.realpath(os.path.dirname(__file__))

setup(
    name="testext",
    version="0.0",
    ext_modules=[
        Extension(
            "testext",
            language="c++",
            sources=[os.path.join(ROOT, "testext.cpp")],
        ),
    ],
    zip_safe=False,
)
