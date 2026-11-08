"""How each cracker burns: timelines of (seconds after ignition, action, *args).

The world (diwali_sim/scripts/generate_assets.py) gives every cracker particle emitters grouped by *part*;
all emitters of a part listen on /festival/cracker/<id>/<part>. cracker_show plays these timelines:

  ('emit', part, on)               put a part in place / park it again (its emitters were armed while
                                   parked; see generate_assets.py "WHY PARTS ARE PARKED")
  ('sound', wav)                   play diwali_festival/sounds/<wav>.wav on the host
  ('light', on, colour, intensity, range, z, absolute_z)
                                   move a pooled world light onto the cracker (or park it again)
  ('hide',)                        move the cracker's body under the street (it blew up / was swapped)
  ('show',)                        put the body back
  ('spin', vx, wz)                 body-frame velocity of a chakkar (VelocityControl)
  ('fly', seconds, apex)           rocket flight: accelerate the 'trail' part up to `apex` metres
  ('done',)                        the cracker is spent

Real-world behaviour being imitated:
  flower_pot   Busuvanam: fuse sputters, then a ~6 s fountain of sparks with glitter and smoke; cone stays.
  chakkar      Sanguchakaram: fuse, then the wheel spins on the ground for ~6 s throwing a spiral of sparks.
  pattasu      Single cracker: fuse burns ~2.5 s, then a bang (flash + paper + smoke) and it is gone.
  saravedi     String of crackers: pops run along the string for ~3 s, then the string is gone.
  rocket       Fuse, whoosh up to ~20 m trailing fire, coloured burst + glitter; the bottle stays.
  cracker_cake Multi-shot box: 18 coloured shots, one tube after another.
  roman_candle Coloured stars pop out of the tube for ~8 s.
"""
import random

PARTS = {
    'flower_pot': ['fuse', 'fountain', 'glitter', 'smoke'],
    'chakkar': ['fuse', 'spin', 'smoke'],      # 'spin' is the spinning wheel itself
    'pattasu': ['fuse', 'bang', 'smoke'],
    'saravedi': [f'pop{k}' for k in range(8)] + ['paper', 'smoke'],
    'rocket': ['trail', 'burst', 'glitter'],   # 'trail' is the flying rocket with its exhaust
    'cracker_cake': [f'shot{k}' for k in range(9)] + ['smoke'],
    'roman_candle': ['stars', 'smoke'],
}

# main colour of each palette entry (matches PALETTE in generate_assets.py), used for the glow lights
GLOW = {
    'gold': (1.0, 0.73, 0.16), 'silver': (0.84, 0.89, 1.0), 'red': (1.0, 0.14, 0.1), 'green': (0.2, 1.0, 0.27),
    'blue': (0.2, 0.4, 1.0), 'pink': (1.0, 0.22, 0.67), 'purple': (0.69, 0.27, 1.0), 'fire': (1.0, 0.63, 0.12),
    'flash': (1.0, 0.94, 0.63),
}


def timeline(kind, colour='gold', rng=random):
    if kind == 'flower_pot':
        return [(0.0, 'emit', 'fuse', True),
                (1.2, 'emit', 'fuse', False), (1.2, 'emit', 'fountain', True), (1.2, 'emit', 'smoke', True),
                (1.2, 'sound', 'busuvanam'), (1.2, 'light', True, colour, 1.4, 7.0, 0.8, False),
                (1.7, 'emit', 'glitter', True),
                (7.8, 'emit', 'fountain', False), (7.8, 'emit', 'glitter', False),
                (7.9, 'light', False), (9.0, 'emit', 'smoke', False), (9.5, 'done')]
    if kind == 'chakkar':
        return [(0.0, 'emit', 'fuse', True),
                (1.0, 'emit', 'fuse', False), (1.0, 'hide'), (1.0, 'emit', 'spin', True),
                (1.05, 'spin', 0.25, 14.0),
                (1.0, 'emit', 'smoke', True), (1.0, 'sound', 'chakkar'),
                (1.0, 'light', True, colour, 1.2, 5.0, 0.3, False),
                (7.0, 'spin', 0.0, 0.0), (7.05, 'emit', 'spin', False), (7.05, 'show'), (7.1, 'light', False),
                (7.8, 'emit', 'smoke', False), (8.0, 'done')]
    if kind == 'pattasu':
        return [(0.0, 'emit', 'fuse', True),
                (2.4, 'emit', 'fuse', False), (2.4, 'emit', 'bang', True), (2.4, 'emit', 'smoke', True),
                (2.4, 'sound', 'pattasu_bang'), (2.4, 'light', True, 'flash', 4.0, 10.0, 0.5, False),
                (2.45, 'hide'), (2.52, 'emit', 'bang', False), (2.75, 'light', False),
                (3.3, 'emit', 'smoke', False), (4.0, 'done')]
    if kind == 'saravedi':
        steps = [(0.0, 'emit', 'pop0', True), (0.05, 'emit', 'pop0', False),
                 (0.4, 'sound', 'saravedi'), (0.4, 'emit', 'smoke', True), (0.4, 'emit', 'paper', True),
                 (0.4, 'light', True, 'flash', 1.8, 6.0, 0.4, False)]
        n = 34
        for i in range(n):                       # pops run from one end of the string to the other
            t = 0.4 + i * 0.095 + rng.uniform(-0.03, 0.03)
            k = max(0, min(7, int(i * 8 / n) + rng.choice((-1, 0, 0, 1))))
            steps += [(t, 'emit', f'pop{k}', True), (t + 0.05, 'emit', f'pop{k}', False)]
        end = 0.4 + n * 0.095
        steps += [(end, 'emit', 'paper', False), (end, 'hide'), (end + 0.1, 'light', False),
                  (end + 0.8, 'emit', 'smoke', False), (end + 1.2, 'done')]
        return steps
    if kind == 'rocket':
        return [(0.0, 'hide'), (0.0, 'emit', 'trail', True),
                (0.7, 'fly', 1.4, None), (0.7, 'sound', 'firework_launch'),
                (2.1, 'emit', 'trail', False), (2.1, 'emit', 'burst', True),
                (2.1, 'sound', 'firework_burst'), (2.1, 'light', True, colour, 5.0, 35.0, None, True),
                (2.32, 'emit', 'burst', False), (2.4, 'emit', 'glitter', True), (2.9, 'light', False),
                (3.3, 'emit', 'glitter', False), (3.3, 'sound', 'firework_crackle'), (4.5, 'done')]
    if kind == 'cracker_cake':
        steps = [(0.6, 'emit', 'smoke', True), (0.6, 'light', True, colour, 1.5, 7.0, 0.8, False)]
        for k in range(18):
            t = 0.6 + k * 0.45
            steps += [(t, 'emit', f'shot{k % 9}', True), (t + 0.08, 'emit', f'shot{k % 9}', False),
                      (t, 'sound', 'shot_pop')]
        return steps + [(8.8, 'light', False), (9.6, 'emit', 'smoke', False), (10.0, 'done')]
    if kind == 'roman_candle':
        steps = [(0.5, 'emit', 'stars', True), (0.5, 'emit', 'smoke', True),
                 (0.5, 'light', True, colour, 1.3, 7.0, 1.0, False)]
        steps += [(0.5 + k * 0.34, 'sound', 'shot_pop') for k in range(24)]
        return steps + [(8.6, 'emit', 'stars', False), (8.7, 'light', False), (9.5, 'emit', 'smoke', False),
                        (10.0, 'done')]
    raise ValueError(f'unknown cracker type "{kind}"')
