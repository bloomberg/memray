cmake_minimum_required(VERSION 3.7)
project(memray)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Python
find_package(Python COMPONENTS Interpreter Development.Module Development.SABIModule REQUIRED)

# Find Cython
find_program(CYTHON_EXECUTABLE cython)
if(NOT CYTHON_EXECUTABLE)
    message(FATAL_ERROR "Cython not found. Please install Cython.")
endif()

# Find required packages
find_package(PkgConfig REQUIRED)
pkg_check_modules(LZ4 REQUIRED liblz4)
if(NOT LZ4_FOUND)
    message(FATAL_ERROR "LZ4 library not found. Please install liblz4-dev or equivalent.")
endif()

if(${CMAKE_SYSTEM_NAME} MATCHES "Linux")
    pkg_check_modules(LIBUNWIND REQUIRED libunwind)
endif()

# Set compiler flags
set(COMPILER_FLAGS "-Wall")
if(NOT DEFINED ENV{NO_MEMRAY_FAST_TLS})
    add_definitions(-DUSE_MEMRAY_TLS_MODEL=1)
endif()

if(DEFINED ENV{MEMRAY_MINIMIZE_INLINING})
    set(COMPILER_FLAGS ${COMPILER_FLAGS} -Og)
else()
    set(COMPILER_FLAGS ${COMPILER_FLAGS} -flto)
    set(LINKER_FLAGS ${LINKER_FLAGS} -flto)
endif()

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
set(LIBBACKTRACE_INCLUDE_DIR ${LIBBACKTRACE_DIR}/install/include)
set(LIBBACKTRACE_LIB_DIR ${LIBBACKTRACE_DIR}/install/lib)

# Add custom command to build libbacktrace
add_custom_command(
    OUTPUT ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a
    COMMAND mkdir -p ${LIBBACKTRACE_INSTALL_DIR}
    COMMAND mkdir -p ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build
    COMMAND cd ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build  &&
        ${LIBBACKTRACE_DIR}/configure 
        --with-pic 
        --prefix=${LIBBACKTRACE_INSTALL_DIR} 
        --includedir=${LIBBACKTRACE_INSTALL_DIR}/include/libbacktrace
    COMMAND cd ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build && make -j
    COMMAND cd ${CMAKE_CURRENT_BINARY_DIR}/libbacktrace_build && make install
    DEPENDS ${LIBBACKTRACE_DIR}/configure
)
add_custom_target(libbacktrace DEPENDS ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a)

# _memray extension

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp
    COMMAND Python::Interpreter -m cython
      --cplus 
      -3 
      -I ${CMAKE_SOURCE_DIR}/src/memray/
      ${CMAKE_SOURCE_DIR}/src/memray/_memray.pyx 
      -o ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp
    DEPENDS ${CMAKE_SOURCE_DIR}/src/memray/_memray.pyx
    VERBATIM
)
set(MEMRAY_SOURCES
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
)
python_add_library(_memray MODULE WITH_SOABI ${MEMRAY_SOURCES} ${CMAKE_CURRENT_BINARY_DIR}/_memray.cpp)
target_include_directories(_memray PRIVATE 
    ${CMAKE_SOURCE_DIR}/src/memray/_memray
    ${LIBBACKTRACE_INCLUDE_DIR} 
    ${LZ4_INCLUDE_DIRS}
)
target_link_libraries(_memray PRIVATE ${LZ4_LIBRARIES} dl ${LIBUNWIND_LIBRARIES} ${LIBBACKTRACE_LIB_DIR}/libbacktrace.a)
target_link_options(_memray PRIVATE ${LZ4_LDFLAGS})
target_compile_options(_memray PRIVATE ${COMPILER_FLAGS})
target_link_options(_memray PRIVATE ${LINKER_FLAGS})
add_dependencies(_memray libbacktrace)

# _test_utils extension

add_custom_command(
    OUTPUT ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp
    COMMAND Python::Interpreter -m cython
      --cplus 
      -3
      -I ${CMAKE_SOURCE_DIR}/src/memray/
      ${CMAKE_SOURCE_DIR}/src/memray/_memray_test_utils.pyx 
      -o ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp
      --module-name memray._test_utils
    DEPENDS ${CMAKE_SOURCE_DIR}/src/memray/_memray_test_utils.pyx
    VERBATIM
)
python_add_library(_test_utils MODULE WITH_SOABI ${CMAKE_CURRENT_BINARY_DIR}/_memray_test_utils.cpp)
target_include_directories(_test_utils PRIVATE 
    ${CMAKE_SOURCE_DIR}/src/memray/_memray
)

# _inject extension

set(INJECT_SOURCES
    src/memray/_memray/inject.cpp
)
python_add_library(_inject MODULE WITH_SOABI USE_SABI 3.7 ${INJECT_SOURCES})
target_include_directories(_inject PRIVATE 
    ${CMAKE_SOURCE_DIR}/src/memray
)
target_compile_options(_test_utils PRIVATE ${COMPILER_FLAGS})
target_link_options(_test_utils PRIVATE ${LINKER_FLAGS})
target_compile_options(_inject PRIVATE ${COMPILER_FLAGS})
target_link_options(_inject PRIVATE ${LINKER_FLAGS})


# Install targets
install(TARGETS _memray _test_utils _inject LIBRARY DESTINATION memray)