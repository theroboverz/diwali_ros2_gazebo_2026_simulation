"""Stage 5: world + robot + Nav2 + festival (manual) + cracker_tour.

The AMR leaves home, drives to every cracker in the city (config/cracker_tour.yaml), lights each one on
arrival, then returns home for a finale. cracker_tour waits for Nav2 itself, so it starts with everything else.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    sim = get_package_share_directory('diwali_sim')
    localization = LaunchConfiguration('localization')
    full = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(sim, 'launch', 'full_diwali_sim.launch.py')),
        launch_arguments={'mode': 'nav2', 'autonomous': 'false', 'localization': localization,
                          'sound': LaunchConfiguration('sound'), 'rviz': LaunchConfiguration('rviz'),
                          'headless': LaunchConfiguration('headless')}.items())
    tour = Node(
        package='diwali_festival', executable='cracker_tour', name='cracker_tour', output='screen',
        parameters=[{'use_sim_time': True,
                     'tour_file': LaunchConfiguration('tour_file'),
                     'localizer': PythonExpression(["'amcl' if '", localization, "' == 'amcl' else 'map_server'"]),
                     'dwell_s': ParameterValue(LaunchConfiguration('dwell_s'), value_type=float)}])
    return LaunchDescription([
        DeclareLaunchArgument('tour_file', default_value=os.path.join(sim, 'config', 'cracker_tour.yaml')),
        DeclareLaunchArgument('dwell_s', default_value='2.0', description='Pause at each lit cracker'),
        DeclareLaunchArgument('localization', default_value='ground_truth', description='ground_truth | amcl'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('sound', default_value='true'),
        DeclareLaunchArgument('headless', default_value='false'),
        full, tour,
    ])
