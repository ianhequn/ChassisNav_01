# chassis_bringup

`chassis_bringup` 负责 Nav2 定位、导航和 SLAM 的启动编排，并存放参数、地图和 RViz 配置。

主要目录：

```text
launch/   启动文件
params/   Nav2 与 slam_toolbox 参数
maps/     静态地图
rviz/     RViz 配置
scripts/  辅助节点
```

## 启动关系

`chassis_sim` 通过 `bringup_launch.py` 进入本包，再按参数选择：

- `slam:=False` → `localization_launch.py`（静态地图 + AMCL）
- `slam:=True use_lifelong:=False` → `slam_launch.py` 中的 `online_sync` 分支
- `slam:=True use_lifelong:=True` → `slam_launch.py` 中的终身建图分支

终身建图分支包含：

- `slam_toolbox_lifelong_launch.py`：`lifelong_slam_toolbox_node`
- `params/slam_lifelong_params.yaml`：终身建图参数
- `scripts/slam_map_autosave.py`：定时保存节点

## 终身建图参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `use_lifelong` | `False` | 仅在 `slam:=True` 时生效 |
| `load_previous_map` | `False` | 加载上次 posegraph 继续建图 |
| `map_save_dir` | `~/.ros/chassis_slam` | 存档目录 |
| `map_file_prefix` | `chassis_map` | 文件名前缀，不含扩展名 |
| `autosave_interval` | `30.0` | 自动保存间隔（秒），`0` = 关闭 |

## 存档文件

默认保存到 `~/.ros/chassis_slam/`：

| 文件 | 来源 | 用途 |
|---|---|---|
| `chassis_map.posegraph` | `serialize_map` | 下次续建 |
| `chassis_map.data` | `serialize_map` | 下次续建 |
| `chassis_map.pgm` | `save_map` | Nav2 静态地图 |
| `chassis_map.yaml` | `save_map` | Nav2 地图元数据 |

自动保存节点每 `autosave_interval` 秒调用一次：

```text
/slam_toolbox/serialize_map  (slam_toolbox/srv/SerializePoseGraph)
/slam_toolbox/save_map       (slam_toolbox/srv/SaveMap)
```

`save_map` 执行期间 slam_toolbox 会短暂停顿约 1–2 秒，属正常现象。

### 手动保存

```bash
PREFIX="$HOME/.ros/chassis_slam/chassis_map"

ros2 service call /slam_toolbox/serialize_map \
  slam_toolbox/srv/SerializePoseGraph "{filename: '$PREFIX'}"

ros2 service call /slam_toolbox/save_map \
  slam_toolbox/srv/SaveMap "{name: {data: '$PREFIX'}}"
```

### 续建

```bash
ros2 launch chassis_sim chassis_sim.launch.py \
  slam:=True use_lifelong:=True load_previous_map:=True \
  headless:=False
```

只有 `.posegraph` 和 `.data` **同时存在**时才会加载；缺任意一个会警告并从零建图。
加载起始位姿固定为 `[0, 0, 0]`，对应当前仿真固定出生点。

## 注意

- 不要修改 `params/nav2_params.yaml` 来放终身建图参数。
  `slam_launch.py` 用 `HasNodeParams` 判断是否把整份参数传给原 `online_sync` 分支，
  混入 `slam_toolbox:` 段会改变原有 `slam:=True` 行为。
- 终身建图参数使用独立的 `params/slam_lifelong_params.yaml`。
- `map_name` 是 slam_toolbox 的“地图话题名”参数，不是文件名前缀；本包用 `map_file_prefix`。
- 损坏或来自其他机器人配置的 `.posegraph` 可能导致 slam_toolbox 直接退出，
  只加载本仿真产生的存档。
