"""Stage 4: world + festival + robot + (Nav2 on the saved map | SLAM Toolbox | nothing)."""
import os

from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, LogInfo, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression


def generate_launch_description():
    sim = get_package_share_directory('diwali_sim')
    robot = get_package_share_directory('diwali_robot')
    mode = LaunchConfiguration('mode')
    missing = []
    for pkg in ('nav2_bringup', 'slam_toolbox'):
        try:
            get_package_share_directory(pkg)
        except PackageNotFoundError:
            missing.append(pkg)
    base = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(sim, 'launch', 'diwali_robot.launch.py')),
        launch_arguments={'festival': 'true', 'autonomous': LaunchConfiguration('autonomous'),
                          'sound': LaunchConfiguration('sound'), 'headless': LaunchConfiguration('headless')}.items())
    nav = TimerAction(period=14.0, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(robot, 'launch', 'nav2.launch.py')),
        launch_arguments={'map': LaunchConfiguration('map'), 'rviz': LaunchConfiguration('rviz'),
                          'localization': LaunchConfiguration('localization')}.items(),
        condition=IfCondition(PythonExpression(["'", mode, "' == 'nav2'"])))])
    slam = TimerAction(period=14.0, actions=[IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(robot, 'launch', 'slam.launch.py')),
        condition=IfCondition(PythonExpression(["'", mode, "' == 'slam'"])))])
    return LaunchDescription([
        DeclareLaunchArgument('mode', default_value='nav2', description='nav2 | slam | none'),
        DeclareLaunchArgument('map', default_value=os.path.join(robot, 'maps', 'diwali_street.yaml')),
        DeclareLaunchArgument('localization', default_value='ground_truth', description='ground_truth | amcl'),
        DeclareLaunchArgument('rviz', default_value='true'),
        DeclareLaunchArgument('autonomous', default_value='true'),
        DeclareLaunchArgument('sound', default_value='true'),
        DeclareLaunchArgument('headless', default_value='false'),
        base,
        *([] if 'nav2_bringup' in missing else [nav]),
        *([] if 'slam_toolbox' in missing else [slam]),
        *([LogInfo(msg='[diwali] Missing ROS packages: ' + ', '.join(missing) + '. Nav2/SLAM skipped, so the robot '
                   'will not drive the cracker tour. Install with: sudo apt install ros-jazzy-navigation2 '
                   'ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox')] if missing else []),
    ])
