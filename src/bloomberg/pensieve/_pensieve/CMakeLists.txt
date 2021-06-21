cmake_minimum_required(VERSION 3.17)
project(_pensieve)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(PythonInterp 3.8 REQUIRED)
find_package(PythonLibs 3.8 REQUIRED)
IF(NOT PYTHONLIBS_FOUND OR NOT PYTHON_EXECUTABLE)
    MESSAGE(SEND_ERROR "You need Python to build Python binding")
ENDIF(NOT PYTHONLIBS_FOUND OR NOT PYTHON_EXECUTABLE)

include_directories(.)

add_library(_pensieve STATIC
        elf_shenanigans.cpp
        guards.cpp
        hooks.cpp
        logging.cpp
        python_helpers.cpp
        record_reader.cpp
        record_writer.cpp
        records.cpp
        tracking_api.cpp
        native_resolver.cpp
        interval_tree.cpp)
set_property(TARGET _pensieve PROPERTY POSITION_INDEPENDENT_CODE ON)
include_directories("." ${PYTHON_INCLUDE_DIRS})
