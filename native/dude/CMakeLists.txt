cmake_minimum_required(VERSION 3.20)
project(neusymnav_dude_worker LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE OFF)
set(CMAKE_SKIP_RPATH ON)

if(NOT DEFINED M4_PREFIX OR M4_PREFIX STREQUAL "")
  message(FATAL_ERROR "M4_PREFIX must be supplied explicitly by tools/build_native.py")
endif()
get_filename_component(M4_PREFIX "${M4_PREFIX}" REALPATH)
set(CGAL_CONFIG "${M4_PREFIX}/lib/x86_64-linux-gnu/cmake/CGAL/CGALConfig.cmake")
if(NOT EXISTS "${CGAL_CONFIG}")
  message(FATAL_ERROR "CGALConfig.cmake was not found below explicit M4_PREFIX=${M4_PREFIX}")
endif()

set(PACKAGE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/upstream")
set(NATIVE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/upstream/native/dude")
set(DUDE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/upstream/Third_Party/dude_final")
set(FIST_ARCHIVE "${DUDE_ROOT}/FIST/libFIST.linux64.a")
foreach(required IN ITEMS
    "${PACKAGE_ROOT}/include/wrapper.cpp"
    "${PACKAGE_ROOT}/include/inc_decomp.cpp"
    "${NATIVE_ROOT}/worker.cpp"
    "${DUDE_ROOT}/src/dude.cpp"
    "${FIST_ARCHIVE}")
  if(NOT EXISTS "${required}")
    message(FATAL_ERROR "Vendored DuDe source closure is incomplete: ${required}")
  endif()
endforeach()

find_package(OpenCV REQUIRED COMPONENTS core imgproc)
find_package(CGAL REQUIRED COMPONENTS Core
  PATHS "${M4_PREFIX}/lib/x86_64-linux-gnu/cmake/CGAL" NO_DEFAULT_PATH)
find_package(PkgConfig REQUIRED)
pkg_check_modules(JSONCPP REQUIRED IMPORTED_TARGET jsoncpp)

set(GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${GENERATED_DIR}")
foreach(source IN ITEMS
    "${PACKAGE_ROOT}/include/wrapper.cpp"
    "${PACKAGE_ROOT}/include/inc_decomp.cpp")
  get_filename_component(name "${source}" NAME)
  file(READ "${source}" contents)
  string(REPLACE "#include \"dude_ros_logging.hpp\""
    "#include \"m4_non_ros_logging.hpp\"" contents "${contents}")
  file(WRITE "${GENERATED_DIR}/${name}" "${contents}")
endforeach()

file(GLOB DUDE_ROOT_SOURCES CONFIGURE_DEPENDS "${DUDE_ROOT}/src/*.cpp")
file(GLOB DUDE_SKELETON_SOURCES CONFIGURE_DEPENDS "${DUDE_ROOT}/src/skeleton/*.cpp")
file(GLOB DUDE_GRAPH_SOURCES CONFIGURE_DEPENDS "${DUDE_ROOT}/src/graph/*.cpp")
file(GLOB DUDE_DRAW_SOURCES CONFIGURE_DEPENDS "${DUDE_ROOT}/src/draw/*.cpp")
list(FILTER DUDE_ROOT_SOURCES EXCLUDE REGEX "/main\\.cpp$")
set(DUDE_SOURCES
  ${DUDE_ROOT_SOURCES}
  ${DUDE_SKELETON_SOURCES}
  ${DUDE_GRAPH_SOURCES}
  ${DUDE_DRAW_SOURCES})

add_executable(occusg_dude_worker
  "${NATIVE_ROOT}/worker.cpp"
  "${NATIVE_ROOT}/globals.cpp"
  "${NATIVE_ROOT}/preprocessing.cpp"
  "${GENERATED_DIR}/wrapper.cpp"
  "${GENERATED_DIR}/inc_decomp.cpp"
  ${DUDE_SOURCES})

target_include_directories(occusg_dude_worker BEFORE PRIVATE
  "${NATIVE_ROOT}/include"
  "${PACKAGE_ROOT}/include"
  "${DUDE_ROOT}/src"
  "${DUDE_ROOT}/src/skeleton"
  "${DUDE_ROOT}/src/graph"
  "${DUDE_ROOT}/src/draw"
  "${DUDE_ROOT}/mathtool"
  "${DUDE_ROOT}/FIST"
  "${DUDE_ROOT}"
  ${OpenCV_INCLUDE_DIRS})
target_link_directories(occusg_dude_worker PRIVATE "${M4_PREFIX}/lib/x86_64-linux-gnu")
target_link_libraries(occusg_dude_worker PRIVATE
  ${OpenCV_LIBS}
  CGAL::CGAL
  CGAL::CGAL_Core
  "${FIST_ARCHIVE}"
  gmpxx
  gmp
  mpfr
  PkgConfig::JSONCPP)
target_compile_definitions(occusg_dude_worker PRIVATE NDEBUG)
target_compile_options(occusg_dude_worker PRIVATE -Wall -Wextra -Wno-deprecated-declarations)
target_link_options(occusg_dude_worker PRIVATE -no-pie)
set_target_properties(occusg_dude_worker PROPERTIES SKIP_BUILD_RPATH TRUE)
