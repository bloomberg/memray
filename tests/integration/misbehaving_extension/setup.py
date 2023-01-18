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
