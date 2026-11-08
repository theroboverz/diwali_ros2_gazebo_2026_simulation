# plugins/

No custom C++ Gazebo system plugin is built in this project. Fireworks use Gazebo Harmonic's own
`gz::sim::systems::ParticleEmitter` system (`gz-sim-particle-emitter-system`), choreographed by
`diwali_festival` over Gazebo Transport. Add a plugin here only if the approximation proves
insufficient (e.g. true per-shell bursts); it would need `find_package(gz-sim8)`,
`find_package(gz-plugin2 COMPONENTS register)`, `GZ_ADD_PLUGIN`, and installation into
`lib/${PROJECT_NAME}` with `GZ_SIM_SYSTEM_PLUGIN_PATH` pointing at it.
