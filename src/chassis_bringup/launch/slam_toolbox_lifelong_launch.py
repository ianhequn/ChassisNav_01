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

"""Launch slam_toolbox in lifelong mode.

Jazzy 的 deb 包没有安装官方仓库里的 lifelong_launch.py，所以这里按官方实现
补一份，并额外支持：
  - 从 map_save_dir / map_file_prefix 计算 map_file_name；
  - 只有 .posegraph 和 .data 同时存在时才加载，避免半份存档导致节点异常；
  - 通过 Node parameters 注入 map_start_pose（不能放 launch_arguments）。
"""

import os
import re

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import (
    DeclareLaunchArgument,
    EmitEvent,
    LogInfo,
    OpaqueFunction,
    RegisterEventHandler,
)
from launch.conditions import IfCondition
from launch.events import matches_action
from launch.substitutions import (
    AndSubstitution,
    LaunchConfiguration,
    NotSubstitution,
)
from launch_ros.actions import LifecycleNode
from launch_ros.event_handlers import OnStateTransition
from launch_ros.events.lifecycle import ChangeState
from lifecycle_msgs.msg import Transition


# 与 slam_toolbox 的 save_map 服务内部正则保持一致：
# 目录允许 / . _ -，文件名前缀不允许 /。
_PATH_RE = re.compile(r'^[A-Za-z0-9_./-]+$')
_PREFIX_RE = re.compile(r'^[A-Za-z0-9_.-]+$')


def _is_true(value):
    """把 launch 参数（字符串）转成 bool。"""
    return str(value).strip().lower() in ('true', '1', 'yes', 'on')


def _start_node(context, *args, **kwargs):
    """在运行时解析路径、检查存档，然后创建终身建图节点。"""
    autostart = LaunchConfiguration('autostart')
    use_lifecycle_manager = LaunchConfiguration('use_lifecycle_manager')
    use_sim_time = LaunchConfiguration('use_sim_time')
    slam_params_file = LaunchConfiguration('slam_params_file')

    load_previous_map = _is_true(
        LaunchConfiguration('load_previous_map').perform(context)
    )
    save_dir = os.path.abspath(os.path.expanduser(
        LaunchConfiguration('map_save_dir').perform(context)
    ))
    prefix = LaunchConfiguration('map_file_prefix').perform(context).strip()

    notes = []
    map_file = ''

    # 只有用户明确要求续建时才检查/加载；默认 false 保证从零开始。
    if load_previous_map:
        if not _PREFIX_RE.match(prefix):
            notes.append(LogInfo(msg=(
                f'[slam_toolbox_lifelong] invalid map_file_prefix "{prefix}": '
                'only [A-Za-z0-9_.-] are allowed; starting from scratch.'
            )))
        elif not _PATH_RE.match(save_dir):
            notes.append(LogInfo(msg=(
                f'[slam_toolbox_lifelong] invalid map_save_dir "{save_dir}": '
                'only [A-Za-z0-9_./-] are allowed; starting from scratch.'
            )))
        else:
            candidate = os.path.join(save_dir, prefix)
            posegraph = candidate + '.posegraph'
            data = candidate + '.data'
            # serialize_map 会写两个文件；只检查 .posegraph 不够。
            if os.path.exists(posegraph) and os.path.exists(data):
                map_file = candidate
                notes.append(LogInfo(msg=(
                    f'[slam_toolbox_lifelong] loading posegraph: {map_file}'
                )))
            else:
                notes.append(LogInfo(msg=(
                    f'[slam_toolbox_lifelong] posegraph not found or incomplete '
                    f'({posegraph} / {data}); starting from scratch.'
                )))

    parameters = [
        slam_params_file,
        {
            'use_lifecycle_manager': use_lifecycle_manager,
            'use_sim_time': use_sim_time,
            # 空字符串表示从零建图；非空时是“不带扩展名”的文件前缀。
            'map_file_name': map_file,
        },
    ]
    if map_file:
        # 必须放在 Node parameters 里；launch_arguments 不会传给节点。
        parameters[1]['map_start_pose'] = [0.0, 0.0, 0.0]

    start_lifelong_slam_toolbox_node = LifecycleNode(
        parameters=parameters,
        package='slam_toolbox',
        executable='lifelong_slam_toolbox_node',
        name='slam_toolbox',
        output='screen',
        namespace='',
    )

    configure_event = EmitEvent(
        event=ChangeState(
            lifecycle_node_matcher=matches_action(start_lifelong_slam_toolbox_node),
            transition_id=Transition.TRANSITION_CONFIGURE,
        ),
        condition=IfCondition(
            AndSubstitution(autostart, NotSubstitution(use_lifecycle_manager))
        ),
    )

    activate_event = RegisterEventHandler(
        OnStateTransition(
            target_lifecycle_node=start_lifelong_slam_toolbox_node,
            start_state='configuring',
            goal_state='inactive',
            entities=[
                LogInfo(msg='[LifecycleLaunch] Slamtoolbox node is activating.'),
                EmitEvent(event=ChangeState(
                    lifecycle_node_matcher=matches_action(
                        start_lifelong_slam_toolbox_node
                    ),
                    transition_id=Transition.TRANSITION_ACTIVATE,
                )),
            ],
        ),
        condition=IfCondition(
            AndSubstitution(autostart, NotSubstitution(use_lifecycle_manager))
        ),
    )

    # notes 放在前面，保证警告先于节点日志打印。
    return notes + [
        start_lifelong_slam_toolbox_node,
        configure_event,
        activate_event,
    ]


def generate_launch_description():
    bringup_dir = get_package_share_directory('chassis_bringup')

    declare_autostart_cmd = DeclareLaunchArgument(
        'autostart', default_value='true',
        description='Automatically startup the slamtoolbox. '
                    'Ignored when use_lifecycle_manager is true.',
    )
    declare_use_lifecycle_manager = DeclareLaunchArgument(
        'use_lifecycle_manager', default_value='false',
        description='Enable bond connection during node activation',
    )
    declare_use_sim_time_argument = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation/Gazebo clock',
    )
    declare_slam_params_file_cmd = DeclareLaunchArgument(
        'slam_params_file',
        default_value=os.path.join(
            bringup_dir, 'params', 'slam_lifelong_params.yaml'
        ),
        description='Full path to the ROS2 parameters file to use for the '
                    'slam_toolbox node',
    )
    declare_load_previous_map_cmd = DeclareLaunchArgument(
        'load_previous_map',
        default_value='False',
        description='Load the previous posegraph and continue mapping',
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

    ld = LaunchDescription()

    ld.add_action(declare_autostart_cmd)
    ld.add_action(declare_use_lifecycle_manager)
    ld.add_action(declare_use_sim_time_argument)
    ld.add_action(declare_slam_params_file_cmd)
    ld.add_action(declare_load_previous_map_cmd)
    ld.add_action(declare_map_save_dir_cmd)
    ld.add_action(declare_map_file_prefix_cmd)

    ld.add_action(OpaqueFunction(function=_start_node))

    return ld
