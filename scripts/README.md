# ROS2 Discovery Server 脚本

> 用途：在 **NAT / 跨网段 / WSL2** 等组播不通的环境下，用一个中心发现服务器牵线，
> 让本机(VM)、WSL2、底盘等各端互相发现，绕开 DDS 默认组播自动发现。

## 目录内容

| 文件 | 作用 |
| --- | --- |
| `run_discovery_server.sh` | 启动 Discovery Server（常驻，占一个终端） |
| `ros_discovery_env.sh` | 把当前 shell 设为客户端（本机 / WSL2 通用） |

## 前置

- ROS2 Jazzy 已装（脚本内已 `source /opt/ros/jazzy/setup.bash`）。
- 默认 RMW 即 `rmw_fastrtps_cpp`（Jazzy 自带），无需额外安装。

## 使用步骤

### 1. 起服务器（本机 VM，专用终端常驻）
```bash
cd ~/MyTest/dev01/ros2/test_ws01/scripts
./run_discovery_server.sh
# 可选：只绑某网卡 / 改端口
./run_discovery_server.sh 192.168.106.137 11811
```
- 默认监听 `0.0.0.0:11811/udp`，`server-id=0`。
- 终端保持打开；`Ctrl-C` 停止。所有客户端都连它，**它必须先起**。

### 2. 客户端环境（**每个**要参与 ROS2 的终端）
本机与 WSL2 步骤相同，`source` 后变量留在当前 shell：
```bash
source /opt/ros/jazzy/setup.bash
source ~/MyTest/dev01/ros2/test_ws01/scripts/ros_discovery_env.sh <服务器IP> [端口] [DOMAIN_ID]
```
示例：
- 1
```bash
source ./ros_discovery_env.sh 192.168.174.128        # 默认端口 11811、DOMAIN_ID 0
```
- ##### VM
```bash
source /home/u24/MyTest/dev01/ros2/test_ws01/scripts/ros_discovery_env.sh 10.144.144.3        # 默认端口 11811、DOMAIN_ID 0
```
- ##### WSL2
```bash
source /home/omen/MyWork/Robot/ros2/ChassisNav_01/scripts/ros_discovery_env.sh 10.144.144.3        # 默认端口 11811、DOMAIN_ID 0
```
等价于手动设置：
```bash
export ROS_DISCOVERY_SERVER=192.168.106.137:11811
export ROS_DOMAIN_ID=0
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
```

### 3. 验证发现已打通
- VM 终端 A：`ros2 topic pub -r 2 /disc_test std_msgs/msg/String "{data: hi}"`
- VM 或 WSL2 终端 B：`ros2 topic echo /disc_test std_msgs/msg/String`

两边都做过步骤 2 后能收到 → 发现链路 OK。

## 选哪个服务器 IP
- VM 默认路由走 `ens33 = 192.168.106.137`，优先用它。
- 若 WSL2 连不上，改试 `ens37 = 192.168.174.128`。
- 以 **WSL2 侧实测能通**为准（步骤 3 能过即可）。

## 约束与注意事项

- **各端必须一致**：`ROS_DOMAIN_ID`、`RMW_IMPLEMENTATION`、端口。
- `ros_discovery_env.sh` 必须用 `source` 调用（不是 `./`），否则变量出不了当前 shell。
- **发现 ≠ 数据双向通**：发现服务器解决“互相发现”，但实际数据仍由发布方向订阅方地址发送。
  WSL2 默认 NAT 下外部无法主动连入 WSL2；若出现“本机互通、WSL2 收不到”，
  需另处理（WSL2 镜像网络 `networkingMode=mirrored` 或端口转发）。当前阶段暂不涉及。
