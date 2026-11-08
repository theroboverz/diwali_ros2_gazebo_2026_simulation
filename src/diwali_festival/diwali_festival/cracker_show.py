#!/usr/bin/env python3
"""Cracker show: lights the street crackers on request and plays each one's burn effect.

Topics
  /festival/burn_count     std_msgs/Int32   in   N -> light the next N unburnt crackers (street order),
                                                  one every `stagger_s` seconds
  /festival/burn           std_msgs/String  in   "<id>[,<id>...]" | "all" | "reset" | "stop"
  /festival/cracker_status std_msgs/String  out  e.g. "burnt 5/32 | burning: cp5 | next: cp6 (Pattasu)"

Example
  ros2 topic pub --once /festival/burn_count std_msgs/msg/Int32 "{data: 3}"
  ros2 topic pub --once /festival/burn std_msgs/msg/String "{data: reset}"

How a cracker burns: its effect parts (fuse, fountain, bang, ...) are separate models parked under the
street. On ignition every part's emitters are switched on while still parked ("armed"); `arm_s` later the
timeline from cracker_effects.py starts and teleports parts into place and back. Switching emitters while
visible would make Gazebo rebuild them and spray white streaks (see generate_assets.py, "WHY PARTS ARE
PARKED"). Crackers, order, models and poses come from diwali_sim/config/crackers.yaml.
Timing is wall-clock: the particle effects run in the renderer, not in the physics step.
"""
import os
import random
import time

import rclpy
import yaml
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Int32, String

from .cracker_effects import GLOW, timeline
from .gz_interface import GzInterface
from .sound_controller import SoundController


def share(pkg, *p):
    try:
        return os.path.join(get_package_share_directory(pkg), *p)
    except PackageNotFoundError:
        return ''


