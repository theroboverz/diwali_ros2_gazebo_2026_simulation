"""Stage 3: world + robot (diwali_bot spawned on the road, bridged to ROS 2)."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration


def generate_launch_description():
    sim = get_package_share_directory('diwali_sim')
    robot = get_package_share_directory('diwali_robot')
    passthrough = ['festival', 'autonomous', 'sound', 'headless']
    args = [DeclareLaunchArgument('festival', default_value='false'),
            DeclareLaunchArgument('autonomous', default_value='true'),
            DeclareLaunchArgument('sound', default_value='true'),
            DeclareLaunchArgument('headless', default_value='false'),
            DeclareLaunchArgument('x', default_value='0.0'),
            DeclareLaunchArgument('y', default_value='0.0'),
            DeclareLaunchArgument('yaw', default_value='0.0')]
    world = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(sim, 'launch', 'diwali_world.launch.py')),
        launch_arguments={k: LaunchConfiguration(k) for k in passthrough}.items())
    spawn = TimerAction(period=6.0, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(robot, 'launch', 'robot.launch.py')),
        launch_arguments={'world_name': 'diwali_street', 'x': LaunchConfiguration('x'),
                          'y': LaunchConfiguration('y'), 'yaw': LaunchConfiguration('yaw')}.items())])
    return LaunchDescription(args + [world, spawn])
