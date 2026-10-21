# Copyright (C) 2023 Open Source Robotics Foundation
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

"""This is all-in-one launch script intended for use by nav2 developers."""
# 上面这行英文是原文件自带的说明：这是一个“一把梭”启动脚本，源自 nav2_bringup。
# 我们的改动只有一处：第 41 行把 nav2_bringup 换成了 chassis_bringup。

import os          # 用来拼文件路径（os.path.join）
import tempfile    # 用来生成临时文件名（给 world 的 sdf 用）

# 这个函数：给它包名，它告诉你这个包装在哪（返回 .../install/share/<包名> 这种路径）
# ROS 2 里想拿“别的包里的文件”，必须用它，不能自己写死路径，否则换台机器就废了
from ament_index_python.packages import get_package_share_directory

# LaunchDescription = 一张“待办清单”。ros2 launch 读进来后，按清单从上到下执行
from launch import LaunchDescription

# 下面这 5 个都是“清单条目”的类型，每个代表一种动作
from launch.actions import (
    DeclareLaunchArgument,     # 声明一个启动参数（名字 + 默认值 + 说明），让命令行能传进来
    ExecuteProcess,            # 起一个普通系统进程（不是 ROS 节点），比如 xacro、gz
    IncludeLaunchDescription,  # 把另一个 launch 文件整个“搬”进来一起跑
    OpaqueFunction,            # 把一段任意 Python 代码包成清单条目（这里用来删临时文件）
    RegisterEventHandler,      # 注册“出某件事时执行什么”的回调（这里监听关机）
)

from launch.conditions import IfCondition   # 条件判断：某个参数为真才执行这一条
from launch.event_handlers import OnShutdown  # 事件类型：launch 关闭/收到 Ctrl-C 时触发
from launch.launch_description_sources import PythonLaunchDescriptionSource
# 上面这个：告诉 IncludeLaunchDescription“我要 include 的是个 .launch.py 文件”（不是 xml/yaml）

from launch.substitutions import LaunchConfiguration, PythonExpression
# LaunchConfiguration：参数名 → 占位符（运行时才去取值，不是现在取）
# PythonExpression：把字符串拼成一个小 Python 表达式求值，用来写“A and not B”这种条件

from launch_ros.actions import Node   # Node = 起一个 ROS 2 节点（比 ExecuteProcess 多懂 ROS 参数、重映射）


