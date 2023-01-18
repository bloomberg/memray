import os
import sysconfig
from distutils.core import Extension
from distutils.core import setup

ROOT = os.path.realpath(os.path.dirname(__file__))
LDSHARED = os.environ.get("LDSHARED", sysconfig.get_config_var("LDSHARED"))
if LDSHARED:
    LDSHARED = LDSHARED.replace("--strip-all", "-g")
    os.environ["LDSHARED"] = LDSHARED

setup(
    name="testext",
    version="0.0",
    ext_modules=[
        Extension(
            "testext",
            language="c++",
            sources=[os.path.join(ROOT, "testext.cpp")],
            extra_compile_args=["-O0", "-g3"],
        ),
    ],
    zip_safe=False,
)
