from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from ament_index_python.packages import get_package_share_directory
import os


def generate_launch_description():
    share = get_package_share_directory('diwali_festival')
    return LaunchDescription([
        DeclareLaunchArgument('autonomous', default_value='true',
                              description='Mode A: trigger fireworks automatically'),
        DeclareLaunchArgument('sound', default_value='true'),
        DeclareLaunchArgument('lights_file', default_value='',
                              description='YAML with controllable Gazebo lights (diwali_sim/config/festival_lights.yaml)'),
        DeclareLaunchArgument('force_gz_cli', default_value='false'),
        Node(package='diwali_festival', executable='festival_manager', name='festival_manager',
             output='screen',
             parameters=[os.path.join(share, 'config', 'festival_params.yaml'), {
                 'autonomous': ParameterValue(LaunchConfiguration('autonomous'), value_type=bool),
                 'sound_enabled': ParameterValue(LaunchConfiguration('sound'), value_type=bool),
                 'force_gz_cli': ParameterValue(LaunchConfiguration('force_gz_cli'), value_type=bool),
                 'lights_file': ParameterValue(LaunchConfiguration('lights_file'), value_type=str),
             }]),
        Node(package='diwali_festival', executable='cracker_show', name='cracker_show', output='screen',
             parameters=[{'sound_enabled': ParameterValue(LaunchConfiguration('sound'), value_type=bool),
                          'force_gz_cli': ParameterValue(LaunchConfiguration('force_gz_cli'), value_type=bool)}]),
    ])
