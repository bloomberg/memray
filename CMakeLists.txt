cmake_minimum_required(VERSION 3.24...3.26)
project(memray)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_INSTALL_RPATH_USE_LINK_PATH TRUE)

# Find Python
find_package(Python COMPONENTS Interpreter Development.Module Development.SABIModule REQUIRED)

# Find Cython
find_program(CYTHON_EXECUTABLE cython)
if(NOT CYTHON_EXECUTABLE)
    message(FATAL_ERROR "Cython not found. Please install Cython.")
endif()

# Find required packages
find_package(PkgConfig REQUIRED)
pkg_check_modules(LZ4 liblz4)
if(NOT LZ4_FOUND)
    message(FATAL_ERROR "liblz4 not found. Please install liblz4-dev or equivalent.")
endif()

if(${CMAKE_SYSTEM_NAME} MATCHES "Linux")
    pkg_check_modules(UNWIND libunwind)
    if(NOT UNWIND_FOUND)
        message(FATAL_ERROR "libunwind not found. Please install libunwind-dev or equivalent.")
    endif()

    pkg_check_modules(DEBUGINFOD libdebuginfod)
    if(NOT DEBUGINFOD_FOUND)
        # Some systems don't have a libdebuginfod.pc file.
        # See if there's a libdebuginfod.so wherever liblz4 or libunwind are.
        include(CheckLibraryExists)
        check_library_exists("libdebuginfod.so" "debuginfod_find_debuginfo" "${LZ4_LIBRARY_DIRS};${UNWIND_LIBRARY_DIRS}" DEBUGINFOD)
        if(DEBUGINFOD)
            set(DEBUGINFOD_LIBRARIES "debuginfod")
        else()
            message(FATAL_ERROR "libdebuginfod not found. Please install libdebuginfod-dev or equivalent.")
        endif()
    endif()
endif()

# Set compiler flags
add_compile_options(-Wall)
if(NOT DEFINED ENV{NO_MEMRAY_FAST_TLS})
    add_compile_definitions(-DUSE_MEMRAY_TLS_MODEL=1)
endif()

set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} -flto")
set(CMAKE_CXX_FLAGS_RELWITHDEBINFO "${CMAKE_CXX_FLAGS_RELWITHDEBINFO} -flto")
set(CMAKE_CXX_FLAGS_DEBUG "${CMAKE_CXX_FLAGS_DEBUG} -Og")

if(${CMAKE_SYSTEM_NAME} MATCHES "Linux")
    set(BINARY_FORMAT "elf")
elseif(${CMAKE_SYSTEM_NAME} MATCHES "Darwin")
    set(BINARY_FORMAT "macho")
else()
    message(FATAL_ERROR "Unsupported platform: ${CMAKE_SYSTEM_NAME}")
endif()

# Set up libbacktrace
set(LIBBACKTRACE_DIR ${CMAKE_SOURCE_DIR}/src/vendor/libbacktrace)
set(LIBBACKTRACE_INSTALL_DIR ${LIBBACKTRACE_DIR}/install)
set(LIBBACKTRACE_INCLUDE_DIR ${LIBBACKTRACE_INSTALL_DIR}/include)
set(LIBBACKTRACE_LIB_DIR ${LIBBACKTRACE_INSTALL_DIR}/lib)

# Add custom command to build libbacktrace
add_custom_command(
    OUTPUT ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a
    OUTPUT ${LIBBACKTRACE_INCLUDE_DIR}/libbacktrace/backtrace.h
    OUTPUT ${LIBBACKTRACE_INCLUDE_DIR}/libbacktrace/internal.h
    COMMAND mkdir -p ${LIBBACKTRACE_INSTALL_DIR}
    COMMAND mkdir -p ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build
    COMMAND cd ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build  &&
        ${LIBBACKTRACE_DIR}/configure
        --with-pic
        --prefix=${LIBBACKTRACE_INSTALL_DIR}
        --includedir=${LIBBACKTRACE_INCLUDE_DIR}/libbacktrace
    COMMAND make -C ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build -j
    COMMAND make -C ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build install
    DEPENDS ${LIBBACKTRACE_DIR}/configure
)
add_custom_target(libbacktrace DEPENDS ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a)

