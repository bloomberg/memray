from setuptools import Extension
from setuptools import setup

setup(
    name="free_sized_extension",
    ext_modules=[
        Extension(
            "free_sized_test",
            sources=["free_sized_test.c"],
            language="c",
            extra_compile_args=["-std=c23"],
        )
    ],
)
