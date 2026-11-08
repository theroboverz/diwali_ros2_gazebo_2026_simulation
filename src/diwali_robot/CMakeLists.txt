cmake_minimum_required(VERSION 3.8)
project(diwali_robot)

find_package(ament_cmake REQUIRED)

# Pure resource package (URDF/Xacro, launch, config, maps): no C++ is compiled.
install(DIRECTORY urdf meshes config launch worlds maps
  DESTINATION share/${PROJECT_NAME})

ament_package()
