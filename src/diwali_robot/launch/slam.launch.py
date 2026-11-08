"""SLAM Toolbox (online async) for building a map of the street. Needs the robot running."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    share = get_package_share_directory('diwali_robot')
    return LaunchDescription([
        Node(package='slam_toolbox', executable='async_slam_toolbox_node', name='slam_toolbox',
             output='screen', parameters=[os.path.join(share, 'config', 'slam_toolbox.yaml')]),
    ])