# _memray extension

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp
    COMMAND Python::Interpreter -m cython
      --cplus
      -3
      -X embedsignature=True
      -X boundscheck=$<IF:$<CONFIG:Debug>,True,False>
      -X wraparound=$<IF:$<CONFIG:Debug>,True,False>
      -X overflowcheck=$<IF:$<CONFIG:Debug>,True,False>
      -X cdivision=$<IF:$<CONFIG:Debug>,False,True>
      -X c_string_type=unicode
      -X c_string_encoding=utf8
      -I ${CMAKE_SOURCE_DIR}/src/memray/
      ${CMAKE_SOURCE_DIR}/src/memray/_memray.pyx
      -o ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp
      --module-name memray._memray
    DEPENDS ${CMAKE_SOURCE_DIR}/src/memray/_memray.pyx
    VERBATIM
)
python_add_library(_memray MODULE WITH_SOABI
    src/memray/_memray/compat.cpp
    src/memray/_memray/hooks.cpp
    src/memray/_memray/tracking_api.cpp
    src/memray/_memray/${BINARY_FORMAT}_shenanigans.cpp
    src/memray/_memray/logging.cpp
    src/memray/_memray/python_helpers.cpp
    src/memray/_memray/source.cpp
    src/memray/_memray/sink.cpp
    src/memray/_memray/records.cpp
    src/memray/_memray/record_reader.cpp
    src/memray/_memray/record_writer.cpp
    src/memray/_memray/snapshot.cpp
    src/memray/_memray/socket_reader_thread.cpp
    src/memray/_memray/native_resolver.cpp
    ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp
)

target_include_directories(_memray PRIVATE
    ${CMAKE_SOURCE_DIR}/src/memray/_memray
    ${LIBBACKTRACE_INCLUDE_DIR}
    ${LZ4_INCLUDE_DIRS}
    ${UNWIND_INCLUDE_DIRS}
    ${DEBUGINFOD_INCLUDE_DIRS}
)
target_link_libraries(_memray PRIVATE
    ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a
    ${LZ4_LIBRARIES}
    ${UNWIND_LIBRARIES}
    ${DEBUGINFOD_LIBRARIES}
    dl
)
target_link_directories(_memray PRIVATE
    ${LZ4_LIBRARY_DIRS}
    ${UNWIND_LIBRARY_DIRS}
    ${DEBUGINFOD_LIBRARY_DIRS}
)
target_link_options(_memray PRIVATE
    ${LZ4_LDFLAGS}
    ${UNWIND_LDFLAGS}
    ${DEBUGINFOD_LDFLAGS}
)
target_compile_options(_memray PRIVATE
    ${LZ4_CFLAGS}
    ${UNWIND_CFLAGS}
    ${DEBUGINFOD_CFLAGS}
)
add_dependencies(_memray libbacktrace)

# _test_utils extension

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp
    COMMAND Python::Interpreter -m cython
      --cplus
      -3
      -X embedsignature=True
      -X boundscheck=False
      -X wraparound=False
      -X cdivision=True
      -X c_string_type=unicode
      -X c_string_encoding=utf8
      -I ${CMAKE_SOURCE_DIR}/src/memray/
      ${CMAKE_SOURCE_DIR}/src/memray/_memray_test_utils.pyx
      -o ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp
      --module-name memray._test_utils
    DEPENDS ${CMAKE_SOURCE_DIR}/src/memray/_memray_test_utils.pyx
    VERBATIM
)
python_add_library(_test_utils MODULE WITH_SOABI
    ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp
)
target_include_directories(_test_utils PRIVATE
    ${CMAKE_SOURCE_DIR}/src/memray/_memray
)

# _inject extension

python_add_library(_inject MODULE WITH_SOABI USE_SABI 3.7
    src/memray/_memray/inject.cpp
)
target_include_directories(_inject PRIVATE
    ${CMAKE_SOURCE_DIR}/src/memray
)

# Install targets
install(TARGETS _memray _test_utils _inject LIBRARY DESTINATION memray)
