#!/usr/bin/env python3
"""Cracker tour: the AMR drives (Nav2) along the centre street and lights each cracker slot on arrival.

Visit order and approach poses come from diwali_sim/config/cracker_tour.yaml, generated together with the
world by diwali_sim/scripts/generate_assets.py. On reaching a stop this node publishes the stop's cracker ids
on /festival/burn; cracker_show plays their burn effects. After the last stop the AMR drives back home, fires
a finale and lights the house sparklers (festival_manager).

Needs Nav2 (nav2.launch.py) and cracker_show (started by festival.launch.py).
Timeouts are in sim time: with CPU rendering Gazebo can run well below real time.
"""
import math
import os
import time

import rclpy
import yaml
from ament_index_python.packages import PackageNotFoundError, get_package_share_directory
from geometry_msgs.msg import PoseStamped
from nav2_simple_commander.robot_navigator import BasicNavigator, TaskResult
from std_msgs.msg import String



def default_tour_file():
    try:
        return os.path.join(get_package_share_directory('diwali_sim'), 'config', 'cracker_tour.yaml')
    except PackageNotFoundError:
        return ''


class CrackerTour(BasicNavigator):
    def __init__(self):
        super().__init__('cracker_tour')
        d = self.declare_parameter
        d('tour_file', default_tour_file())
        d('localizer', 'map_server')   # 'map_server' (ground-truth localization) or 'amcl'
        d('dwell_s', 2.0)              # pause beside each freshly lit cracker (wall time)
        d('goal_timeout_s', 60.0)      # per attempt, sim time, plus 4 s per metre of straight-line distance
        d('max_attempts', 2)           # per stop; a stop that still fails is skipped
        d('reset_on_start', False)     # the world starts with every cracker off; true when re-running a tour
        d('finale_at_home', True)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        path = g('tour_file')
        if not path or not os.path.isfile(path):
            raise RuntimeError(f'tour_file not found: "{path}"')
        with open(path) as f:
            tour = yaml.safe_load(f)
        self.stops, self.home = tour['stops'], tour['home']
        self.localizer = g('localizer')
        self.dwell, self.timeout = float(g('dwell_s')), float(g('goal_timeout_s'))
        self.max_attempts, self.finale = int(g('max_attempts')), bool(g('finale_at_home'))
        self.reset_on_start = bool(g('reset_on_start'))
        self.here = tuple(self.home[:2])
        self.burn_pub = self.create_publisher(String, '/festival/burn', 10)
        self.fw_pub = self.create_publisher(String, '/festival/fireworks', 10)
        self.sound_pub = self.create_publisher(String, '/festival/sound', 10)
        self.info(f'Loaded {len(self.stops)} cracker stops from {path}')

    # -- helpers ---------------------------------------------------------------------------
    def pose(self, x, y, yaw):
        p = PoseStamped()
        p.header.frame_id = 'map'
        p.header.stamp = self.get_clock().now().to_msg()
        p.pose.position.x, p.pose.position.y = float(x), float(y)
        p.pose.orientation.z, p.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        return p

    def sim_now(self):
        return self.get_clock().now().nanoseconds * 1e-9

    def drive(self, goal, label):
        timeout = self.timeout + 4.0 * math.hypot(goal[0] - self.here[0], goal[1] - self.here[1])
        for attempt in range(1, self.max_attempts + 1):
            if not self.goToPose(self.pose(*goal)):
                self.warn(f'{label}: goal rejected (attempt {attempt})')
                continue
            start = last_log = self.sim_now()
            while not self.isTaskComplete():
                now = self.sim_now()
                if now - start > timeout:
                    self.warn(f'{label}: timed out after {timeout:.0f} s (sim), cancelling')
                    self.cancelTask()
                    break
                fb = self.getFeedback()
                if fb and now - last_log > 15.0:
                    last_log = now
                    self.info(f'{label}: {fb.distance_remaining:.1f} m to go')
            if self.getResult() == TaskResult.SUCCEEDED:
                self.here = tuple(goal[:2])
                return True
            self.warn(f'{label}: attempt {attempt}/{self.max_attempts} failed')
        return False

    # -- tour ------------------------------------------------------------------------------
    def run(self):
        if self.localizer == 'amcl':
            self.setInitialPose(self.pose(*self.home))
        self.waitUntilNav2Active(localizer=self.localizer)
        if self.reset_on_start:
            self.info('Resetting every cracker')
            self.burn_pub.publish(String(data='reset'))
        n, lit, skipped = len(self.stops), 0, []
        for i, s in enumerate(self.stops, 1):
            label = f'[{i}/{n}] slot {s["slot"]}'
            self.info(f'{label}: driving to ({s["goal"][0]:.1f}, {s["goal"][1]:.1f})')
            if not self.drive(s['goal'], label):
                self.warn(f'{label}: unreachable, skipping')
                skipped.append(s['slot'])
                continue
            self.burn_pub.publish(String(data=','.join(s['ids'])))
            lit += 1
            self.info(f'{label}: lighting {", ".join(s["ids"])}')
            time.sleep(self.dwell)
        self.info(f'All slots visited ({lit} lit, {len(skipped)} skipped). Returning home.')
        if self.drive(self.home, 'home'):
            self.info('Back home. Happy Diwali!')
            self.sound_pub.publish(String(data='temple_bell'))
            if self.finale:
                self.fw_pub.publish(String(data='finale'))
                self.fw_pub.publish(String(data='sparkler_on'))   # the house sparklers join in
        else:
            self.error('Could not get back home')
        if skipped:
            self.warn(f'Skipped: {", ".join(skipped)}')


def main(args=None):
    rclpy.init(args=args)
    node = CrackerTour()
    try:
        node.run()
    except KeyboardInterrupt:
        node.cancelTask()
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
