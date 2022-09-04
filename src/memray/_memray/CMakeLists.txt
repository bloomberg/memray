cmake_minimum_required(VERSION 3.10)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
project(_memray)

find_package(
  Python
  COMPONENTS Interpreter Development
  REQUIRED)

if(CMAKE_HOST_SYSTEM_NAME MATCHES "Darwin")
  set(MEMRAY_LINKER_FILE macho_shenanigans.cpp)
else()
  set(MEMRAY_LINKER_FILE elf_shenanigans.cpp)
endif()

add_library(
  _memray STATIC
  ${MEMRAY_LINKER_FILE}
  inject.cpp
  compat.cpp
  hooks.cpp
  logging.cpp
  native_resolver.cpp
  python_helpers.cpp
  record_reader.cpp
  record_writer.cpp
  records.cpp
  sink.cpp
  snapshot.cpp
  socket_reader_thread.cpp
  source.cpp
  tracking_api.cpp)

if(CMAKE_HOST_SYSTEM_NAME MATCHES "Darwin")
  execute_process(
    COMMAND brew --prefix lz4
    RESULT_VARIABLE BREW_LZ4
    OUTPUT_VARIABLE BREW_LZ4_PREFIX
    OUTPUT_STRIP_TRAILING_WHITESPACE)
  if(BREW_LZ4 EQUAL 0 AND EXISTS "${BREW_LZ4_PREFIX}")
    message(STATUS "Found Lz4 installed by Homebrew at ${BREW_LZ4_PREFIX}")
    include_directories("${BREW_LZ4_PREFIX}/include")
    link_directories("${BREW_LZ4_PREFIX}/lib")
  endif()
else()
  find_package(PkgConfig REQUIRED)
  pkg_check_modules(BINARY_DEPS REQUIRED liblz4 libunwind)
  target_link_libraries(_memray ${BINARY_DEPS_STATIC_LIBRARIES})
  target_include_directories(_memray PUBLIC ${BINARY_DEPS_INCLUDE_DIRS})
  target_compile_options(_memray PUBLIC ${BINARY_DEPS_CFLAGS})
  target_link_options(_memray PUBLIC ${BINARY_DEPS_LDFLAGS})
endif()

include_directories(. ../../vendor/libbacktrace/install/include
                    ${Python_INCLUDE_DIRS})
link_directories(../../vendor/libbacktrace/install/lib)
