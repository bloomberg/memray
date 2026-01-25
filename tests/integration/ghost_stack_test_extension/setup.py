from distutils.core import Extension
from distutils.core import setup

setup(
    name="ghost_stack_test",
    ext_modules=[
        Extension(
            "ghost_stack_test",
            language="c++",
            sources=["ghost_stack_test.cpp"],
            extra_compile_args=["-O0", "-g3", "-fno-omit-frame-pointer"],
        ),
    ],
    zip_safe=False,
)