class CrackerShow(Node):
    def __init__(self):
        super().__init__('cracker_show')
        d = self.declare_parameter
        d('crackers_file', share('diwali_sim', 'config', 'crackers.yaml'))
        d('sounds_dir', share('diwali_festival', 'sounds'))
        d('sound_enabled', True)
        d('stagger_s', 1.5)        # gap between two crackers lit by one burn_count
        d('arm_s', 1.2)            # emitters run parked this long before the effect starts
        d('force_gz_cli', False)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        with open(g('crackers_file')) as f:
            cfg = yaml.safe_load(f)
        self.order = cfg['crackers']
        self.by_id = {c['id']: c for c in self.order}
        self.park_z = float(cfg.get('park_z', -30.0))
        self.free_lights = list(cfg.get('flash_lights', []))
        self.stagger, self.arm = float(g('stagger_s')), float(g('arm_s'))
        self.gz = GzInterface(cfg.get('world', 'diwali_street'), self.get_logger(), g('force_gz_cli'))
        self.sound = SoundController(g('sounds_dir'), g('sound_enabled'), max_concurrent=10, logger=self.get_logger())
        self.burnt, self.burning = set(), set()
        self.queue = []        # (abs_time, cid, step)
        self.flights = {}      # cid -> (t0, duration, z0, apex)
        self.lights = {}       # cid -> light name
        for c in self.order:   # advertise early so gz-transport discovery is done before the first burn
            for part in c['parts']:
                self.gz.prime(self.topic(c, part))

        self.create_subscription(Int32, '/festival/burn_count', self.on_count, 10)
        self.create_subscription(String, '/festival/burn', self.on_burn, 10)
        self.status_pub = self.create_publisher(
            String, '/festival/cracker_status',
            QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL))
        self.create_timer(1 / 30, self.tick)
        self.create_timer(1 / 60, self.fly_tick)   # smooth rocket flight (the trail is emitted where it is)
        self.get_logger().info(f'Cracker show ready: {len(self.order)} crackers. '
                               'Publish a number on /festival/burn_count to light them.')
        self.publish_status()

    # -- helpers -----------------------------------------------------------------------------
    @staticmethod
    def topic(c, part):
        return f'/festival/cracker/{c["id"]}/{part}'

    def unburnt(self):
        return [c for c in self.order if c['id'] not in self.burnt and c['id'] not in self.burning]

    def publish_status(self):
        nxt = self.unburnt()
        text = (f'burnt {len(self.burnt)}/{len(self.order)} | burning: {", ".join(sorted(self.burning)) or "-"} | '
                f'next: {nxt[0]["id"] + " (" + nxt[0]["name"] + ")" if nxt else "none left"}')
        self.status_pub.publish(String(data=text))

    def place(self, model, pose, z=None):
        x, y, pz, yaw = pose
        self.gz.set_pose(model, x, y, pz if z is None else z, yaw)

    # -- commands ----------------------------------------------------------------------------
    def on_count(self, msg):
        n = int(msg.data)
        todo = self.unburnt()
        if n <= 0:
            self.get_logger().warn(f'burn_count {n}: nothing to do')
            return
        if not todo:
            self.get_logger().warn('All crackers are already burnt; publish "reset" on /festival/burn')
            return
        if n > len(todo):
            self.get_logger().warn(f'Asked for {n} but only {len(todo)} unburnt crackers are left')
        self.ignite([c['id'] for c in todo[:n]])

    def on_burn(self, msg):
        text = msg.data.strip().lower()
        if text == 'reset':
            self.reset()
        elif text == 'stop':
            self.stop()
        elif text == 'all':
            self.ignite([c['id'] for c in self.unburnt()])
        else:
            ids = [i.strip() for i in msg.data.split(',') if i.strip()]
            bad = [i for i in ids if i not in self.by_id]
            if bad:
                self.get_logger().warn(f'Unknown cracker id(s): {", ".join(bad)}')
            self.ignite([i for i in ids if i in self.by_id and i not in self.burnt and i not in self.burning])

    def ignite(self, ids):
        now = time.monotonic()
        for k, cid in enumerate(ids):
            c = self.by_id[cid]
            self.burning.add(cid)
            t_arm = now + k * self.stagger
            self.queue.append((t_arm, cid, ('arm',)))
            for step in timeline(c['type'], c.get('colour', 'gold'), random):
                self.queue.append((t_arm + self.arm + step[0], cid, step[1:]))
            self.get_logger().info(f'Lighting {cid}: {c["name"]} ({c["colour"]}) in {k * self.stagger:.1f} s')
        self.queue.sort(key=lambda q: q[0])
        self.publish_status()

    def stop(self):
        """Abort every running effect; crackers that were burning count as burnt."""
        for cid in list(self.burning):
            self.extinguish(self.by_id[cid])
            self.burnt.add(cid)
        self.burning.clear()
        self.queue.clear()
        self.flights.clear()
        self.publish_status()

    def reset(self):
        self.queue.clear()
        self.flights.clear()
        for c in self.order:
            self.extinguish(c)
            self.place(c['body'], c['pose'])
        self.burnt.clear()
        self.burning.clear()
        self.get_logger().info('All crackers reset')
        self.publish_status()

    def extinguish(self, c):
        """Park every part and switch its emitters off (out of sight)."""
        for part, p in c['parts'].items():
            if c['type'] == 'chakkar' and part == 'spin':
                self.gz.set_twist(p['model'], 0.0, 0.0)
            self.place(p['model'], p['pose'], self.park_z)
            self.gz.set_emitting(self.topic(c, part), False)
        self.release_light(c['id'])

    # -- lights ------------------------------------------------------------------------------
    def light_on(self, c, colour, intensity, rng, z, absolute):
        name = self.lights.get(c['id']) or (self.free_lights.pop(0) if self.free_lights else None)
        if not name:
            return
        self.lights[c['id']] = name
        x, y, cz = c['at']
        if absolute:
            z = c['parts']['burst']['pose'][2] if z is None else z
        else:
            z = cz + z
        self.gz.set_light(name, (x, y, z), GLOW.get(colour, GLOW['fire']), intensity, rng, (0.3, 0.2, 0.05))

    def release_light(self, cid):
        name = self.lights.pop(cid, None)
        if name:
            self.gz.set_light(name, (0.0, 0.0, -20.0), GLOW['fire'], 0.0, 8.0, (0.3, 0.2, 0.05))
            self.free_lights.append(name)

    # -- playback ----------------------------------------------------------------------------
    def run(self, c, step):
        action = step[0]
        if action == 'arm':
            for part in c['parts']:
                self.gz.set_emitting(self.topic(c, part), True)
        elif action == 'emit':
            p = c['parts'][step[1]]
            self.place(p['model'], p['pose'], None if step[2] else self.park_z)
        elif action == 'sound':
            self.sound.play(step[1])
        elif action == 'light':
            if step[1]:
                self.light_on(c, *step[2:])
            else:
                self.release_light(c['id'])
        elif action == 'hide':
            self.place(c['body'], c['pose'], self.park_z)
        elif action == 'show':
            self.place(c['body'], c['pose'])
        elif action == 'spin':
            self.gz.set_twist(c['parts']['spin']['model'], step[1], step[2])
        elif action == 'fly':
            apex = step[2] or c['parts']['burst']['pose'][2]
            self.flights[c['id']] = (time.monotonic(), step[1], c['parts']['trail']['pose'][2], apex)
        elif action == 'done':
            self.extinguish(c)
            self.burning.discard(c['id'])
            self.burnt.add(c['id'])
            self.get_logger().info(f'{c["id"]} ({c["name"]}) finished. {len(self.unburnt())} left.')
            self.publish_status()

    def fly_tick(self):
        now = time.monotonic()
        for cid, (t0, dur, z0, apex) in list(self.flights.items()):
            s = min(1.0, (now - t0) / dur)
            p = self.by_id[cid]['parts']['trail']
            self.place(p['model'], p['pose'], z0 + (apex - z0) * s * s)   # accelerating climb
            if s >= 1.0:
                del self.flights[cid]

    def tick(self):
        now = time.monotonic()
        while self.queue and self.queue[0][0] <= now:
            _, cid, step = self.queue.pop(0)
            if cid in self.burning:
                self.run(self.by_id[cid], step)


def main(args=None):
    rclpy.init(args=args)
    node = CrackerShow()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            node.stop()
        except Exception:  # noqa: BLE001 - context may already be shut down by Ctrl-C
            pass
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
