#!/usr/bin/env bash
# SCL 图形前端（WSL2 侧）：设发现环境 + 启动 rviz2，显示 VM 侧雷达的 /scan
source /opt/ros/jazzy/setup.bash
source /home/omen/MyWork/Robot/ros2/ChassisNav_01/scripts/ros_discovery_env.sh 10.144.144.3

rviz2 -d /home/omen/MyWork/Robot/ros2/ydlidar/ydlidar_ros2_driver/config/ydlidar.rviz
