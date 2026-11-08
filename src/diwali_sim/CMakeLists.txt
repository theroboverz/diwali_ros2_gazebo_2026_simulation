cmake_minimum_required(VERSION 3.8)
project(diwali_sim)

find_package(ament_cmake REQUIRED)

# Resource package: SDF world, generated models/textures, launch files. No C++ target is built
# because fireworks use Gazebo Harmonic's built-in ParticleEmitter system (see plugins/README.md).
install(DIRECTORY worlds models materials launch config plugins
  DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/generate_assets.py
  DESTINATION lib/${PROJECT_NAME})

ament_package()
