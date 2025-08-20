from setuptools import Extension, setup

setup(
    name="free_sized_extension",
    ext_modules=[
        Extension(
            "free_sized_test",
            sources=["free_sized_test.cpp"],
            language="c++",
        )
    ],
)
