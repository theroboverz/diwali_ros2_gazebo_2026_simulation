"""Nav2 (planner/controller/BT navigator + costmaps) on the saved map.

localization:=ground_truth (default): the robot's /odom is Gazebo ground truth in world coordinates, which are
  also the map's coordinates, so map -> odom is a static identity and only map_server is needed.
localization:=amcl: the stock nav2_bringup map_server + AMCL. The street repeats every 12 m, so AMCL can lock onto
  the wrong block; prefer ground truth unless you are testing localization itself.
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('diwali_robot')
    nav2 = get_package_share_directory('nav2_bringup')
    params = LaunchConfiguration('params_file')
    ground_truth = IfCondition(PythonExpression(["'", LaunchConfiguration('localization'), "' == 'ground_truth'"]))
    amcl = IfCondition(PythonExpression(["'", LaunchConfiguration('localization'), "' == 'amcl'"]))
    return LaunchDescription([
        DeclareLaunchArgument('map', default_value=os.path.join(share, 'maps', 'diwali_street.yaml')),
        DeclareLaunchArgument('params_file', default_value=os.path.join(share, 'config', 'nav2_params.yaml')),
        DeclareLaunchArgument('localization', default_value='ground_truth', description='ground_truth | amcl'),
        DeclareLaunchArgument('rviz', default_value='true'),
        GroupAction(condition=ground_truth, actions=[
            Node(package='nav2_map_server', executable='map_server', name='map_server', output='screen',
                 parameters=[params, {'yaml_filename': LaunchConfiguration('map'), 'use_sim_time': True}]),
            Node(package='nav2_lifecycle_manager', executable='lifecycle_manager', name='lifecycle_manager_localization',
                 output='screen', parameters=[{'use_sim_time': True, 'autostart': True, 'node_names': ['map_server']}]),
            Node(package='tf2_ros', executable='static_transform_publisher', name='map_to_odom', output='screen',
                 arguments=['--frame-id', 'map', '--child-frame-id', 'odom'], parameters=[{'use_sim_time': True}]),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(os.path.join(nav2, 'launch', 'navigation_launch.py')),
                launch_arguments={'params_file': params, 'use_sim_time': 'true', 'autostart': 'true',
                                  'use_composition': 'False'}.items()),
        ]),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(nav2, 'launch', 'bringup_launch.py')),
            launch_arguments={'map': LaunchConfiguration('map'), 'params_file': params,
                              'use_sim_time': 'true', 'autostart': 'true'}.items(),
            condition=amcl),
        Node(package='rviz2', executable='rviz2', output='screen',
             arguments=['-d', os.path.join(nav2, 'rviz', 'nav2_default_view.rviz')],
             parameters=[{'use_sim_time': True}], condition=IfCondition(LaunchConfiguration('rviz'))),
    ])
