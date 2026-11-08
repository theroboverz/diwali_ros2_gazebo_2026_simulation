#!/usr/bin/env python3
"""Festival event manager.

Topics (all std_msgs/String unless noted):
  /festival/fireworks     in  command  "<effect>[@<site>]"  QoS reliable / volatile / depth 10
  /festival/lighting      in  command  "on|off|dim|bright|twinkle|festive"  same QoS
  /festival/sound         in  command  "<wav name without extension>"       same QoS
  /festival/event_status  out diwali_interfaces/FestivalStatus              reliable / transient_local / depth 1
Services (std_srvs/SetBool): /festival/set_autonomous, /festival/enable_fireworks,
                             /festival/enable_lighting, /festival/enable_sound
Scheduling uses wall-clock time on purpose: particle effects run in the renderer and are not
tied to the physics step.
"""
import os
import random
import time
from collections import deque

import rclpy
import yaml
from ament_index_python.packages import get_package_share_directory
from diwali_interfaces.msg import FestivalStatus
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String
from std_srvs.srv import SetBool

from .fireworks_controller import EFFECTS, FireworksController
from .gz_interface import GzInterface
from .lighting_controller import LightingController
from .sound_controller import SoundController


class FestivalManager(Node):
    def __init__(self):
        super().__init__('festival_manager')
        d = self.declare_parameter
        d('world_name', 'diwali_street')
        d('autonomous', True)
        d('fireworks_enabled', True)
        d('lighting_enabled', True)
        d('sound_enabled', True)
        d('auto_first_delay_s', 20.0)
        d('auto_interval_min_s', 25.0)
        d('auto_interval_max_s', 50.0)
        d('max_events_per_minute', 6)
        d('lights_file', '')
        d('sounds_dir', '')
        d('sites', ['fw_n1', 'fw_n2', 'fw_s1', 'fw_s2'])
        d('sparklers', ['sp0', 'sp1', 'sp2', 'sp3'])
        d('auto_effects', ['golden_burst', 'red_burst', 'blue_burst', 'green_burst', 'finale'])
        d('force_gz_cli', False)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        self.autonomous, self.fw_on = g('autonomous'), g('fireworks_enabled')
        self.max_per_min = int(g('max_events_per_minute'))
        self.auto_effects = list(g('auto_effects'))
        sounds_dir = g('sounds_dir') or os.path.join(get_package_share_directory('diwali_festival'), 'sounds')

        self.gz = GzInterface(g('world_name'), self.get_logger(), g('force_gz_cli'))
        self.sound = SoundController(sounds_dir, g('sound_enabled'), logger=self.get_logger())
        site_parts, park_z, fx_dir = {}, -30.0, ''
        try:
            sim = get_package_share_directory('diwali_sim')
            fx_dir = os.path.join(sim, 'models', 'cracker_fx', 'materials', 'textures')
            with open(os.path.join(sim, 'config', 'crackers.yaml')) as f:
                cfg = yaml.safe_load(f)
            site_parts, park_z = cfg.get('sites', {}), float(cfg.get('park_z', park_z))
        except Exception as e:  # noqa: BLE001 - diwali_sim missing: no sky shots
            self.get_logger().warn(f'No sky-shot sites available: {e}')
        self.fw = FireworksController(self.gz, g('sites'), g('sparklers'), self.sound, self.get_logger(), fx_dir,
                                      site_parts, park_z)
        self.lights = LightingController(self.gz, g('lights_file'), self.get_logger())
        if not g('lighting_enabled'):
            self.lights.enabled = False

        self._history = deque()
        self.triggered = self.rejected = 0
        self.last_event = 'none'
        self.next_auto = time.monotonic() + float(g('auto_first_delay_s'))

        cmd_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.VOLATILE,
                             history=HistoryPolicy.KEEP_LAST, depth=10)
        status_qos = QoSProfile(reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
                                history=HistoryPolicy.KEEP_LAST, depth=1)
        self.create_subscription(String, '/festival/fireworks', self._on_fireworks, cmd_qos)
        self.create_subscription(String, '/festival/lighting', self._on_lighting, cmd_qos)
        self.create_subscription(String, '/festival/sound', lambda m: self.sound.play(m.data.strip()), cmd_qos)
        self.status_pub = self.create_publisher(FestivalStatus, '/festival/event_status', status_qos)
        self.create_service(SetBool, '/festival/set_autonomous', self._srv('autonomous'))
        self.create_service(SetBool, '/festival/enable_fireworks', self._srv('fw_on'))
        self.create_service(SetBool, '/festival/enable_lighting', self._srv('lighting'))
        self.create_service(SetBool, '/festival/enable_sound', self._srv('sound'))
        self.create_timer(0.05, self._tick)
        self.create_timer(1.0, self._publish_status)
        self.get_logger().info(f'Festival manager ready. Effects: {", ".join(EFFECTS)}')
        self._publish_status()

    # -- services --------------------------------------------------------------------------
    def _srv(self, what):
        def cb(req, res):
            if what == 'autonomous':
                self.autonomous = req.data
                self.next_auto = time.monotonic() + 5.0
            elif what == 'fw_on':
                self.fw_on = req.data
                if not req.data:
                    self.fw.stop_all()
            elif what == 'lighting':
                self.lights.set_enabled(req.data)
            elif what == 'sound':
                self.sound.enabled = req.data
            res.success, res.message = True, f'{what} = {req.data}'
            self._publish_status()
            return res
        return cb

    # -- commands --------------------------------------------------------------------------
    def _on_fireworks(self, msg):
        self._request(msg.data, 'topic')

    def _on_lighting(self, msg):
        ok, info = self.lights.set_mode(msg.data)
        self.last_event = f'lighting {msg.data.strip()} {"ACCEPTED" if ok else "REJECTED: " + info}'
        self.get_logger().info(self.last_event)
        self._publish_status()

    def _request(self, text, source):
        now = time.monotonic()
        effect, _, site = text.strip().partition('@')
        effect, site = effect.strip().lower(), (site.strip() or None)
        if effect == 'random':
            effect = random.choice([e for e in self.auto_effects if e != 'finale'] or ['golden_burst'])
        accepted, reason = False, ''
        if effect == 'stop':
            accepted, reason = self.fw.trigger('stop', None, now)
        elif not self.fw_on:
            reason = 'fireworks disabled'
        else:
            while self._history and now - self._history[0] > 60.0:
                self._history.popleft()
            if len(self._history) >= self.max_per_min:
                reason = f'rate limit ({self.max_per_min}/min)'
            else:
                accepted, reason = self.fw.trigger(effect, site, now)
                if accepted and not effect.startswith('sparkler'):
                    self._history.append(now)
        if accepted:
            self.triggered += 1
        else:
            self.rejected += 1
        self.last_event = f'{effect}@{reason if accepted else (site or "-")} {"ACCEPTED" if accepted else "REJECTED: " + reason} ({source})'
        self.get_logger().info(self.last_event)
        self._publish_status()

    # -- timers ----------------------------------------------------------------------------
    def _tick(self):
        now = time.monotonic()
        self.fw.tick(now)
        self.lights.tick(now)
        if self.autonomous and self.fw_on and now >= self.next_auto:
            self._request(random.choice(self.auto_effects), 'auto')
            lo, hi = self.get_parameter('auto_interval_min_s').value, self.get_parameter('auto_interval_max_s').value
            self.next_auto = now + random.uniform(lo, hi)

    def _publish_status(self):
        m = FestivalStatus()
        m.stamp = self.get_clock().now().to_msg()
        m.mode = 'AUTONOMOUS' if self.autonomous else 'MANUAL'
        m.fireworks_enabled, m.lighting_enabled, m.sound_enabled = self.fw_on, self.lights.enabled, self.sound.enabled
        m.lighting_mode, m.last_event = self.lights.mode, self.last_event
        m.events_triggered, m.events_rejected = self.triggered, self.rejected
        m.seconds_to_next_auto_event = float(max(0.0, self.next_auto - time.monotonic())) if self.autonomous else -1.0
        self.status_pub.publish(m)


def main(args=None):
    rclpy.init(args=args)
    node = FestivalManager()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.fw.stop_all()
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
