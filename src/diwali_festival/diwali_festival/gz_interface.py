"""Thin wrapper around Gazebo Transport.

Why this exists: ros_gz_bridge has no mapping for gz.msgs.ParticleEmitter, so ROS 2 cannot
publish it directly. This adapter talks to Gazebo Harmonic's transport layer instead:

  * preferred: Python bindings (python3-gz-transport13 + python3-gz-msgs10)
  * fallback : the `gz` command line tool (slower, one process per call, but no extra packages)
"""
import os
import shutil
import subprocess

import yaml

try:  # Harmonic = gz-transport13 / gz-msgs10
    from gz.transport13 import Node as GzNode
    from gz.msgs10.particle_emitter_pb2 import ParticleEmitter
    from gz.msgs10.light_pb2 import Light
    from gz.msgs10.boolean_pb2 import Boolean
    from gz.msgs10.pose_pb2 import Pose
    from gz.msgs10.twist_pb2 import Twist
    HAVE_PY_BINDINGS = True
except Exception:  # pragma: no cover - depends on the machine
    HAVE_PY_BINDINGS = False


class GzInterface:
    def __init__(self, world='diwali_street', logger=None, force_cli=False):
        self.world = world
        self._log = logger
        self.use_py = HAVE_PY_BINDINGS and not force_cli
        self._node = GzNode() if self.use_py else None
        self._pubs = {}
        self._procs = []
        self.fanout = self._load_fanout()
        self.gz_bin = shutil.which('gz')
        mode = 'python bindings' if self.use_py else ('gz CLI' if self.gz_bin else 'NONE (dry run)')
        self._info(f'Gazebo transport backend: {mode}')

    @staticmethod
    def _load_fanout():
        """Gazebo keeps one particle emitter per topic, so every jet of a cracker part has its own topic
        <part>/<k>; diwali_sim/config/emitter_topics.yaml says how many jets each part has."""
        try:
            from ament_index_python.packages import get_package_share_directory
            path = os.path.join(get_package_share_directory('diwali_sim'), 'config', 'emitter_topics.yaml')
            with open(path) as f:
                return {t: [f'{t}/{k}' for k in range(int(n))] for t, n in (yaml.safe_load(f) or {}).items()}
        except Exception:  # noqa: BLE001 - no map: topics are used as given
            return {}

    # -- logging helpers -------------------------------------------------------------------
    def _info(self, msg):
        if self._log:
            self._log.info(msg)

    def _warn(self, msg):
        if self._log:
            self._log.warn(msg)

    # -- particle emitters -----------------------------------------------------------------
    def prime(self, topic):
        """Advertise early so Gazebo transport discovery has finished before the first command."""
        for t in self.fanout.get(topic, [topic]):
            if self.use_py and t not in self._pubs:
                self._pubs[t] = self._node.advertise(t, ParticleEmitter)

    def set_emitting(self, topic, emitting, rate=None, colour_image=None):
        ok = True
        for t in self.fanout.get(topic, [topic]):
            ok = self._set_emitting(t, emitting, rate, colour_image) and ok
        return ok

    def _set_emitting(self, topic, emitting, rate=None, colour_image=None):
        """Switch an emitter (or every emitter sharing `topic`) on/off; optionally change its rate or its
        color_range_image (an absolute PNG path: ogre2 ignores color_start/color_end)."""
        emitting = bool(emitting)
        if self.use_py:
            self.prime(topic)
            msg = ParticleEmitter()
            msg.emitting.data = emitting
            if rate is not None:
                msg.rate.data = float(rate)
            if colour_image:
                msg.color_range_image.data = colour_image
            return self._pubs[topic].publish(msg)
        extra = f' rate: {{data: {float(rate)}}}' if rate is not None else ''
        extra += f' color_range_image: {{data: "{colour_image}"}}' if colour_image else ''
        return self._cli(['topic', '-t', topic, '-m', 'gz.msgs.ParticleEmitter', '-p',
                          f'emitting: {{data: {str(emitting).lower()}}}{extra}'])

    # -- models ----------------------------------------------------------------------------
    def set_pose(self, model, x, y, z, yaw=0.0, timeout_ms=100):
        """Teleport a model (static ones too) through /world/<world>/set_pose."""
        import math
        qz, qw = math.sin(yaw / 2), math.cos(yaw / 2)
        service = f'/world/{self.world}/set_pose'
        if self.use_py:
            msg = Pose()
            msg.name = model
            msg.position.x, msg.position.y, msg.position.z = float(x), float(y), float(z)
            msg.orientation.z, msg.orientation.w = qz, qw
            ok, _ = self._node.request(service, msg, Pose, Boolean, timeout_ms)
            return ok
        return self._cli(['service', '-s', service, '--reqtype', 'gz.msgs.Pose', '--reptype', 'gz.msgs.Boolean',
                          '--timeout', str(timeout_ms), '--req',
                          f'name: "{model}" position {{x: {x} y: {y} z: {z}}} orientation {{z: {qz} w: {qw}}}'])

    def set_twist(self, model, vx=0.0, wz=0.0):
        """Body-frame velocity command for a model running the VelocityControl system."""
        topic = f'/model/{model}/cmd_vel'
        if self.use_py:
            if topic not in self._pubs:
                self._pubs[topic] = self._node.advertise(topic, Twist)
            msg = Twist()
            msg.linear.x, msg.angular.z = float(vx), float(wz)
            return self._pubs[topic].publish(msg)
        return self._cli(['topic', '-t', topic, '-m', 'gz.msgs.Twist', '-p',
                          f'linear: {{x: {vx}}} angular: {{z: {wz}}}'])

    # -- lights ----------------------------------------------------------------------------
    def set_light(self, name, pose, diffuse, intensity, range_, attenuation):
        """Calls /world/<world>/light_config (UserCommands system) with a full gz.msgs.Light."""
        service = f'/world/{self.world}/light_config'
        if self.use_py:
            msg = Light()
            msg.name = name
            msg.type = Light.POINT
            msg.intensity = float(intensity)
            msg.range = float(range_)
            msg.attenuation_constant, msg.attenuation_linear, msg.attenuation_quadratic = attenuation
            msg.cast_shadows = False
            msg.diffuse.r, msg.diffuse.g, msg.diffuse.b, msg.diffuse.a = (*diffuse, 1.0)
            msg.specular.r, msg.specular.g, msg.specular.b, msg.specular.a = (*diffuse, 1.0)
            msg.pose.position.x, msg.pose.position.y, msg.pose.position.z = pose[:3]
            ok, _ = self._node.request(service, msg, Light, Boolean, 300)
            return ok
        r, g, b = diffuse
        text = (f'name: "{name}" type: POINT intensity: {intensity} range: {range_} '
                f'attenuation_constant: {attenuation[0]} attenuation_linear: {attenuation[1]} '
                f'attenuation_quadratic: {attenuation[2]} cast_shadows: false '
                f'diffuse {{r: {r} g: {g} b: {b} a: 1}} specular {{r: {r} g: {g} b: {b} a: 1}} '
                f'pose {{position {{x: {pose[0]} y: {pose[1]} z: {pose[2]}}}}}')
        return self._cli(['service', '-s', service, '--reqtype', 'gz.msgs.Light', '--reptype',
                          'gz.msgs.Boolean', '--timeout', '300', '--req', text])

    # -- CLI fallback ----------------------------------------------------------------------
    def _cli(self, args):
        if not self.gz_bin:
            self._warn('No Gazebo transport backend available; command dropped: gz ' + ' '.join(args[:3]))
            return False
        self._procs = [p for p in self._procs if p.poll() is None]
        if len(self._procs) > 24:
            return False  # protect against process storms
        self._procs.append(subprocess.Popen([self.gz_bin] + args, stdout=subprocess.DEVNULL,
                                            stderr=subprocess.DEVNULL))
        return True
