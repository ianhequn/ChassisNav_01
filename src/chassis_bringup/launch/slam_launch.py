# Copyright (c) 2020 Samsung Research Russia
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, SetParameter, SetRemap
from launch_ros.descriptions import ParameterFile
from launch_ros.parameter_descriptions import ParameterValue
from nav2_common.launch import HasNodeParams, RewrittenYaml


def generate_launch_description():
    # Input parameters declaration
    namespace = LaunchConfiguration('namespace')
    params_file = LaunchConfiguration('params_file')
    use_sim_time = LaunchConfiguration('use_sim_time')
    autostart = LaunchConfiguration('autostart')
    use_respawn = LaunchConfiguration('use_respawn')
    log_level = LaunchConfiguration('log_level')
    use_lifelong = LaunchConfiguration('use_lifelong')
    load_previous_map = LaunchConfiguration('load_previous_map')
    map_save_dir = LaunchConfiguration('map_save_dir')
    map_file_prefix = LaunchConfiguration('map_file_prefix')
    autosave_interval = LaunchConfiguration('autosave_interval')

    # Variables
    lifecycle_nodes = ['map_saver']

    # Getting directories and launch-files
    bringup_dir = get_package_share_directory('chassis_bringup')
    slam_toolbox_dir = get_package_share_directory('slam_toolbox')
    slam_launch_file = os.path.join(slam_toolbox_dir, 'launch', 'online_sync_launch.py')
    lifelong_params_file = os.path.join(bringup_dir, 'params', 'slam_lifelong_params.yaml')

    # Create our own temporary YAML files that include substitutions
    configured_params = ParameterFile(
        RewrittenYaml(
            source_file=params_file,
            root_key=namespace,
            param_rewrites={},
            convert_types=True,
        ),
        allow_substs=True,
    )

    # Declare the launch arguments
    declare_namespace_cmd = DeclareLaunchArgument(
        'namespace', default_value='', description='Top-level namespace'
    )

    declare_params_file_cmd = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(bringup_dir, 'params', 'nav2_params.yaml'),
        description='Full path to the ROS2 parameters file to use for all launched nodes',
    )

    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='True',
        description='Use simulation (Gazebo) clock if true',
    )

    declare_autostart_cmd = DeclareLaunchArgument(
        'autostart',
        default_value='True',
        description='Automatically startup the nav2 stack',
    )

    declare_use_respawn_cmd = DeclareLaunchArgument(
        'use_respawn',
        default_value='False',
        description='Whether to respawn if a node crashes. Applied when composition is disabled.',
    )

    declare_log_level_cmd = DeclareLaunchArgument(
        'log_level', default_value='info', description='log level'
    )

    declare_use_lifelong_cmd = DeclareLaunchArgument(
        'use_lifelong',
        default_value='False',
        description='Use slam_toolbox lifelong mapping instead of online sync mapping',
    )

    declare_load_previous_map_cmd = DeclareLaunchArgument(
        'load_previous_map',
        default_value='False',
        description='Load the previous posegraph and continue lifelong mapping',
    )

    declare_map_save_dir_cmd = DeclareLaunchArgument(
        'map_save_dir',
        default_value='~/.ros/chassis_slam',
        description='Directory used to store/load lifelong maps',
    )

    declare_map_file_prefix_cmd = DeclareLaunchArgument(
        'map_file_prefix',
        default_value='chassis_map',
        description='Map file prefix without extension',
    )

    declare_autosave_interval_cmd = DeclareLaunchArgument(
        'autosave_interval',
        default_value='30.0',
        description='Autosave interval in seconds; 0 disables autosave',
    )

    # Nodes launching commands
    start_map_server = GroupAction(
        actions=[
            SetParameter('use_sim_time', use_sim_time),
            Node(
                package='nav2_map_server',
                executable='map_saver_server',
                output='screen',
                respawn=use_respawn,
                respawn_delay=2.0,
                arguments=['--ros-args', '--log-level', log_level],
                parameters=[configured_params],
            ),
            Node(
                package='nav2_lifecycle_manager',
                executable='lifecycle_manager',
                name='lifecycle_manager_slam',
                output='screen',
                arguments=['--ros-args', '--log-level', log_level],
                parameters=[{'autostart': autostart}, {'node_names': lifecycle_nodes}],
            ),
        ]
    )

    # If the provided param file doesn't have slam_toolbox params, we must remove the 'params_file'
    # LaunchConfiguration, or it will be passed automatically to slam_toolbox and will not load
    # the default file
    has_slam_toolbox_params = HasNodeParams(
        source_file=params_file, node_name='slam_toolbox'
    )

    start_slam_toolbox_cmd = GroupAction(
        condition=UnlessCondition(use_lifelong),
        actions=[
            # Remapping required to have a slam session subscribe & publish in optional namespaces
            SetRemap(src='/scan', dst='scan'),
            SetRemap(src='/tf', dst='tf'),
            SetRemap(src='/tf_static', dst='tf_static'),
            SetRemap(src='/map', dst='map'),

            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(slam_launch_file),
                launch_arguments={'use_sim_time': use_sim_time}.items(),
                condition=UnlessCondition(has_slam_toolbox_params),
            ),

            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(slam_launch_file),
                launch_arguments={'use_sim_time': use_sim_time,
                                  'slam_params_file': params_file}.items(),
                condition=IfCondition(has_slam_toolbox_params),
            )
        ]
    )

    # 终身建图分支：从零开始或加载上次 posegraph，并挂一个定时存图节点。
    # 原 online_sync 分支已被 UnlessCondition(use_lifelong) 包住，两者互斥。
    start_lifelong_slam_cmd = GroupAction(
        condition=IfCondition(use_lifelong),
        actions=[
            SetRemap(src='/scan', dst='scan'),
            SetRemap(src='/tf', dst='tf'),
            SetRemap(src='/tf_static', dst='tf_static'),
            SetRemap(src='/map', dst='map'),

            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(bringup_dir, 'launch', 'slam_toolbox_lifelong_launch.py')
                ),
                launch_arguments={
                    'use_sim_time': use_sim_time,
                    'autostart': autostart,
                    'slam_params_file': lifelong_params_file,
                    'load_previous_map': load_previous_map,
                    'map_save_dir': map_save_dir,
                    'map_file_prefix': map_file_prefix,
                }.items(),
            ),

            Node(
                package='chassis_bringup',
                executable='slam_map_autosave.py',
                name='slam_map_autosave',
                output='screen',
                parameters=[{
                    'save_dir': map_save_dir,
                    'map_file_prefix': map_file_prefix,
                    # LaunchConfiguration 取出来是字符串，这里显式转成 float，
                    # 否则节点参数类型会变成 string。
                    'interval': ParameterValue(
                        autosave_interval, value_type=float),
                    # 用墙钟：Gazebo 暂停时也继续保存。
                    'use_sim_time': False,
                }],
            ),
        ],
    )

    ld = LaunchDescription()

    # Declare the launch options
    ld.add_action(declare_namespace_cmd)
    ld.add_action(declare_params_file_cmd)
    ld.add_action(declare_use_sim_time_cmd)
    ld.add_action(declare_autostart_cmd)
    ld.add_action(declare_use_respawn_cmd)
    ld.add_action(declare_log_level_cmd)
    ld.add_action(declare_use_lifelong_cmd)
    ld.add_action(declare_load_previous_map_cmd)
    ld.add_action(declare_map_save_dir_cmd)
    ld.add_action(declare_map_file_prefix_cmd)
    ld.add_action(declare_autosave_interval_cmd)

    # Running Map Saver Server
    ld.add_action(start_map_server)

    # Running SLAM Toolbox (Only one of them will be run)
    ld.add_action(start_slam_toolbox_cmd)
    ld.add_action(start_lifelong_slam_cmd)

    return ld
