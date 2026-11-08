import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'diwali_festival'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
        (os.path.join('share', package_name, 'config'), glob('config/*.yaml')),
        (os.path.join('share', package_name, 'sounds'), glob('sounds/*.wav')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Diwali Sim Maintainer',
    maintainer_email='dev@example.com',
    description='Festival event manager: fireworks, lighting and sound control for the Diwali Gazebo world.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'festival_manager = diwali_festival.festival_manager:main',
            'cracker_tour = diwali_festival.cracker_tour:main',
            'cracker_show = diwali_festival.cracker_show:main',
        ],
    },
)
