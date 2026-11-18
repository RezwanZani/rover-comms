import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'rover_telemetry'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Rover Team',
    maintainer_email='rover@team.org',
    description='Aggregates telemetry from rover topics and broadcasts over XBee and Network UDP.',
    license='Apache-2.0',
    entry_points={
        'console_scripts': [
            'telemetry_node = rover_telemetry.telemetry_node:main',
        ],
    },
)
