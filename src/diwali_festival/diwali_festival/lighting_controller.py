"""Controls the world-level point lights listed in festival_lights.yaml.

Important: a Gazebo emissive material only makes the surface itself look bright; it does not light
neighbouring objects. Real illumination comes from <light> elements, and those can be changed at
runtime through the UserCommands service /world/<world>/light_config (gz.msgs.Light).
Emissive materials on LED bulbs / flames / windows are static in this project.
"""
import random

import yaml


class LightingController:
    SCALES = {'on': 1.0, 'off': 0.0, 'dim': 0.35, 'bright': 1.6}
    MODES = ('on', 'off', 'dim', 'bright', 'twinkle', 'festive')
    PALETTE = [(1.0, 0.72, 0.35), (1.0, 0.2, 0.2), (0.2, 1.0, 0.4), (0.3, 0.5, 1.0), (1.0, 0.8, 0.1), (0.9, 0.3, 0.9)]

    def __init__(self, gz, lights_file, logger=None):
        self.gz, self._log = gz, logger
        self.lights = []
        if lights_file:
            try:
                with open(lights_file) as f:
                    self.lights = (yaml.safe_load(f) or {}).get('lights', [])
            except OSError as e:
                if logger:
                    logger.error(f'Cannot read lights_file "{lights_file}": {e}')
        elif logger:
            logger.warn('No lights_file given: /festival/lighting will have no effect.')
        self.mode = 'on'
        self.enabled = True
        self._next = 0.0
        self._step = 0

    def _apply(self, light, scale, color=None):
        self.gz.set_light(light['name'], light['pose'], color or light['diffuse'],
                          light['base_intensity'] * scale, light['range'], light['attenuation'])

    def set_mode(self, mode):
        mode = mode.strip().lower()
        if mode not in self.MODES:
            return False, f'unknown lighting mode "{mode}" (use {", ".join(self.MODES)})'
        self.mode = mode
        if mode in self.SCALES and self.enabled:
            for light in self.lights:
                self._apply(light, self.SCALES[mode])
        return True, mode

    def set_enabled(self, enabled):
        self.enabled = enabled
        scale = self.SCALES.get(self.mode, 1.0) if enabled else 0.0
        for light in self.lights:
            self._apply(light, scale)

    def tick(self, now):
        if not self.enabled or now < self._next or not self.lights:
            return
        if self.mode == 'twinkle':
            self._apply(random.choice(self.lights), random.uniform(0.3, 1.3))
            self._next = now + 0.4          # at most 2.5 service calls per second
        elif self.mode == 'festive':
            self._step += 1
            for i, light in enumerate(self.lights):
                self._apply(light, 1.0, self.PALETTE[(i + self._step) % len(self.PALETTE)])
            self._next = now + 1.5
