# chassis_sim

`chassis_sim` 是仿真入口包，负责按顺序启动：

1. Gazebo 世界与机器人模型；
2. `ros_gz_bridge`；
3. `robot_state_publisher`；
4. 可选 RViz；
5. `chassis_bringup` 里的 Nav2 / SLAM 栈。

## 编译与加载

```bash
cd /home/omen/MyWork/Robot/ros2/ChassisNav_01
source /opt/ros/jazzy/setup.bash
colcon build --packages-select chassis_bringup chassis_sim
source install/setup.bash
```

## 主入口

```bash
ros2 launch chassis_sim chassis_sim.launch.py
```

常用参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `slam` | `False` | `False` = 静态地图 + AMCL；`True` = SLAM |
| `use_lifelong` | `False` | 仅在 `slam:=True` 时生效，启用终身建图 |
| `load_previous_map` | `False` | 加载上次 posegraph 继续建图 |
| `map_save_dir` | `~/.ros/chassis_slam` | 终身建图存档目录 |
| `map_file_prefix` | `chassis_map` | 存档文件名前缀，不含扩展名 |
| `autosave_interval` | `30.0` | 自动保存间隔（秒），`0` = 关闭 |
| `headless` | `True` | `False` 才打开 Gazebo 窗口 |
| `use_rviz` | `True` | 是否启动 RViz |
| `use_composition` | `True` | Nav2 节点是否装进同一个容器 |

## 运行方式

### 静态地图 + AMCL

```bash
ros2 launch chassis_sim chassis_sim.launch.py \
  slam:=False headless:=False
```

### 原在线建图

```bash
ros2 launch chassis_sim chassis_sim.launch.py \
  slam:=True headless:=False
```

### 终身建图（从零开始，默认自动存图）

```bash
ros2 launch chassis_sim chassis_sim.launch.py \
  slam:=True use_lifelong:=True headless:=False
```

启动后在 RViz 中用 **Nav2 Goal** 连续发目标点，即可边导航边建图。

### 加载上次地图继续建图

```bash
ros2 launch chassis_sim chassis_sim.launch.py \
  slam:=True use_lifelong:=True load_previous_map:=True \
  headless:=False
```

存档目录、自动保存、手动保存等细节见
[`chassis_bringup/README.md`](../chassis_bringup/README.md)。

## 注意

- 默认 `headless:=True`，不显示 Gazebo 画面；需要界面时显式传 `headless:=False`。
- `slam:=False` 时 `use_lifelong:=True` 会被忽略，并打印警告。
- 终身建图是 slam_toolbox 的实验性模式，启动时出现 `experimental` 警告属正常。