def generate_launch_description():
    # ↑ ros2 launch 约定的入口函数，必须叫这个名字，必须返回一个 LaunchDescription。
    #   注意：这个函数在你敲下命令、解析文件时就会执行一遍，里面的值在这一刻就算好了。

    # 拿到三个关键目录（都是“安装后”的路径，不是 src 里的路径）
    bringup_dir = get_package_share_directory('chassis_bringup')    # 导航/定位那一层的包（我们抄的那套）
    launch_dir = os.path.join(bringup_dir, 'launch')                # 它的 launch 子目录，一会儿 include 兄弟文件用
    sim_dir = get_package_share_directory('nav2_minimal_tb3_sim')   # TB3 的模型、世界、桥接配置，直接用系统里现成的

    # ↓↓↓ 下面这一堆 LaunchConfiguration 只是“占位符”，不是真值 ↓↓↓
    # 它们的作用：让后面的 Node/Include 能引用“叫这个名字的参数”，
    # 至于这个参数到底是多少，要等 launch 执行时才去查（命令行传的 > 声明的默认值）
    slam = LaunchConfiguration('slam')                      # 是否用 SLAM 建图（而不是加载现成地图）
    namespace = LaunchConfiguration('namespace')            # 命名空间，多机器人时才用，单机就是空
    use_namespace = LaunchConfiguration('use_namespace')    # 是否真的启用命名空间
    map_yaml_file = LaunchConfiguration('map')              # 地图 yaml 的路径
    use_sim_time = LaunchConfiguration('use_sim_time')      # 是否用仿真时钟（Gazebo 的 /clock）当时间源
    params_file = LaunchConfiguration('params_file')        # Nav2 的参数文件（所有节点的参数都在这一个文件里）
    autostart = LaunchConfiguration('autostart')            # 是否自动把 Nav2 节点从“未配置”拉到“已激活”
    use_composition = LaunchConfiguration('use_composition')# 是否把所有 Nav2 节点塞进一个进程（省内存）
    use_respawn = LaunchConfiguration('use_respawn')        # 节点挂了是否自动重启（只在非 composition 时有效）

    # ↓ 这几个是“仿真专属”的参数
    rviz_config_file = LaunchConfiguration('rviz_config_file')  # RViz 用哪个 .rviz 布局文件
    use_simulator = LaunchConfiguration('use_simulator')        # 是否真的启动 Gazebo
    use_robot_state_pub = LaunchConfiguration('use_robot_state_pub')  # 是否启动 robot_state_publisher
    use_rviz = LaunchConfiguration('use_rviz')                  # 是否启动 RViz
    headless = LaunchConfiguration('headless')                  # 无头模式：True=只有物理引擎，没有画面
    world = LaunchConfiguration('world')                        # 世界文件（.sdf.xacro）路径

    # 机器人的出生位姿。这里直接给了 default，因为这些参数没在下面用 DeclareLaunchArgument 正式声明，
    # 靠 LaunchConfiguration 自带的 default 兜底（命令行仍然可以传 x_pose:=... 覆盖）
    pose = {
        'x': LaunchConfiguration('x_pose', default='-2.00'),   # 出生点 x（米）
        'y': LaunchConfiguration('y_pose', default='-0.50'),   # 出生点 y（米）
        'z': LaunchConfiguration('z_pose', default='0.01'),    # 出生点 z（米），抬高 1cm 防止一出生就陷进地面
        'R': LaunchConfiguration('roll', default='0.00'),      # 翻滚角（绕 x 轴，弧度）
        'P': LaunchConfiguration('pitch', default='0.00'),     # 俯仰角（绕 y 轴，弧度）
        'Y': LaunchConfiguration('yaw', default='0.00'),       # 偏航角（绕 z 轴，弧度），0 = 朝 x 正方向
    }
    robot_name = LaunchConfiguration('robot_name')   # 机器人在 Gazebo 里的名字（也是话题名前缀的一部分）
    robot_sdf = LaunchConfiguration('robot_sdf')     # 机器人模型文件（.sdf.xacro），决定它长什么样、有什么传感器

    # 重映射表：把全名的 /tf 映射成相对名 tf。
    # 为什么？因为一旦用了命名空间 /robot1，节点默认会去发 /robot1/tf，
    # 那样每个机器人就有一棵独立的 TF 树，Nav2 就找不到统一的坐标关系了。
    # 这里强制它们都发全局的 /tf，保证全栈共用一棵树。
    remappings = [('/tf', 'tf'), ('/tf_static', 'tf_static')]

    # ↓↓↓ 从这里开始才是“正式声明”参数：给出类型以外的信息（默认值、说明），并让 --show-args 能看到 ↓↓↓

    # 声明 namespace 参数：默认空字符串（= 没有命名空间），说明文字是给 --show-args 看的
    declare_namespace_cmd = DeclareLaunchArgument(
        'namespace', default_value='', description='Top-level namespace'
    )

    # 声明 use_namespace：默认 false，即不启用命名空间
    declare_use_namespace_cmd = DeclareLaunchArgument(
        'use_namespace',
        default_value='false',
        description='Whether to apply a namespace to the navigation stack',
    )

    # 声明 slam：默认 False，走“加载现成地图 + AMCL 定位”这条分支；True 则走 slam_toolbox 建图分支
    declare_slam_cmd = DeclareLaunchArgument(
        'slam', default_value='False', description='Whether run a SLAM'
    )

    # 声明地图路径：默认用 chassis_bringup 包里的 maps/tb3_sandbox.yaml
    # （这个默认值之所以指向 chassis_bringup，就是因为第 41 行把 bringup_dir 改成了它）
    declare_map_yaml_cmd = DeclareLaunchArgument(
        'map',
        default_value=os.path.join(bringup_dir, 'maps', 'tb3_sandbox.yaml'),
    )

    # 声明 use_sim_time：默认 true。仿真里必须为 true，否则节点用自己的墙钟时间，
    # 和 Gazebo 的仿真时间对不上，TF 会报 "extrapolation"（时间戳跑到未来/过去）
    declare_use_sim_time_cmd = DeclareLaunchArgument(
        'use_sim_time',
        default_value='true',
        description='Use simulation (Gazebo) clock if true',
    )

    # 声明参数文件路径：默认 chassis_bringup/params/nav2_params.yaml
    # 注意：Nav2 所有节点（十几个）共用这一个 yaml，靠节点名区分各自的段
    declare_params_file_cmd = DeclareLaunchArgument(
        'params_file',
        default_value=os.path.join(bringup_dir, 'params', 'nav2_params.yaml'),
        description='Full path to the ROS2 parameters file to use for all launched nodes',
    )

    # 声明 autostart：默认 true，即启动后自动把节点从 unconfigured 拉到 active。
    # 设 false 的话，节点会停在 unconfigured，得手动 ros2 lifecycle set 一个个激活
    declare_autostart_cmd = DeclareLaunchArgument(
        'autostart',
        default_value='true',
        description='Automatically startup the nav2 stack',
    )

    # 声明 use_composition：默认 True（所有 Nav2 节点装进一个容器进程）。
    # 我们运行时传 False，让每个节点独立成进程，方便看日志、方便单独杀
    declare_use_composition_cmd = DeclareLaunchArgument(
        'use_composition',
        default_value='True',
        description='Whether to use composed bringup',
    )

    # 声明 use_respawn：默认 False，节点崩了不自动重启（只在 use_composition=False 时有意义）
    declare_use_respawn_cmd = DeclareLaunchArgument(
        'use_respawn',
        default_value='False',
        description='Whether to respawn if a node crashes. Applied when composition is disabled.',
    )

    # 声明 RViz 配置文件路径：默认 chassis_bringup/rviz/nav2_default_view.rviz
    # （里面预设了要显示哪些话题、哪些图层）
    declare_rviz_config_file_cmd = DeclareLaunchArgument(
        'rviz_config_file',
        default_value=os.path.join(bringup_dir, 'rviz', 'nav2_default_view.rviz'),
        description='Full path to the RVIZ config file to use',
    )

    # 声明 use_simulator：默认 True。设 False 可以“不开 Gazebo，只起 Nav2”，用来单独调导航
    declare_use_simulator_cmd = DeclareLaunchArgument(
        'use_simulator',
        default_value='True',
        description='Whether to start the simulator',
    )

    # 声明 use_robot_state_pub：默认 True，即启动 robot_state_publisher（机器人内部关节/连杆 TF 的来源）
    declare_use_robot_state_pub_cmd = DeclareLaunchArgument(
        'use_robot_state_pub',
        default_value='True',
        description='Whether to start the robot state publisher',
    )

    # 声明 use_rviz：默认 True，即自动弹 RViz
    declare_use_rviz_cmd = DeclareLaunchArgument(
        'use_rviz', default_value='True', description='Whether to start RVIZ'
    )

    # 声明 headless：默认 True，即不带画面。
    # 我们不传它就永远看不到 GUI，而且 world 文件里也会少加载一个关键插件（见下面第 214 行附近）
    declare_simulator_cmd = DeclareLaunchArgument(
        'headless', default_value='True', description='Whether to execute gzclient)'
    )

    # 声明世界文件：默认用 TB3 包里的 tb3_sandbox.sdf.xacro（一个带墙的沙盒世界）
    # 之所以是 .xacro 不是 .sdf，是因为它要根据 headless 决定加不加载 SceneBroadcaster 插件
    declare_world_cmd = DeclareLaunchArgument(
        'world',
        default_value=os.path.join(sim_dir, 'worlds', 'tb3_sandbox.sdf.xacro'),
        description='Full path to world model file to load',
    )

    # 声明机器人名字：默认 turtlebot3_waffle。这个名字会成为 Gazebo 里实体的名字，
    # 也会影响部分话题名（比如 /model/turtlebot3_waffle/...）
    declare_robot_name_cmd = DeclareLaunchArgument(
        'robot_name', default_value='turtlebot3_waffle', description='name of the robot'
    )

    # 声明机器人模型文件：默认 TB3 包里的 gz_waffle.sdf.xacro（SDF 格式，给 Gazebo 用）
    declare_robot_sdf_cmd = DeclareLaunchArgument(
        'robot_sdf',
        default_value=os.path.join(sim_dir, 'urdf', 'gz_waffle.sdf.xacro'),
        description='Full path to robot sdf file to spawn the robot in gazebo',
    )

    # 注意！下面这行是“解析文件时”就执行的：读 URDF 文本，读进内存变成字符串。
    # 这里必须用 URDF（不是 SDF），因为 robot_state_publisher 只认 URDF，用来算连杆之间的 TF
    urdf = os.path.join(sim_dir, 'urdf', 'turtlebot3_waffle.urdf')
    with open(urdf, 'r') as infp:   # 打开文件
        robot_description = infp.read()   # 整个读成一个大字符串

    # 起 robot_state_publisher 节点：它的唯一工作是把 URDF + 关节角 变成 TF
    # 具体说：发出 base_footprint→base_link、base_link→base_scan、base_link→camera_link 这些静态关系
    start_robot_state_publisher_cmd = Node(
        condition=IfCondition(use_robot_state_pub),  # use_robot_state_pub 为真才起
        package='robot_state_publisher',            # 属于哪个包
        executable='robot_state_publisher',         # 跑包里的哪个可执行文件
        name='robot_state_publisher',               # 节点名（ros2 node list 看到的就是它）
        namespace=namespace,                        # 套不套命名空间
        output='screen',                            # 日志直接打到当前终端（不写日志文件）
        parameters=[
            # 两个参数：仿真时间开关 + 上面读进来的 URDF 字符串
            {'use_sim_time': use_sim_time, 'robot_description': robot_description}
        ],
        remappings=remappings,                      # 套用前面那张 /tf 重映射表
    )

    # 把 RViz 的 launch 文件内联进来（注意：这是“起 rviz2”的另一个文件，不是节点本身）
    rviz_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'rviz_launch.py')),  # 要 include 的文件路径
        condition=IfCondition(use_rviz),   # 只有 use_rviz 为真才起
        launch_arguments={
            # 显式把这些参数传给被 include 的文件（不传它就用它自己的默认值）
            'namespace': namespace,
            'use_namespace': use_namespace,
            'use_sim_time': use_sim_time,
            'rviz_config': rviz_config_file,
        }.items(),   # .items() 把字典变成 (键, 值) 序列，launch 要求的格式
    )

    # 把导航/定位那一层（我们抄的 bringup_launch.py）内联进来。
    # 这一步才是真正起那 14 个 Nav2 节点的入口
    bringup_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(launch_dir, 'bringup_launch.py')),
        launch_arguments={
            # 一个个往下传。参数名必须和下层文件里的名字完全一致，否则传了也白传
            'namespace': namespace,
            'use_namespace': use_namespace,
            'slam': slam,
            'map': map_yaml_file,
            'use_sim_time': use_sim_time,
            'params_file': params_file,
            'autostart': autostart,
            'use_composition': use_composition,
            'use_respawn': use_respawn,
        }.items(),
    )
    # The SDF file for the world is a xacro file because we wanted to
    # conditionally load the SceneBroadcaster plugin based on wheter we're
    # running in headless mode. But currently, the Gazebo command line doesn't
    # take SDF strings for worlds, so the output of xacro needs to be saved into
    # a temporary file and passed to Gazebo.
    # ↑ 官方注释翻译：世界文件之所以写成 xacro，是因为要“根据 headless 决定加不加载 SceneBroadcaster 插件”。
    #   但 gz 命令行只接受“文件路径”，不接受一段 SDF 文本，所以只能先把 xacro 展开、存成临时文件。

    # 要一个临时文件路径（/tmp/nav2_xxxxxx.sdf）。注意它此时只是“名字”，文件还不存在
    world_sdf = tempfile.mktemp(prefix='nav2_', suffix='.sdf')

    # 起一个普通进程执行 xacro：把 .sdf.xacro 展开成真正的 .sdf 写到上面那个临时路径。
    # 这是一条“同步阻塞”的动作：launch 会等 xacro 跑完才继续往下走
    world_sdf_xacro = ExecuteProcess(
        cmd=['xacro', '-o', world_sdf, ['headless:=', headless], world])
        # cmd 各部分：xacro 程序、-o 输出文件、输出到哪、传参数 headless:=True/False、输入文件是哪个

    # 起 Gazebo 服务端（没有画面的那个，负责物理计算）。
    # -r = 立刻开始跑（不暂停）；-s = server only，只起服务端，不起界面
    gazebo_server = ExecuteProcess(
        cmd=['gz', 'sim', '-r', '-s', world_sdf],
        output='screen',                       # 它的输出直接打到终端
        condition=IfCondition(use_simulator)   # use_simulator 为真才起
    )

    # 注册一个“关机时执行”的回调：删掉上面那个临时 sdf 文件，免得 /tmp 越积越多。
    # 注意：只有正常关闭（Ctrl-C）才会执行；被 kill -9 或进程变孤儿就不会，文件会留在 /tmp
    remove_temp_sdf_file = RegisterEventHandler(event_handler=OnShutdown(
        on_shutdown=[
            # OpaqueFunction 用来塞一段自定义 Python：lambda 收到上下文参数（用 _ 忽略），执行 os.remove
            OpaqueFunction(function=lambda _: os.remove(world_sdf))
        ]))

    # 起 Gazebo 客户端（就是那个有画面的窗口）。这是通过 include ros_gz_sim 的 launch 文件起的，
    # 不是直接跑 gz 命令，所以传参方式不同
    gazebo_client = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(get_package_share_directory('ros_gz_sim'),
                         'launch',
                         'gz_sim.launch.py')     # ros_gz_sim 包自带的、专门起 gz 窗口的 launch 文件
        ),
        # 条件：use_simulator 为真【并且】headless 为假，才起窗口。
        # PythonExpression 把字符串拼成表达式求值，这里拼出来的是 "True and not False" 这种
        condition=IfCondition(PythonExpression(
            [use_simulator, ' and not ', headless])),
        # 传给 gz 的命令行参数：-v4 日志级别，-g 只起界面（连到已有的 server 上）
        launch_arguments={'gz_args': ['-v4 -g ']}.items(),
    )

    # 把 spawn（生成机器人）的 launch 文件内联进来。它里面干两件事：
    #   1) 起 ros_gz_bridge 做 ROS ↔ Gazebo 的话题翻译
    #   2) 起 ros_gz_sim 的 create 节点，在 Gazebo 世界里“造”一个机器人
    gz_robot = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(sim_dir, 'launch', 'spawn_tb3.launch.py')),
        launch_arguments={
            'namespace': namespace,
            'use_sim_time': use_sim_time,
            'robot_name': robot_name,
            'robot_sdf': robot_sdf,      # 机器人模型文件（决定有几轮子、有没有雷达）
            'x_pose': pose['x'],         # 出生位姿，一个个传下去
            'y_pose': pose['y'],
            'z_pose': pose['z'],
            'roll': pose['R'],
            'pitch': pose['P'],
            'yaw': pose['Y'],
        }.items(),
    )

    # ↓↓↓ 下面开始“建清单”：把上面准备好的动作按顺序塞进去 ↓↓↓
    # 注意：这里只是往清单里加，并不是执行。真正执行是在函数返回之后，由 launch 统一调度
    ld = LaunchDescription()

    # 先声明所有参数。必须排在前面，因为后面的动作要用到这些参数名
    ld.add_action(declare_namespace_cmd)
    ld.add_action(declare_use_namespace_cmd)
    ld.add_action(declare_slam_cmd)
    ld.add_action(declare_map_yaml_cmd)
    ld.add_action(declare_use_sim_time_cmd)
    ld.add_action(declare_params_file_cmd)
    ld.add_action(declare_autostart_cmd)
    ld.add_action(declare_use_composition_cmd)

    ld.add_action(declare_rviz_config_file_cmd)
    ld.add_action(declare_use_simulator_cmd)
    ld.add_action(declare_use_robot_state_pub_cmd)
    ld.add_action(declare_use_rviz_cmd)
    ld.add_action(declare_simulator_cmd)
    ld.add_action(declare_world_cmd)
    ld.add_action(declare_robot_name_cmd)
    ld.add_action(declare_robot_sdf_cmd)
    ld.add_action(declare_use_respawn_cmd)

    # 然后按顺序放“真正干活”的动作
    ld.add_action(world_sdf_xacro)     # 1. 展开 world 成临时 sdf（会等它跑完）
    ld.add_action(remove_temp_sdf_file)# 2. 注册关机删文件的回调
    ld.add_action(gz_robot)            # 3. 起 bridge + create（create 会自己等 server 就绪）
    ld.add_action(gazebo_server)       # 4. 起 Gazebo 服务端（物理）
    ld.add_action(gazebo_client)       # 5. 起 Gazebo 窗口（headless=False 才有）

    # Add the actions to launch all of the navigation nodes
    ld.add_action(start_robot_state_publisher_cmd)  # 6. 起 robot_state_publisher（发机器人内部 TF）
    ld.add_action(rviz_cmd)                         # 7. 起 RViz
    ld.add_action(bringup_cmd)                      # 8. 起 Nav2（定位 + 导航，14 个组件）

    # 把清单交回去，launch 拿到后开始一条条执行
    return ld
