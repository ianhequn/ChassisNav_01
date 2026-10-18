#!/usr/bin/env bash
# =============================================================
# 将当前 shell 设为 Discovery Server 客户端（本机 / WSL2 通用）
# 用法（必须用 source，才能把变量留在当前 shell）：
#   source ros_discovery_env.sh <服务器IP> [端口] [DOMAIN_ID]
#   例：source ros_discovery_env.sh 192.168.106.137
# =============================================================
# 服务器 IP 必填，否则给本机默认值
SERVER_IP="${1:-127.0.0.1}"
PORT="${2:-11811}"
DOMAIN_ID="${3:-0}"

export ROS_DISCOVERY_SERVER="${SERVER_IP}:${PORT}"
export ROS_DOMAIN_ID="${DOMAIN_ID}"
export RMW_IMPLEMENTATION=rmw_fastrtps_cpp   # 该发现机制由 Fast DDS 提供

echo "[discovery] ROS_DISCOVERY_SERVER=${ROS_DISCOVERY_SERVER}  ROS_DOMAIN_ID=${ROS_DOMAIN_ID}  RMW=${RMW_IMPLEMENTATION}"
