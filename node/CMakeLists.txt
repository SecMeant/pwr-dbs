project(wbclient CXX)
cmake_minimum_required(VERSION 3.0)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(PkgConfig REQUIRED)

find_library(libpthread pthread REQUIRED)
pkg_check_modules(fmt REQUIRED fmt>=6)

set(SRC_DIR source)

file(GLOB_RECURSE SRC_FILES_CXX ${SRC_DIR}/*.cc ${SRC_DIR}/*.cpp)
add_executable(wbclient ${SRC_FILES_CXX})
target_link_libraries(wbclient ${libpthread} ${fmt_LIBRARIES})
