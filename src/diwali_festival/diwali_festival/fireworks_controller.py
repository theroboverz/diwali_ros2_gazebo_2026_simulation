"""Sky shots from the launch tubes at the street ends, on top of Gazebo's ParticleEmitter system.

Gazebo Harmonic particle emitters are continuous jets, not an explosion system, so a "firework" is a timed
choreography (see diwali_sim/scripts/generate_assets.py: firework_parts):

  rocket  : fire stream + smoke rising from the tube
  burst   : 26 jets in all directions at 28 m (colour chosen per shot via color_range_image)
  sparkle : glitter in a large ellipsoid around the burst

Every part is a model parked under the street. A shot first ARMS the site (emitters switched on while
parked, burst colour set) and `arm_s` later places/parks the parts on schedule: commanding a visible
emitter makes Gazebo rebuild it and spray white streaks (generate_assets.py, "WHY PARTS ARE PARKED").
Part topics: /festival/fw/<site>/<part>; part models and poses come from diwali_sim/config/crackers.yaml.
"""
import random

BURSTS = {'golden_burst': 'gold', 'red_burst': 'red', 'blue_burst': 'blue', 'green_burst': 'green'}
PARTS = ('rocket', 'burst', 'sparkle')
EFFECTS = ('rocket', 'golden_burst', 'red_burst', 'blue_burst', 'green_burst', 'sparkle', 'finale',
           'sparkler_on', 'sparkler_off', 'stop', 'random')
RISE_S = 1.5


def _launch():
    return [(0.0, 'sound', 'firework_launch'), (0.0, 'place', 'rocket', True), (RISE_S, 'place', 'rocket', False)]


def _burst(t0=RISE_S):
    return [(t0, 'sound', 'firework_burst'), (t0, 'place', 'burst', True), (t0 + 0.3, 'place', 'burst', False),
            (t0 + 0.4, 'place', 'sparkle', True), (t0 + 1.2, 'sound', 'firework_crackle'),
            (t0 + 1.6, 'place', 'sparkle', False)]


def timeline(effect):
    """-> (steps, burst colour)"""
    if effect == 'rocket':
        return _launch(), None
    if effect in BURSTS:
        return _launch() + _burst(), BURSTS[effect]
    if effect == 'sparkle':
        return [(0.0, 'place', 'sparkle', True), (1.5, 'place', 'sparkle', False)], None
    return None, None


class FireworksController:
    def __init__(self, gz, sites, sparklers, sound, logger=None, fx_dir='', site_parts=None, park_z=-30.0,
                 arm_s=1.2):
        self.gz, self.sparklers, self.sound, self._log = gz, list(sparklers), sound, logger
        self.fx_dir = fx_dir                  # absolute dir of range_<colour>.png
        self.site_parts = site_parts or {}    # site -> part -> {model, pose}
        self.park_z, self.arm_s = park_z, arm_s
        self.sites = [s for s in sites if s in self.site_parts]
        if logger and len(self.sites) < len(sites):
            logger.warn(f'No part models for sites {sorted(set(sites) - set(self.sites))}; they are ignored')
        self._queue = []                       # (abs_time, site, action, args...)
        self._busy_until = {s: 0.0 for s in self.sites}
        for s in self.sites:
            for p in PARTS:
                self.gz.prime(self._topic(s, p))
        for sp in self.sparklers:
            self.gz.prime(self._spark_topic(sp))

    @staticmethod
    def _topic(site, part):
        return f'/festival/fw/{site}/{part}'

    @staticmethod
    def _spark_topic(sid):
        return f'/festival/sparkler/{sid}'

    def _schedule(self, now, site, steps, colour, offset=0.0):
        t0 = now + offset
        end = t0 + self.arm_s + max(s[0] for s in steps) + 0.5
        self._queue.append((t0, site, 'arm', colour))
        for st in steps:
            self._queue.append((t0 + self.arm_s + st[0], site) + tuple(st[1:]))
        self._queue.append((end, site, 'disarm'))
        self._queue.sort(key=lambda q: q[0])
        self._busy_until[site] = max(self._busy_until[site], end)

    def free_sites(self, now):
        return [s for s in self.sites if self._busy_until[s] <= now]

    def trigger(self, effect, site, now):
        """Returns (accepted: bool, reason: str)."""
        if effect == 'stop':
            self.stop_all()
            return True, 'stopped'
        if effect in ('sparkler_on', 'sparkler_off'):
            for sp in self.sparklers:
                self.gz.set_emitting(self._spark_topic(sp), effect == 'sparkler_on')
            return True, effect
        if effect == 'finale':
            free = self.free_sites(now)
            if not free:
                return False, 'all sites busy'
            colours = list(BURSTS.values())
            for i, s in enumerate(free):
                self._schedule(now, s, _launch() + _burst(), colours[i % 4], offset=i * 0.7)
            return True, f'finale on {len(free)} site(s)'
        steps, colour = timeline(effect)
        if steps is None:
            return False, f'unknown effect "{effect}"'
        if site is None:
            free = self.free_sites(now)
            if not free:
                return False, 'all sites busy'
            site = random.choice(free)
        elif site not in self._busy_until:
            return False, f'unknown site "{site}"'
        elif self._busy_until[site] > now:
            return False, f'site {site} busy'
        self._schedule(now, site, steps, colour)
        return True, site

    def _place(self, site, part, on):
        p = self.site_parts[site][part]
        x, y, z, yaw = p['pose']
        self.gz.set_pose(p['model'], x, y, z if on else self.park_z, yaw)

    def _arm(self, site, on, colour=None):
        for part in PARTS:
            image = (f'{self.fx_dir}/range_{colour}.png'
                     if on and part == 'burst' and colour and self.fx_dir else None)
            self.gz.set_emitting(self._topic(site, part), on, colour_image=image)

    def tick(self, now):
        while self._queue and self._queue[0][0] <= now:
            item = self._queue.pop(0)
            site, action = item[1], item[2]
            if action == 'arm':
                self._arm(site, True, item[3])
            elif action == 'disarm':
                self._arm(site, False)
            elif action == 'place':
                self._place(site, item[3], item[4])
            elif action == 'sound':
                self.sound.play(item[3])

    def stop_all(self):
        self._queue.clear()
        for s in self.sites:
            self._busy_until[s] = 0.0
            for p in PARTS:
                self._place(s, p, False)
            self._arm(s, False)
