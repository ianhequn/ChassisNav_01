#!/usr/bin/env python3
"""Periodically save the slam_toolbox map.

保存两份东西：
  1. serialize_map -> .posegraph + .data（用于下次终身续建）
  2. save_map      -> .pgm + .yaml（用于 Nav2 静态地图 / AMCL）

设计要点：
  - 用墙钟定时（use_sim_time=False），Gazebo 暂停时仍会保存；
  - 用异步 service 调用 + 回调链，避免在回调里阻塞等待导致死锁；
  - serialize 失败时跳过本轮 save_map；
  - save_map 返回 1（还没收到地图）时当作“跳过”，不刷错误；
  - 看门狗防止某个 service 永远不返回导致 busy 永久卡住。
"""

import os
import re
import threading
import time

import rclpy
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from slam_toolbox.srv import SaveMap, SerializePoseGraph


# 与 slam_toolbox 的 save_map 服务内部正则一致。
_PATH_RE = re.compile(r'^[A-Za-z0-9_./-]+$')
_PREFIX_RE = re.compile(r'^[A-Za-z0-9_.-]+$')

# 单次保存超过这个时间就认为卡住，复位 busy 标记。
SERVICE_TIMEOUT_SEC = 15.0
WATCHDOG_PERIOD_SEC = 5.0


class SlamMapAutosave(Node):

    def __init__(self):
        super().__init__('slam_map_autosave')

        self.declare_parameter('save_dir', '~/.ros/chassis_slam')
        self.declare_parameter('map_file_prefix', 'chassis_map')
        self.declare_parameter('interval', 30.0)

        raw_dir = str(self.get_parameter('save_dir').value)
        self._prefix = str(self.get_parameter('map_file_prefix').value).strip()
        self._save_dir = os.path.abspath(os.path.expanduser(raw_dir))
        self._interval = float(self.get_parameter('interval').value)

        self._lock = threading.Lock()
        self._busy = False
        self._busy_since = 0.0
        # 每次保存/看门狗复位都会递增；回调携带旧 generation 时直接忽略，
        # 避免超时后迟到的回调再次发起 save_map。
        self._generation = 0
        self._valid = True

        self._serialize_client = self.create_client(
            SerializePoseGraph, '/slam_toolbox/serialize_map')
        self._save_client = self.create_client(
            SaveMap, '/slam_toolbox/save_map')

        self._validate_paths()

        if self._interval > 0.0:
            self.create_timer(self._interval, self._on_timer)
            self.get_logger().info(
                f'autosave enabled: {os.path.join(self._save_dir, self._prefix)} '
                f'every {self._interval:.1f}s'
            )
        else:
            self.get_logger().info(
                'autosave disabled (interval <= 0)'
            )

        self.create_timer(WATCHDOG_PERIOD_SEC, self._on_watchdog)

    def _validate_paths(self):
        if not _PREFIX_RE.match(self._prefix):
            self.get_logger().error(
                f'invalid map_file_prefix "{self._prefix}": '
                'only [A-Za-z0-9_.-] are allowed; autosave disabled'
            )
            self._valid = False
            return

        if not _PATH_RE.match(self._save_dir):
            self.get_logger().error(
                f'invalid save_dir "{self._save_dir}": '
                'only [A-Za-z0-9_./-] are allowed; autosave disabled'
            )
            self._valid = False
            return

        try:
            os.makedirs(self._save_dir, exist_ok=True)
        except OSError as exc:
            self.get_logger().error(
                f'failed to create save_dir "{self._save_dir}": {exc}; '
                'autosave disabled'
            )
            self._valid = False

    def _on_timer(self):
        if not self._valid:
            return

        with self._lock:
            if self._busy:
                return
            if not self._serialize_client.service_is_ready():
                self.get_logger().warn(
                    'serialize_map service not ready; skip this round'
                )
                return
            if not self._save_client.service_is_ready():
                self.get_logger().warn(
                    'save_map service not ready; skip this round'
                )
                return

            self._busy = True
            self._busy_since = time.monotonic()
            generation = self._generation

        request = SerializePoseGraph.Request()
        request.filename = os.path.join(self._save_dir, self._prefix)

        try:
            future = self._serialize_client.call_async(request)
        except Exception as exc:  # rclpy 在 shutdown 等情况下可能抛异常
            self._finish(generation, f'serialize_map call failed: {exc}',
                         error=True)
            return

        future.add_done_callback(
            lambda done, gen=generation: self._on_serialize_done(done, gen)
        )

    def _on_serialize_done(self, future, generation):
        if not self._is_current(generation):
            return

        try:
            response = future.result()
        except Exception as exc:
            self._finish(
                generation, f'serialize_map failed: {exc}', error=True)
            return

        if response.result != SerializePoseGraph.Response.RESULT_SUCCESS:
            self._finish(
                generation,
                f'serialize_map returned {response.result}; skip save_map',
                error=True,
            )
            return

        request = SaveMap.Request()
        request.name.data = os.path.join(self._save_dir, self._prefix)

        try:
            save_future = self._save_client.call_async(request)
        except Exception as exc:
            self._finish(
                generation, f'save_map call failed: {exc}', error=True)
            return

        save_future.add_done_callback(
            lambda done, gen=generation: self._on_save_done(done, gen)
        )

    def _on_save_done(self, future, generation):
        if not self._is_current(generation):
            return

        try:
            response = future.result()
        except Exception as exc:
            self._finish(generation, f'save_map failed: {exc}', error=True)
            return

        if response.result == SaveMap.Response.RESULT_SUCCESS:
            self._finish(
                generation,
                f'map saved: {os.path.join(self._save_dir, self._prefix)}',
            )
        elif response.result == SaveMap.Response.RESULT_NO_MAP_RECEIEVD:
            self._finish(
                generation,
                'save_map skipped: no map received yet',
                error=False,
            )
        else:
            self._finish(
                generation, f'save_map returned {response.result}', error=True)

    def _is_current(self, generation):
        with self._lock:
            return generation == self._generation

    def _finish(self, generation, message, error=False):
        with self._lock:
            if generation != self._generation:
                return
            self._busy = False

        if error:
            self.get_logger().error(message)
        else:
            self.get_logger().info(message)

    def _on_watchdog(self):
        with self._lock:
            if not self._busy:
                return
            if time.monotonic() - self._busy_since <= SERVICE_TIMEOUT_SEC:
                return

            # 让当前这轮的回调失效，然后允许下一轮重新开始。
            self._generation += 1
            self._busy = False

        self.get_logger().error(
            f'map save timed out after {SERVICE_TIMEOUT_SEC:.0f}s; '
            'reset and will retry on the next interval'
        )


def main(args=None):
    rclpy.init(args=args)
    node = SlamMapAutosave()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
