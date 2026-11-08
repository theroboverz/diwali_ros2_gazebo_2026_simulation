#!/usr/bin/env python3
"""Procedural asset generator for the Diwali street simulation.

Generates (all self-contained, no downloads, standard library only):
  * SDF models           -> diwali_sim/models/<name>/{model.sdf,model.config}
  * textures (PNG)       -> rangoli, kolam, banner
  * world                -> diwali_sim/worlds/diwali_street.sdf
  * controllable lights  -> diwali_sim/config/festival_lights.yaml
  * AMR cracker tour     -> diwali_sim/config/cracker_tour.yaml
  * burnable crackers    -> diwali_sim/config/crackers.yaml (burn order for cracker_show)
  * synthetic WAV files  -> diwali_festival/sounds/
  * occupancy-grid map   -> diwali_robot/maps/diwali_street.{pgm,yaml}

Run:  python3 generate_assets.py        (output is already committed; re-run after edits)
"""
import json
import math
import random
import struct
import wave
import zlib
from pathlib import Path
from xml.dom import minidom

PKG = Path(__file__).resolve().parent.parent
SRC = PKG.parent
MODELS = PKG / 'models'
WORLDS = PKG / 'worlds'
CONFIG = PKG / 'config'
SOUNDS = SRC / 'diwali_festival' / 'sounds'
MAPS = SRC / 'diwali_robot' / 'maps'
WORLD = 'diwali_street'
rnd = random.Random(7)

# ----------------------------------------------------------------------------
# Street layout (metres). Street runs along world X; road centre line y = 0.
# ----------------------------------------------------------------------------
ROAD_HALF = 3.5          # road y in [-3.5, 3.5]
SIDEWALK_OUT = 5.5       # sidewalk y in [3.5, 5.5]
WALL_Y = 6.5             # compound wall centre line |y|
STREET_X = 30.0          # barricades at both ends of the festival street
SIDEWALK_Z = 0.15        # sidewalk top surface
HOUSE_X = [-18.0, -6.0, 6.0, 18.0]
HOUSE_Y = 15.3           # house origin |y|; local +x faces the street
POLE_X = [-24.0, -12.0, 0.0, 12.0, 24.0]
POLE_Y = 4.5
SLOT_X = [-21.0, -15.0, -9.0, -3.0, 3.0, 9.0, 15.0, 21.0]   # cracker slots on both sidewalks
FW_SITES = {'fw_n1': (-27.5, 2.0), 'fw_n2': (27.5, 2.0),     # sky-shot tubes on the road at the street ends
            'fw_s1': (-27.5, -2.0), 'fw_s2': (27.5, -2.0)}
FLASH_LIGHTS = [f'flash_{k}' for k in range(6)]            # world lights cracker_show moves onto a burning cracker
CONNECT_GAPS = []        # no cross streets any more: only the centre street remains
HOME = (0.0, 0.0, 0.0)   # AMR spawn / home pose (x, y, yaw); matches robot.launch.py and AMCL initial_pose
OBST = []                # (x0, y0, x1, y1) world rectangles used for the Nav2 map


# ----------------------------------------------------------------------------
# SDF helpers
# ----------------------------------------------------------------------------
def P(t):
    t = tuple(t) + (0.0,) * (6 - len(t))
    return '<pose>' + ' '.join(f'{v:.4f}' for v in t) + '</pose>'


def box(x, y, z):
    return f'<box><size>{x:.4f} {y:.4f} {z:.4f}</size></box>'


def cyl(r, l):
    return f'<cylinder><radius>{r:.4f}</radius><length>{l:.4f}</length></cylinder>'


def sph(r):
    return f'<sphere><radius>{r:.4f}</radius></sphere>'


def mat(rgb, rough=0.8, metal=0.0, emis=None, albedo=None, alpha=1.0):
    r, g, b = (c / 255.0 for c in rgb)
    s = (f'<material><ambient>{r:.3f} {g:.3f} {b:.3f} {alpha}</ambient>'
         f'<diffuse>{r:.3f} {g:.3f} {b:.3f} {alpha}</diffuse>'
         f'<specular>0.2 0.2 0.2 1</specular>')
    if emis:
        er, eg, eb = (c / 255.0 for c in emis)
        s += f'<emissive>{er:.3f} {eg:.3f} {eb:.3f} 1</emissive>'
    s += '<pbr><metal>'
    if albedo:
        s += f'<albedo_map>{albedo}</albedo_map>'
    s += f'<roughness>{rough}</roughness><metalness>{metal}</metalness></metal></pbr></material>'
    return s


def vis(name, geom, pose=(0, 0, 0), material='', shadow=True):
    sh = '' if shadow else '<cast_shadows>false</cast_shadows>'
    return (f'<visual name="{name}">{P(pose)}<geometry>{geom}</geometry>{material}{sh}</visual>')


def col(name, geom, pose=(0, 0, 0)):
    return f'<collision name="{name}">{P(pose)}<geometry>{geom}</geometry></collision>'


def link(name, body):
    return f'<link name="{name}">{body}</link>'


def spans(a, b, gaps):
    """The interval [a, b] with the (g0, g1) gaps cut out."""
    out, cur = [], a
    for g0, g1 in sorted(gaps):
        if g0 > cur:
            out.append((cur, g0))
        cur = max(cur, g1)
    if cur < b:
        out.append((cur, b))
    return out


def kerb(x0, y0, x1, y1):
    """Kerbs (0.14-0.15 m) sit below the 0.30 m LiDAR plane, so draw them into the Nav2 map as 0.1 m lines."""
    OBST.append((min(x0, x1) - 0.05, min(y0, y1) - 0.05, max(x0, x1) + 0.05, max(y0, y1) + 0.05))


def pretty(xml):
    d = minidom.parseString(xml.encode('utf-8'))
    s = d.toprettyxml(indent='  ')
    return '\n'.join(l for l in s.split('\n') if l.strip()) + '\n'


def write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def write_model(name, desc, body, static=True):
    sdf = (f'<sdf version="1.9"><model name="{name}"><static>{str(static).lower()}</static>'
           f'{body}</model></sdf>')
    write(MODELS / name / 'model.sdf', pretty(sdf))
    cfg = (f'<model><name>{name}</name><version>1.0</version>'
           f'<sdf version="1.9">model.sdf</sdf>'
           f'<author><name>diwali_sim generator</name><email>none@example.com</email></author>'
           f'<description>{desc}</description></model>')
    write(MODELS / name / 'model.config', pretty(cfg))


# ----------------------------------------------------------------------------
# Textures (pure-python PNG writer)
# ----------------------------------------------------------------------------
def write_png(path, wd, ht, fn):
    raw = bytearray()
    for j in range(ht):
        raw.append(0)
        for i in range(wd):
            raw += bytes(fn((i + 0.5) / wd, 1.0 - (j + 0.5) / ht))
    ctype = 6 if len(fn(0.5, 0.5)) == 4 else 2

    def chunk(t, d):
        c = struct.pack('>I', len(d)) + t + d
        return c + struct.pack('>I', zlib.crc32(t + d) & 0xffffffff)

    png = (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', wd, ht, 8, ctype, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + chunk(b'IEND', b''))
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_bytes(png)


def rangoli_px(u, v):
    x, y = u * 2 - 1, v * 2 - 1
    r, th = math.hypot(x, y), math.atan2(y, x)
    ground = (62, 56, 52)
    if r > 0.97:
        return ground
    if r > 0.90:                                   # beaded border
        return (245, 245, 235) if int((th + math.pi) * 24 / math.pi) % 2 == 0 else (200, 30, 60)
    petals = [(214, 40, 80), (255, 140, 0), (255, 205, 0), (30, 150, 70)]
    if 0.45 < r < 0.40 + 0.48 * abs(math.cos(4 * th)):   # outer lotus petals
        return petals[int((th + math.pi) / (math.pi / 4)) % 4]
    if r > 0.45:
        return (40, 36, 100)
    if r > 0.30:                                   # ring
        return (250, 250, 250) if int((th + math.pi) * 6 / math.pi) % 2 == 0 else (40, 70, 180)
    if r < 0.06:
        return (255, 255, 255)
    if r < 0.12 + 0.18 * abs(math.cos(4 * th + math.pi / 8)):
        return (255, 210, 0)
    return (230, 60, 120)


def kolam_px(u, v):
    x, y = u * 2 - 1, v * 2 - 1
    ground = (52, 50, 56)
    if abs(x) + abs(y) > 0.92:
        return ground
    k = math.pi / 0.2
    val = math.cos(k * (x + y)) + math.cos(k * (x - y))
    if abs(val) < 0.16:
        return (245, 245, 240)                      # rice-flour lines
    dx = (x / 0.2 + 0.5) % 1.0 - 0.5
    dy = (y / 0.2 + 0.5) % 1.0 - 0.5
    if dx * dx + dy * dy < 0.012:
        return (255, 255, 255)                      # pulli dots
    return ground


def banner_px(u, v):
    if v < 0.14 or v > 0.86:
        tri = abs(((u * 40) % 1.0) - 0.5) * 2
        if abs((v if v < 0.5 else 1 - v) - (0.05 + 0.05 * tri)) < 0.018:
            return (255, 205, 60)
        return (150, 20, 35)
    uc = (math.floor(u * 12) + 0.5) / 12
    dx, dy = (u - uc) * 4.0, v - 0.5
    r2 = dx * dx + dy * dy
    if r2 < 0.012:
        return (255, 245, 170)
    if r2 < 0.03:
        return (255, 120, 20)
    if r2 < 0.06:
        return (230, 170, 30)
    return (255, 150, 10)


# ----------------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------------
BRASS = (205, 155, 60)


def make_diya(name, lit):
    flame = (255, 140, 20)
    V = [
        vis('foot', cyl(0.03, 0.012), (0, 0, 0.006), mat(BRASS, 0.35, 0.7)),
        vis('bowl', cyl(0.05, 0.022), (0, 0, 0.023), mat(BRASS, 0.3, 0.8)),
        vis('oil', cyl(0.042, 0.004), (0, 0, 0.035), mat((70, 40, 10), 0.2)),
        vis('lip', box(0.05, 0.03, 0.02), (0.055, 0, 0.03), mat(BRASS, 0.3, 0.8)),
        vis('wick', cyl(0.003, 0.02), (0.06, 0, 0.045), mat((30, 20, 10), 0.9)),
        vis('flame', sph(0.014), (0.06, 0, 0.064), mat(flame, 0.5, emis=(255, 170, 40)), shadow=False),
    ]
    L = ''
    if lit:   # real light source: emissive materials do NOT illuminate neighbours
        L = ('<light name="flame_light" type="point">' + P((0.06, 0, 0.09)) +
             '<cast_shadows>false</cast_shadows><diffuse>1 0.62 0.22 1</diffuse>'
             '<specular>1 0.55 0.2 1</specular><intensity>0.7</intensity>'
             '<attenuation><range>3</range><constant>0.2</constant><linear>0.6</linear>'
             '<quadratic>1.0</quadratic></attenuation></light>')
    write_model(name, 'Brass oil lamp (diya) with emissive flame' + (' and point light' if lit else ''),
                link('link', ''.join(V) + L))


def make_rangoli(name, tex, size, fn, thick=0.004):
    img = f'model://rangoli/materials/textures/{tex}'
    V = vis('floor_art', box(size, size, thick), (0, 0, thick / 2),
            mat((255, 255, 255), 0.9, albedo=img), shadow=False)
    write_model(name, 'Texture-based floor decoration (visual only, no collision)', link('link', V))


def curve(L, n, sag):
    pts = []
    for k in range(n):
        t = k / (n - 1)
        pts.append(((t - 0.5) * L, -sag * (1 - (2 * t - 1) ** 2)))
    return pts


def wire(pts, prefix, rgb):
    out = []
    for k in range(len(pts) - 1):
        (x0, z0), (x1, z1) = pts[k], pts[k + 1]
        ln = math.hypot(x1 - x0, z1 - z0)
        out.append(vis(f'{prefix}{k}', box(ln, 0.012, 0.012), ((x0 + x1) / 2, 0, (z0 + z1) / 2, 0,
                       -math.atan2(z1 - z0, x1 - x0), 0), mat(rgb, 0.7), shadow=False))
    return out


def make_led_string(name, L, n, sag):
    cols = [(255, 40, 40), (40, 255, 80), (60, 120, 255), (255, 210, 40), (255, 60, 220)]
    pts = curve(L, n, sag)
    V = wire(pts, 'w', (25, 25, 25))
    for k, (x, z) in enumerate(pts):
        c = cols[k % 5]
        V.append(vis(f'bulb{k}', sph(0.035), (x, 0, z - 0.04), mat(c, 0.3, emis=c), shadow=False))
    write_model(name, f'Decorative LED string {L} m (emissive bulbs, visual only)', link('link', ''.join(V)))


def make_garland(name, L, n, sag):
    cols = [(255, 120, 0), (255, 190, 10), (230, 90, 0)]
    pts = curve(L, n, sag)
    V = []
    for k, (x, z) in enumerate(pts):
        V.append(vis(f'f{k}', sph(0.045), (x, 0, z), mat(cols[k % 3], 0.9), shadow=False))
        if k % 4 == 2:
            for j in range(1, 4):
                V.append(vis(f'f{k}_s{j}', sph(0.04), (x, 0, z - 0.11 * j), mat(cols[(k + j) % 3], 0.9),
                             shadow=False))
    write_model(name, f'Marigold flower garland {L} m (visual only)', link('link', ''.join(V)))


def make_toran(name):
    V = [vis('string', box(1.6, 0.015, 0.015), (0, 0, 0), mat((90, 60, 30)), shadow=False)]
    for k in range(9):
        x = -0.7 + k * 0.175
        V.append(vis(f'leaf{k}', box(0.07, 0.015, 0.2), (x, 0, -0.1), mat((35, 120, 45), 0.8), shadow=False))
        V.append(vis(f'flower{k}', sph(0.04), (x + 0.087, 0, -0.05), mat((255, 150, 0), 0.9), shadow=False))
    write_model(name, 'Mango-leaf and marigold door toran (visual only)', link('link', ''.join(V)))


def make_streetlight():
    V = [vis('pole', cyl(0.06, 6.0), (0, 0, 3.0), mat((50, 52, 56), 0.5, 0.6)),
         vis('base', cyl(0.12, 0.3), (0, 0, 0.15), mat((50, 52, 56), 0.5, 0.6)),
         vis('arm', box(1.3, 0.06, 0.06), (0.6, 0, 5.95), mat((50, 52, 56), 0.5, 0.6)),
         vis('head', box(0.55, 0.22, 0.08), (1.2, 0, 5.93), mat((60, 60, 60), 0.5, 0.5)),
         vis('lens', box(0.45, 0.16, 0.02), (1.2, 0, 5.88), mat((255, 225, 160), 0.3, emis=(255, 215, 140)),
             shadow=False)]
    C = [col('pole', cyl(0.1, 6.0), (0, 0, 3.0))]
    L = ('<light name="lamp" type="spot">' + P((1.2, 0, 5.85)) +
         '<cast_shadows>false</cast_shadows><diffuse>1 0.84 0.55 1</diffuse>'
         '<specular>0.6 0.5 0.3 1</specular><intensity>3</intensity>'
         '<attenuation><range>16</range><constant>0.5</constant><linear>0.04</linear>'
         '<quadratic>0.008</quadratic></attenuation><direction>0 0 -1</direction>'
         '<spot><inner_angle>0.5</inner_angle><outer_angle>1.15</outer_angle><falloff>1.0</falloff></spot>'
         '</light>')
    write_model('streetlight', 'Sodium-style streetlight with spot light (pole collision only)',
                link('link', ''.join(V) + ''.join(C) + L))


def make_banner():
    tex = 'model://festival_banner/materials/textures/banner.png'
    V = [vis('cloth_front', box(9.2, 0.02, 0.95), (0, 0.01, 4.15), mat((255, 255, 255), 0.95, albedo=tex), shadow=False),
         vis('cloth_back', box(9.2, 0.02, 0.95), (0, -0.01, 4.15), mat((255, 255, 255), 0.95, albedo=tex), shadow=False),
         vis('bar', cyl(0.025, 9.6), (0, 0, 4.7), mat((60, 40, 20)), shadow=False)]
    V[2] = V[2].replace('<pose>0.0000 0.0000 4.7000 0.0000 0.0000 0.0000</pose>',
                        '<pose>0.0000 0.0000 4.7000 0.0000 1.5708 0.0000</pose>')
    C = []
    for s in (-1, 1):
        V.append(vis(f'pole{s}', cyl(0.05, 4.9), (s * 4.8, 0, 2.45), mat((70, 70, 75), 0.6, 0.5)))
        C.append(col(f'pole{s}', cyl(0.07, 4.9), (s * 4.8, 0, 2.45)))
    write_model('festival_banner', 'Deepavali banner on two poles (pole collision only)',
                link('link', ''.join(V) + ''.join(C)))


def make_house(name, wall, trim):
    V, C = [], []
    stone, oxide, roof, rib = (155, 145, 130), (140, 55, 40), (170, 80, 50), (120, 50, 35)
    wood = (95, 55, 30)
    V.append(vis('plinth', box(9.6, 8.6, 0.5), (1.0, 0, 0.25), mat(stone, 0.9)))
    V.append(vis('plinth_stripe', box(9.64, 8.64, 0.07), (1.0, 0, 0.45), mat((170, 50, 35), 0.9)))
    V.append(vis('step1', box(0.5, 2.4, 0.32), (6.05, 0, 0.16), mat(stone, 0.9)))
    V.append(vis('step2', box(0.5, 2.4, 0.16), (6.55, 0, 0.08), mat(stone, 0.9)))
    V.append(vis('body', box(7.0, 8.0, 3.2), (0, 0, 2.1), mat(wall, 0.85)))
    V.append(vis('base_band', box(7.06, 8.06, 0.45), (0, 0, 0.725), mat(oxide, 0.9)))
    V.append(vis('door_frame', box(0.12, 1.5, 2.3), (3.52, 0, 1.65), mat(trim, 0.7)))
    V.append(vis('door', box(0.08, 1.2, 2.15), (3.58, 0, 1.575), mat(wood, 0.7)))
    V.append(vis('door_knob', sph(0.03), (3.64, 0.4, 1.5), mat(BRASS, 0.3, 0.8)))
    for s, sg in (('l', -1), ('r', 1)):
        y = sg * 2.6
        V.append(vis(f'win_frame_{s}', box(0.1, 1.1, 1.2), (3.52, y, 2.1), mat(trim, 0.7)))
        V.append(vis(f'win_glow_{s}', box(0.05, 0.9, 1.0), (3.57, y, 2.1),
                     mat((255, 190, 100), 0.4, emis=(150, 95, 40)), shadow=False))
        for b in range(5):
            V.append(vis(f'win_bar_{s}{b}', box(0.03, 0.03, 1.0), (3.62, y - 0.36 + b * 0.18, 2.1),
                         mat((25, 25, 25), 0.5, 0.5)))
    for k, y in enumerate((-3.9, -1.3, 1.3, 3.9)):       # thinnai pillars
        V.append(vis(f'pillar{k}', cyl(0.1, 2.4), (5.5, y, 1.7), mat((232, 226, 210), 0.8)))
    V.append(vis('veranda_beam', box(0.15, 8.8, 0.15), (5.7, 0, 2.85), mat(wood, 0.7)))

    def slab(nm, cx, cz, length, width, thick, th):
        V.append(vis(nm, box(length, width, thick), (cx, 0, cz, 0, th, 0), mat(roof, 0.75)))
        s, k = -length / 2 + 0.25, 0
        while s < length / 2 - 0.1:
            h = thick / 2 + 0.02
            V.append(vis(f'{nm}_rib{k}', box(0.07, width, 0.04),
                         (cx + s * math.cos(th) + h * math.sin(th), 0, cz - s * math.sin(th) + h * math.cos(th),
                          0, th, 0), mat(rib, 0.8)))
            s += 0.42
            k += 1

    th = math.atan2(1.5, 4.2)
    slab('roof_front', 2.1, 4.26, 4.46, 9.0, 0.12, th)
    slab('roof_back', -2.1, 4.26, 4.46, 9.0, 0.12, -th)
    slab('veranda_roof', 4.65, 3.16, 2.335, 8.8, 0.1, 0.172)
    V.append(vis('ridge', cyl(0.12, 9.0), (0, 0, 5.02, math.pi / 2, 0, 0), mat((140, 60, 40), 0.8)))
    for k, w_ in enumerate((5.8, 3.47, 1.2)):             # stepped gable infill
        for sg in (-1, 1):
            V.append(vis(f'gable{k}_{sg}', box(w_, 0.3, 0.42), (0, sg * 3.85, 3.91 + 0.42 * k), mat(wall, 0.85)))
    # tulasi maadam in the yard
    V.append(vis('tulasi_base', box(0.6, 0.6, 0.6), (7.0, -2.8, 0.3), mat((235, 230, 220), 0.9)))
    V.append(vis('tulasi_stripe', box(0.62, 0.62, 0.1), (7.0, -2.8, 0.45), mat(oxide, 0.9)))
    V.append(vis('tulasi_top', cyl(0.22, 0.12), (7.0, -2.8, 0.66), mat((235, 230, 220), 0.9)))
    V.append(vis('tulasi_plant', sph(0.24), (7.0, -2.8, 0.95), mat((40, 130, 50), 0.9)))
    C.append(col('body', box(9.6, 8.6, 5.0), (1.0, 0, 2.5)))
    C.append(col('steps', box(1.4, 2.4, 0.3), (6.3, 0, 0.15)))
    C.append(col('tulasi', box(0.6, 0.6, 0.9), (7.0, -2.8, 0.45)))
    write_model(name, 'South Indian (Tamil) residential house: raised plinth, thinnai veranda, '
                'clay-tile gable roof, tulasi maadam. Single simplified collision box.',
                link('link', ''.join(V) + ''.join(C)))


# ----------------------------------------------------------------------------
# Particle effects
# ----------------------------------------------------------------------------
# Gazebo Harmonic's ogre2 particle renderer IGNORES <color_start>/<color_end> (it logs "ParticleEmitter
# SetColorRange is currently disabled"), which is why plain emitters render as white squares. Colour comes
# from a <color_range_image> instead (left = birth, right = death; its alpha fades the particle out) and the
# round glow from a soft spark texture used as the particle material's albedo map.
# Emitters have no spread angle and particles feel no gravity: every emitter is a straight jet along its
# local +X, so fountains / bursts / spinners are built from several jets pointing in different directions.
FX = 'model://cracker_fx/materials/textures'
# <color_range_image> only accepts an absolute file path (no model:// URI, no relative path), so the world
# carries the placeholder below and diwali_world.launch.py substitutes the installed texture directory.
FX_PLACEHOLDER = '@DIWALI_FX_DIR@'
RANGE_BASE = {'base': FX_PLACEHOLDER}
FX_DIR = MODELS / 'cracker_fx' / 'materials' / 'textures'

# colour: (white-hot core, main colour, dying ember) as 0-255 RGB
PALETTE = {
    'gold': ((255, 250, 225), (255, 185, 40), (210, 70, 5)),
    'silver': ((255, 255, 255), (215, 228, 255), (120, 140, 210)),
    'red': ((255, 225, 200), (255, 35, 25), (150, 0, 20)),
    'green': ((235, 255, 220), (50, 255, 70), (0, 120, 40)),
    'blue': ((225, 235, 255), (50, 100, 255), (20, 25, 170)),
    'pink': ((255, 230, 245), (255, 55, 170), (160, 20, 120)),
    'purple': ((245, 225, 255), (175, 70, 255), (90, 20, 170)),
    'fire': ((255, 255, 225), (255, 160, 30), (220, 45, 0)),
    'flash': ((255, 255, 255), (255, 240, 160), (255, 110, 20)),
}
CRACKER_COLOURS = ('gold', 'red', 'green', 'blue', 'pink', 'purple', 'silver')


def range_px(name):
    hot, main, ember = PALETTE[name]

    def f(u, v):
        if u < 0.2:                                   # white-hot when born
            t = u / 0.2
            c = [h + (m - h) * t for h, m in zip(hot, main)]
        elif u < 0.65:                                # its real colour for most of its life
            c = list(main)
        else:                                         # cooling ember, fading out
            t = (u - 0.65) / 0.35
            c = [m + (e - m) * t for m, e in zip(main, ember)]
        a = 1.0 if u < 0.6 else max(0.0, 1.0 - (u - 0.6) / 0.4) ** 1.2
        return (*(int(x) for x in c), int(255 * a))
    return f


def smoke_range_px(u, v):
    g = int(85 - 35 * u)                              # thin grey haze: particles blend additively-ish,
    a = min(1.0, u / 0.15) * (1.0 - u)                # so smoke must stay faint or it glows white
    return (g, g, g + 5, int(55 * max(0.0, a)))


def spark_px(u, v):
    r = math.hypot(u - 0.5, v - 0.5) * 2
    core = max(0.0, 1.0 - r) ** 2.0
    return (255, 255, 255, int(255 * min(1.0, core * 1.7)))


def smoke_px(u, v):
    r = math.hypot(u - 0.5, v - 0.5) * 2
    n = 0.5 + 0.25 * math.sin(u * 23.0 + math.sin(v * 17.0) * 2) + 0.25 * math.sin(v * 31.0 + u * 7.0)
    return (255, 255, 255, int(255 * max(0.0, 1.0 - r) ** 1.6 * (0.55 + 0.45 * n)))


def build_fx_textures():
    write_png(FX_DIR / 'spark.png', 64, 64, spark_px)
    write_png(FX_DIR / 'smoke.png', 64, 64, smoke_px)
    for name in PALETTE:
        write_png(FX_DIR / f'range_{name}.png', 64, 4, range_px(name))
    write_png(FX_DIR / 'range_smoke.png', 64, 4, smoke_range_px)
    write_model('cracker_fx', 'Particle textures shared by every cracker: spark/smoke sprites and colour ramps',
                link('link', ''))


def unit(d):
    n = math.sqrt(sum(c * c for c in d))
    return tuple(c / n for c in d)


# Gazebo's ParticleEmitter system keeps ONE emitter per topic: emitters sharing a topic do not all react.
# Every jet therefore gets its own topic <part topic>/<k>; config/emitter_topics.yaml maps each part topic to
# its jet count and GzInterface.set_emitting(<part topic>) fans out to all of them.
EMITTER_TOPICS = {}


def fx(name, topic, colour, pos, direction=(0, 0, 1), rate=100, life=1.0, vmin=1.0, vmax=2.0, psize=0.05,
       kind='box', size=(0.02, 0.02, 0.02), tex='spark', scale=None, emitting=False):
    """One particle jet. `direction` is the world-frame (model-frame) spray direction."""
    dx, dy, dz = unit(direction)
    yaw, pitch = math.atan2(dy, dx), -math.asin(max(-1.0, min(1.0, dz)))
    s = f'<scale_rate>{scale}</scale_rate>' if scale is not None else ''
    rng = 'smoke' if tex == 'smoke' else colour
    k = EMITTER_TOPICS.get(topic, 0)
    EMITTER_TOPICS[topic] = k + 1
    topic = f'{topic}/{k}'
    return (f'<particle_emitter name="pe_{name}" type="{kind}"><emitting>{str(emitting).lower()}</emitting>'
            f'<size>{size[0]} {size[1]} {size[2]}</size><particle_size>{psize} {psize} {psize}</particle_size>'
            f'<lifetime>{life}</lifetime><min_velocity>{vmin}</min_velocity><max_velocity>{vmax}</max_velocity>'
            f'<rate>{rate}</rate>{P(tuple(pos) + (0.0, pitch, yaw))}'
            f'<material><diffuse>1 1 1 1</diffuse><specular>0 0 0 1</specular>'
            f'<pbr><metal><albedo_map>{FX}/{tex}.png</albedo_map></metal></pbr></material>'
            f'<color_range_image>{RANGE_BASE["base"]}/range_{rng}.png</color_range_image>{s}<topic>{topic}</topic>'
            '</particle_emitter>')


def cone_dirs(rings):
    """rings: [(tilt_rad, count)] -> spray directions around +Z."""
    out = []
    for r, (tilt, n) in enumerate(rings):
        for k in range(n):
            a = 2 * math.pi * (k + 0.5 * r) / n
            out.append((math.sin(tilt) * math.cos(a), math.sin(tilt) * math.sin(a), math.cos(tilt)))
    return out


def sphere_dirs(n, min_z=-1.0):
    """Fibonacci sphere, optionally dropping the directions below min_z."""
    out, g = [], math.pi * (3 - math.sqrt(5))
    for k in range(n):
        z = 1 - 2 * (k + 0.5) / n
        r = math.sqrt(1 - z * z)
        if z >= min_z:
            out.append((r * math.cos(g * k), r * math.sin(g * k), z))
    return out


def jets(prefix, topic, colour, pos, dirs, **kw):
    return ''.join(fx(f'{prefix}{k}', topic, colour, pos, d, **kw) for k, d in enumerate(dirs))


def smoke(name, topic, pos, rate=12, life=3.0, psize=0.45, size=(0.15, 0.15, 0.15), vmin=0.25, vmax=0.6):
    return fx(name, topic, 'smoke', pos, (0, 0, 1), rate=max(2, int(rate * 0.5)), life=life, vmin=vmin,
              vmax=vmax, psize=round(psize * 0.6, 3), kind='box', size=size, tex='smoke', scale=0.35)


# ---- cracker bodies ---
# WHY PARTS ARE PARKED: every gz.msgs.ParticleEmitter command makes gz-sim resend the whole emitter, which
# marks it dirty in gz-rendering's ogre2 backend; the particle system is then destroyed and rebuilt, and
# its first update sprays long white streaks for ~0.5 s. So each separately-switched piece of an effect
# (fuse, fountain, bang, pop, burst...) is its own model, parked PARK_Z below the street. cracker_show
# switches its emitters on while it is parked (the rebuild glitch happens out of sight), waits, and then
# teleports it into place with /world/<w>/set_pose -- moving a model never rebuilds its emitters.
PARK_Z = -30.0
# A cracker = a visible static body model + one parked model per part. Part emitters listen on
# /festival/cracker/<id>/<part>/<k> (see EMITTER_TOPICS); config/crackers.yaml lists models and poses.
BUSUVANAM_H, BUSUVANAM_R = 0.28, 0.11


def write_obj_frustum(path, r0, r1, h, n=32):
    """Truncated cone with side UVs (u around, v up) plus base and top discs."""
    v, vt, vn, f = [], [], [], []
    slope = (r0 - r1) / h
    for k in range(n + 1):
        a = 2 * math.pi * k / n
        c, s = math.cos(a), math.sin(a)
        v += [(r0 * c, r0 * s, 0.0), (r1 * c, r1 * s, h)]
        vt += [(k / n, 0.0), (k / n, 1.0)]
        nn = unit((c, s, slope))
        vn += [nn, nn]
    for k in range(n):
        a, b, c2, d = 2 * k + 1, 2 * k + 2, 2 * k + 3, 2 * k + 4
        f += [((a, a, a), (c2, c2, c2), (d, d, d)), ((a, a, a), (d, d, d), (b, b, b))]
    for z, r, up in ((0.0, r0, -1.0), (h, r1, 1.0)):     # discs (centre vertex + rim)
        base = len(v) + 1
        v.append((0.0, 0.0, z))
        vt.append((0.5, 0.5))
        vn.append((0.0, 0.0, up))
        for k in range(n + 1):
            a = 2 * math.pi * k / n
            v.append((r * math.cos(a), r * math.sin(a), z))
            vt.append((0.5 + 0.5 * math.cos(a), 0.5 + 0.5 * math.sin(a)))
            vn.append((0.0, 0.0, up))
        for k in range(n):
            p, q = base + 1 + k, base + 2 + k
            tri = (base, p, q) if up > 0 else (base, q, p)
            f.append(tuple((i, i, i) for i in tri))
    out = ['# busuvanam (flower pot) cone, generated by generate_assets.py']
    out += [f'v {x:.5f} {y:.5f} {z:.5f}' for x, y, z in v]
    out += [f'vt {a:.5f} {b:.5f}' for a, b in vt]
    out += [f'vn {x:.5f} {y:.5f} {z:.5f}' for x, y, z in vn]
    out += ['f ' + ' '.join(f'{a}/{b}/{c}' for a, b, c in tri) for tri in f]
    write(path, '\n'.join(out) + '\n')


def busuvanam_px(u, v):
    """Paper wrapper of a Tamil busuvanam: red body, gold/green bands, white star/diamond print."""
    if v < 0.08 or 0.9 < v:
        return (40, 140, 70)
    if 0.08 <= v < 0.13 or 0.84 < v <= 0.9:
        return (245, 195, 40)
    if 0.42 < v < 0.58:                                       # label band with a lamp motif
        cx = (u * 6) % 1.0
        d = math.hypot((cx - 0.5) * 1.6, (v - 0.5) * 9)
        if d < 0.35:
            return (255, 150, 20) if d < 0.18 else (250, 235, 160)
        return (245, 235, 205)
    gu, gv = (u * 12) % 1.0, (v * 9) % 1.0
    if abs(gu - 0.5) + abs(gv - 0.5) < 0.18:                 # diamond print
        return (255, 225, 90)
    if (gu - 0.5) ** 2 + (gv - 0.5) ** 2 > 0.2:
        return (120, 10, 25)
    return (205, 25, 40)


def pattasu_px(u, v):
    """Red paper wrap with a gold band and a black 'bolt' mark, like a lakshmi vedi."""
    if 0.42 < v < 0.62:
        bolt = abs((u * 4) % 1.0 - 0.5 - (v - 0.52) * 2.5) < 0.08
        return (30, 30, 30) if bolt else (250, 200, 50)
    if v < 0.06 or v > 0.94:
        return (60, 130, 60)
    return (200, 20, 30) if int(u * 24 + v * 6) % 2 else (175, 15, 25)


def part(xml, dz=0.0, visuals='', dynamic=False):
    """One independently switched piece of a cracker effect (its own parked model)."""
    return dict(xml=xml, dz=dz, visuals=visuals, dynamic=dynamic)


def busuvanam_parts(cid, colour):
    t = f'/festival/cracker/{cid}'
    h = BUSUVANAM_H
    V = vis('cone', f'<mesh><uri>model://flower_pot/meshes/busuvanam.obj</uri></mesh>', (0, 0, 0),
            mat((255, 255, 255), 0.75, albedo='model://flower_pot/materials/textures/busuvanam_wrap.png'),
            shadow=False)
    V += vis('mouth', cyl(0.024, 0.01), (0, 0, h + 0.004), mat((35, 25, 20), 0.9), shadow=False)
    V += vis('fuse', cyl(0.003, 0.05), (0, 0, h + 0.03), mat((90, 60, 30), 0.9), shadow=False)
    top = (0, 0, h + 0.01)
    fountain = jets('core', f'{t}/fountain', 'fire', top, cone_dirs([(0.0, 1), (0.1, 4)]), rate=170, life=0.9,
                    vmin=2.8, vmax=4.8, psize=0.08)
    fountain += jets('fan', f'{t}/fountain', colour, top, cone_dirs([(0.22, 6), (0.38, 8), (0.52, 8)]),
                     rate=120, life=0.85, vmin=2.0, vmax=4.2, psize=0.075)
    return V, {
        'fuse': part(fx('fuse', f'{t}/fuse', 'fire', (0, 0, h + 0.055), (0, 0, 1), rate=80, life=0.25, vmin=0.3,
                        vmax=0.9, psize=0.025)),
        'fountain': part(fountain),
        'glitter': part(fx('glitter', f'{t}/glitter', 'silver', (0, 0, 1.5), (0, 0, 1), rate=260, life=0.25,
                           vmin=0.05, vmax=0.3, psize=0.03, kind='ellipsoid', size=(1.3, 1.3, 2.2))),
        'smoke': part(smoke('smoke', f'{t}/smoke', top, rate=10, life=3.5, psize=0.55)),
    }


def chakkar_visuals():
    V = vis('wheel', cyl(0.075, 0.025), (0, 0, 0), mat((40, 130, 70), 0.6), shadow=False)
    V += vis('coil', cyl(0.05, 0.027), (0, 0, 0.001), mat((230, 200, 60), 0.5), shadow=False)
    V += vis('ring', cyl(0.03, 0.028), (0, 0, 0.001), mat((200, 30, 40), 0.6), shadow=False)
    V += vis('hub', cyl(0.012, 0.03), (0, 0, 0.002), mat((240, 240, 230), 0.6), shadow=False)
    return V


def chakkar_parts(cid, colour):
    """Sanguchakaram: the static wheel is swapped for a spinner (gravity-free, VelocityControl) whose three
    rim jets throw tangential sparks, so the spinning wheel draws a spiral of fire."""
    t = f'/festival/cracker/{cid}'
    spin = ''
    for k in range(3):
        a = 2 * math.pi * k / 3
        pos = (0.078 * math.cos(a), 0.078 * math.sin(a), 0.005)
        tang = (-math.sin(a), math.cos(a), 0.12)
        spin += fx(f'spin{k}', f'{t}/spin', colour if k else 'fire', pos, tang, rate=320, life=0.45, vmin=1.6,
                   vmax=3.2, psize=0.045)
    spin += fx('ring_glow', f'{t}/spin', 'fire', (0, 0, 0.03), (0, 0, 1), rate=150, life=0.12, vmin=0.0,
               vmax=0.1, psize=0.05, kind='cylinder', size=(0.2, 0.2, 0.02))
    return chakkar_visuals(), {
        'fuse': part(fx('fuse', f'{t}/fuse', 'fire', (0.075, 0, 0.01), (1, 0, 0.3), rate=80, life=0.25, vmin=0.3,
                        vmax=0.8, psize=0.025)),
        'spin': part(spin, visuals=chakkar_visuals(), dynamic=True),
        'smoke': part(smoke('smoke', f'{t}/smoke', (0, 0, 0.05), rate=6, life=2.5, psize=0.4, size=(0.3, 0.3, 0.05))),
    }


def pattasu_parts(cid, colour):
    t = f'/festival/cracker/{cid}'
    V = vis('body', cyl(0.03, 0.1), (0, 0, 0.05),
            mat((255, 255, 255), 0.7, albedo='model://pattasu/materials/textures/pattasu_wrap.png'), shadow=False)
    V += vis('cap', cyl(0.031, 0.006), (0, 0, 0.101), mat((60, 130, 60), 0.7), shadow=False)
    V += vis('fuse', cyl(0.0025, 0.05), (0, 0, 0.125), mat((90, 60, 30), 0.9), shadow=False)
    bang = jets('bang', f'{t}/bang', 'flash', (0, 0, 0.08), sphere_dirs(22, -0.3), rate=1100, life=0.28,
                vmin=2.5, vmax=6.5, psize=0.075)
    bang += jets('paper', f'{t}/bang', 'red', (0, 0, 0.08), sphere_dirs(8, 0.2), rate=300, life=0.7, vmin=0.6,
                 vmax=1.8, psize=0.03)
    return V, {
        'fuse': part(fx('fuse', f'{t}/fuse', 'fire', (0, 0, 0.15), (0, 0, 1), rate=90, life=0.22, vmin=0.3,
                        vmax=0.9, psize=0.025)),
        'bang': part(bang),
        'smoke': part(smoke('smoke', f'{t}/smoke', (0, 0, 0.25), rate=45, life=3.0, psize=0.55,
                            size=(0.35, 0.35, 0.3))),
    }


SARAVEDI_N, SARAVEDI_PITCH, SARAVEDI_POPS = 30, 0.045, 8


def saravedi_body():
    """Saravedi: a fuse cord threaded with red/green crackers, laid along local X."""
    L = (SARAVEDI_N - 1) * SARAVEDI_PITCH
    V = vis('fuse', box(L + 0.1, 0.006, 0.006), (0, 0, 0.012), mat((70, 60, 40), 0.9), shadow=False)
    for k in range(SARAVEDI_N):
        side = 1 if k % 2 else -1
        x = -L / 2 + k * SARAVEDI_PITCH
        V += vis(f'c{k}', cyl(0.009, 0.05), (x, side * 0.022, 0.012, math.pi / 2, 0, 0),
                 mat((210, 30, 30) if k % 3 else (40, 150, 60), 0.6), shadow=False)
    return V


def saravedi_parts(cid, colour):
    t = f'/festival/cracker/{cid}'
    L = (SARAVEDI_N - 1) * SARAVEDI_PITCH
    P_ = {}
    for k in range(SARAVEDI_POPS):
        x = -L / 2 + L * k / (SARAVEDI_POPS - 1)
        P_[f'pop{k}'] = part(jets(f'pop{k}_', f'{t}/pop{k}', 'flash', (x, 0, 0.03),
                                  [(0.6, 0.5, 1), (-0.5, -0.6, 1), (0.1, -0.2, 1), (-0.7, 0.4, 0.5)],
                                  rate=1400, life=0.16, vmin=1.5, vmax=3.8, psize=0.055))
    P_['paper'] = part(fx('paper', f'{t}/paper', 'red', (0, 0, 0.05), (0, 0, 1), rate=120, life=0.8, vmin=0.4,
                          vmax=1.4, psize=0.025, kind='box', size=(L, 0.1, 0.05)))
    P_['smoke'] = part(smoke('smoke', f'{t}/smoke', (0, 0, 0.15), rate=40, life=3.0, psize=0.5, size=(L, 0.2, 0.1)))
    return saravedi_body(), P_


ROCKET_APEX = 20.0


def rocket_visuals(colour):
    V = vis('stick', cyl(0.003, 0.55), (0, 0, 0.275), mat((180, 150, 100), 0.9), shadow=False)
    V += vis('body', cyl(0.016, 0.13), (0, 0, 0.5), mat(tuple(PALETTE[colour][1]), 0.5), shadow=False)
    V += vis('band', cyl(0.0165, 0.02), (0, 0, 0.47), mat((240, 200, 60), 0.4), shadow=False)
    V += vis('tip', sph(0.016), (0, 0, 0.565), mat((235, 235, 235), 0.6), shadow=False)
    return V


def rocket_parts(cid, colour, base_z=0.0):
    """The static rocket in the bottle is swapped for the 'trail' part (same visuals + exhaust) which
    cracker_show flies up; its exhaust is emitted in world space so it leaves a trail. The burst and glitter
    parts are placed at the apex."""
    t = f'/festival/cracker/{cid}'
    trail = fx('trail', f'{t}/trail', 'fire', (0, 0, 0.43), (0, 0, -1), rate=420, life=0.5, vmin=0.4, vmax=1.4,
               psize=0.07)
    trail += smoke('exhaust', f'{t}/trail', (0, 0, 0.4), rate=30, life=2.0, psize=0.3, vmin=0.0, vmax=0.2)
    apex = ROCKET_APEX - base_z
    return rocket_visuals(colour), {
        'trail': part(trail, visuals=rocket_visuals(colour)),
        'burst': part(jets('burst', f'{t}/burst', colour, (0, 0, 0), sphere_dirs(24), rate=420, life=1.5,
                           vmin=4.5, vmax=8.5, psize=0.1), dz=apex),
        'glitter': part(fx('glitter', f'{t}/glitter', 'silver', (0, 0, 0), (0, 0, -1), rate=500, life=0.45,
                           vmin=0.1, vmax=0.5, psize=0.06, kind='ellipsoid', size=(10, 10, 10)), dz=apex),
    }


def rocket_bottle_body():
    V = vis('bottle', cyl(0.045, 0.22), (0, 0, 0.11), mat((60, 140, 80), 0.1, 0.0, alpha=0.6), shadow=False)
    V += vis('bottle_neck', cyl(0.02, 0.06), (0, 0, 0.25), mat((60, 140, 80), 0.1, 0.0, alpha=0.6), shadow=False)
    return V


def cake_parts(cid, colour):
    """Multi-shot box: nine tubes fired one after another, each shooting a coloured star."""
    t = f'/festival/cracker/{cid}'
    V = vis('crate', box(0.36, 0.36, 0.24), (0, 0, 0.12), mat((200, 30, 40), 0.6), shadow=False)
    V += vis('ribbon_x', box(0.37, 0.05, 0.245), (0, 0, 0.12), mat((240, 190, 40), 0.4, 0.3), shadow=False)
    V += vis('ribbon_y', box(0.05, 0.37, 0.245), (0, 0, 0.12), mat((240, 190, 40), 0.4, 0.3), shadow=False)
    P_ = {}
    k = 0
    for i in (-1, 0, 1):
        for j in (-1, 0, 1):
            V += vis(f'tube{k}', cyl(0.035, 0.04), (i * 0.11, j * 0.11, 0.25), mat((30, 30, 35), 0.8), shadow=False)
            c = colour if k % 2 == 0 else ('gold' if colour != 'gold' else 'green')
            shot = fx(f'shot{k}', f'{t}/shot{k}', c, (i * 0.11, j * 0.11, 0.28), (i * 0.12, j * 0.12, 1.0),
                      rate=500, life=0.9, vmin=8.0, vmax=11.0, psize=0.09)
            shot += fx(f'muzzle{k}', f'{t}/shot{k}', 'fire', (i * 0.11, j * 0.11, 0.28), (0, 0, 1), rate=700,
                       life=0.15, vmin=0.5, vmax=2.0, psize=0.05)
            P_[f'shot{k}'] = part(shot)
            k += 1
    P_['smoke'] = part(smoke('smoke', f'{t}/smoke', (0, 0, 0.4), rate=18, life=3.0, psize=0.5, size=(0.3, 0.3, 0.1)))
    return V, P_


def roman_candle_parts(cid, colour):
    t = f'/festival/cracker/{cid}'
    V = vis('stand', box(0.18, 0.18, 0.04), (0, 0, 0.02), mat((90, 60, 35), 0.9), shadow=False)
    stripe = PALETTE[colour][1]
    for k in range(6):
        V += vis(f'tube{k}', cyl(0.03, 0.1), (0, 0, 0.09 + k * 0.1),
                 mat(stripe if k % 2 else (235, 225, 200), 0.6), shadow=False)
    stars = fx('stars', f'{t}/stars', colour, (0, 0, 0.66), (0, 0, 1), rate=3, life=1.7, vmin=7, vmax=9, psize=0.2)
    stars += fx('sparks', f'{t}/stars', 'fire', (0, 0, 0.66), (0, 0, 1), rate=140, life=0.5, vmin=1.0, vmax=2.6,
                psize=0.04)
    return V, {'stars': part(stars),
               'smoke': part(smoke('smoke', f'{t}/smoke', (0, 0, 0.7), rate=8, life=3.0, psize=0.4))}


def sparkler_body(sid, colour='gold', lit=True):
    t = f'/festival/sparkler/{sid}'
    V = vis('stick', cyl(0.004, 0.35), (0, 0, 0.175), mat((90, 90, 95), 0.5, 0.8), shadow=False)
    V += vis('holder', cyl(0.04, 0.05), (0, 0, 0.025), mat((100, 70, 40), 0.9), shadow=False)
    E = jets('sparks', t, colour, (0, 0, 0.36), sphere_dirs(10), rate=60, life=0.35, vmin=0.6, vmax=1.6,
             psize=0.03, emitting=lit)
    return link('link', V + E)


FW_BURST_Z = 28.0


def firework_parts(site):
    """Sky-shot tube at a street end (festival_manager). The burst colour is chosen per shot by sending a
    new color_range_image while the burst part is still parked."""
    t = f'/festival/fw/{site}'
    rocket = fx('rocket', f'{t}/rocket', 'fire', (0, 0, 0.6), (0, 0, 1), rate=90, life=1.4, vmin=19, vmax=21,
                psize=0.14)
    rocket += smoke('smoke', f'{t}/rocket', (0, 0, 0.6), rate=25, life=3.5, psize=0.9, vmin=6, vmax=12)
    V = vis('tube', cyl(0.08, 0.8), (0, 0, 0.4), mat((40, 40, 45), 0.7), shadow=False)
    V += vis('sand', cyl(0.5, 0.1), (0, 0, 0.05), mat((120, 100, 70), 1.0), shadow=False)
    return V, {
        'rocket': part(rocket),
        'burst': part(jets('burst', f'{t}/burst', 'gold', (0, 0, 0), sphere_dirs(26), rate=450, life=2.0, vmin=6,
                           vmax=11, psize=0.22), dz=FW_BURST_Z),
        'sparkle': part(fx('sparkle', f'{t}/sparkle', 'silver', (0, 0, 0), (0, 0, -1), rate=500, life=0.6,
                           vmin=0.2, vmax=1.0, psize=0.1, kind='ellipsoid', size=(14, 14, 14)), dz=FW_BURST_Z),
    }


def firework_body(site):
    V, P_ = firework_parts(site)
    return link('link', V + ''.join(p['xml'] for p in P_.values()))


# kind: (parts builder, display name)
CRACKERS = {
    'flower_pot': (busuvanam_parts, 'Busuvanam'),
    'chakkar': (chakkar_parts, 'Sanguchakaram'),
    'pattasu': (pattasu_parts, 'Pattasu'),
    'saravedi': (saravedi_parts, 'Saravedi'),
    'rocket': (rocket_parts, 'Rocket'),
    'cracker_cake': (cake_parts, 'Sky-shot box'),
    'roman_candle': (roman_candle_parts, 'Roman candle'),
}


def build_models():
    make_diya('diya', True)
    make_diya('diya_visual_only', False)
    write_png(MODELS / 'rangoli/materials/textures/rangoli_mandala.png', 384, 384, rangoli_px)
    write_png(MODELS / 'rangoli/materials/textures/kolam_white.png', 384, 384, kolam_px)
    make_rangoli('rangoli', 'rangoli_mandala.png', 1.6, rangoli_px)
    make_rangoli('kolam', 'kolam_white.png', 1.6, kolam_px)
    make_rangoli('kolam_small', 'kolam_white.png', 1.0, kolam_px)
    write_png(MODELS / 'festival_banner/materials/textures/banner.png', 512, 128, banner_px)
    make_banner()
    make_led_string('led_string_9m', 9.0, 36, 0.55)
    make_led_string('led_string_4m', 4.0, 16, 0.25)
    make_garland('marigold_garland', 4.0, 36, 0.25)
    make_toran('toran')
    make_streetlight()
    for nm, wall, trim in (('tamil_house', (240, 225, 190), (230, 215, 190)),
                           ('tamil_house_teal', (110, 190, 185), (235, 230, 215)),
                           ('tamil_house_pink', (230, 150, 170), (235, 230, 215)),
                           ('tamil_house_yellow', (240, 200, 90), (235, 225, 200))):
        make_house(nm, wall, trim)
    build_fx_textures()
    write_obj_frustum(MODELS / 'flower_pot/meshes/busuvanam.obj', BUSUVANAM_R, 0.026, BUSUVANAM_H)
    write_png(MODELS / 'flower_pot/materials/textures/busuvanam_wrap.png', 256, 256, busuvanam_px)
    write_png(MODELS / 'pattasu/materials/textures/pattasu_wrap.png', 128, 128, pattasu_px)
    # stand-alone demo models (the world uses inline copies with their own topics)
    write_model('firework_site', 'Sky-shot launch tube: emitters on /festival/fw/demo/{rocket,smoke,burst,sparkle}',
                firework_body('demo'))
    write_model('sparkler', 'Sparkler, topic /festival/sparkler/demo', sparkler_body('demo'))
    for kind, desc in (('flower_pot', 'Busuvanam (flower pot): textured paper cone with a fountain'),
                       ('pattasu', 'Pattasu: single paper-wrapped cracker that bangs'),
                       ('chakkar', 'Sanguchakaram (ground spinner); static demo copy'),
                       ('cracker_cake', 'Multi-shot sky-shot box'), ('roman_candle', 'Roman candle'),
                       ('rocket', 'Rocket on a stick'), ('saravedi', 'Saravedi: string of crackers')):
        V, P_ = CRACKERS[kind][0]('demo', 'gold')
        E = ''.join(p['xml'] for p in P_.values())
        write_model(kind, desc + ' -- emitters on /festival/cracker/demo/PART', link('link', V + E))


# ----------------------------------------------------------------------------
# World
# ----------------------------------------------------------------------------
def xf(hx, hy, yaw, lx, ly):
    c, s = math.cos(yaw), math.sin(yaw)
    return hx + lx * c - ly * s, hy + lx * s + ly * c


def rect_local(hx, hy, yaw, x0, y0, x1, y1):
    pts = [xf(hx, hy, yaw, a, b) for a in (x0, x1) for b in (y0, y1)]
    OBST.append((min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts)))


def street_base():
    V, C = [], []
    V.append(vis('ground', box(2 * STREET_X + 6, 46, 0.1), (0, 0, -0.05), mat((58, 48, 38), 0.98), shadow=False))
    C.append(col('ground', box(2 * STREET_X + 6, 46, 0.1), (0, 0, -0.05)))
    V.append(vis('road', box(2 * STREET_X, 2 * ROAD_HALF, 0.02), (0, 0, 0.01), mat((38, 38, 42), 0.95)))
    C.append(col('road', box(2 * STREET_X, 2 * ROAD_HALF, 0.02), (0, 0, 0.01)))
    for sg in (-1, 1):
        yc = sg * (ROAD_HALF + SIDEWALK_OUT) / 2
        for k, (a, b) in enumerate(spans(-STREET_X, STREET_X, CONNECT_GAPS)):
            sw = box(b - a, SIDEWALK_OUT - ROAD_HALF, 0.15)
            V.append(vis(f'sidewalk{sg}_{k}', sw, ((a + b) / 2, yc, 0.075), mat((150, 148, 142), 0.9)))
            C.append(col(f'sidewalk{sg}_{k}', sw, ((a + b) / 2, yc, 0.075)))
            kerb(a, sg * ROAD_HALF, b, sg * ROAD_HALF)
        for gx in (x for g in CONNECT_GAPS for x in g):
            kerb(gx, sg * ROAD_HALF, gx, sg * SIDEWALK_OUT)
        V.append(vis(f'edge_line{sg}', box(2 * STREET_X, 0.1, 0.003), (0, sg * 3.2, 0.0215), mat((235, 235, 225), 0.8), shadow=False))
    for k in range(-7, 8):
        V.append(vis(f'dash{k}', box(2.0, 0.12, 0.003), (k * 4.0, 0, 0.0215), mat((240, 220, 90), 0.8), shadow=False))
    for sg in (-1, 1):                                   # end-of-street barricades
        x = sg * STREET_X
        C.append(col(f'barricade{sg}', box(0.4, 2 * WALL_Y + 0.2, 1.0), (x, 0, 0.5)))
        n = 7
        wd = (2 * WALL_Y) / n
        for k in range(n):
            c = (205, 40, 40) if k % 2 == 0 else (240, 240, 235)
            V.append(vis(f'barr{sg}_{k}', box(0.4, wd, 0.5), (x, -WALL_Y + wd * (k + 0.5), 0.75), mat(c, 0.8)))
            V.append(vis(f'barrl{sg}_{k}', box(0.4, wd, 0.5), (x, -WALL_Y + wd * (k + 0.5), 0.25), mat((60, 60, 60), 0.9)))
        OBST.append((x - 0.2, -WALL_Y - 0.1, x + 0.2, WALL_Y + 0.1))
    return V, C


def compound_walls():
    V, C = [], []
    n = 0
    cream, oxide = (235, 225, 200), (150, 60, 40)
    for sg in (-1, 1):
        gaps = [(hx - 1.6, hx + 1.6) for hx in HOUSE_X] + CONNECT_GAPS
        for a, b in spans(-STREET_X + 0.2, STREET_X - 0.2, gaps):
            ln, cx, y = b - a, (a + b) / 2, sg * WALL_Y
            V.append(vis(f'wall{n}', box(ln, 0.25, 1.3), (cx, y, 0.65), mat(cream, 0.9)))
            V.append(vis(f'band{n}', box(ln, 0.27, 0.3), (cx, y, 0.15), mat(oxide, 0.9)))
            V.append(vis(f'cap{n}', box(ln, 0.35, 0.08), (cx, y, 1.34), mat((200, 190, 170), 0.9)))
            C.append(col(f'wall{n}', box(ln, 0.25, 1.4), (cx, y, 0.7)))
            OBST.append((a, y - 0.15, b, y + 0.15))
            n += 1
        for hx in HOUSE_X:
            y = sg * WALL_Y
            for s2 in (-1, 1):
                px = hx + s2 * 1.75
                V.append(vis(f'gp{n}', box(0.5, 0.5, 2.0), (px, y, 1.0), mat(cream, 0.9)))
                V.append(vis(f'gpc{n}', box(0.62, 0.62, 0.1), (px, y, 2.05), mat((200, 190, 170), 0.9)))
                C.append(col(f'gp{n}', box(0.5, 0.5, 2.1), (px, y, 1.05)))
                OBST.append((px - 0.3, y - 0.3, px + 0.3, y + 0.3))
                lx = hx + s2 * 1.5
                V.append(vis(f'leaf{n}', box(0.06, 1.5, 1.2), (lx, y + sg * 0.85, 0.9), mat((30, 30, 32), 0.5, 0.6)))
                C.append(col(f'leaf{n}', box(0.06, 1.5, 1.2), (lx, y + sg * 0.85, 0.9)))
                OBST.append((lx - 0.05, min(y, y + sg * 1.6), lx + 0.05, max(y, y + sg * 1.6)))
                n += 1
    return V, C


def build_world():
    EMITTER_TOPICS.clear()      # the demo models registered /demo topics; keep only the world's
    inc, lights = [], []
    inline = []
    cnt = {}

    def include(model, base, x, y, z=0.0, yaw=0.0):
        cnt[base] = cnt.get(base, 0) + 1
        inc.append(f'<include><uri>model://{model}</uri><name>{base}_{cnt[base]}</name>{P((x, y, z, 0, 0, yaw))}</include>')

    variants = ['tamil_house', 'tamil_house_teal', 'tamil_house_pink', 'tamil_house_yellow']
    for sg in (1, -1):
        hy, hyaw = sg * HOUSE_Y, -sg * math.pi / 2
        for i, hx in enumerate(HOUSE_X):
            v = variants[(i + (0 if sg > 0 else 2)) % 4]

            def L(lx, ly, lz=0.0, lyaw=0.0):
                wx, wy = xf(hx, hy, hyaw, lx, ly)
                return wx, wy, lz, hyaw + lyaw

            include(v, 'house', hx, hy, 0.0, hyaw)
            rect_local(hx, hy, hyaw, -3.8, -4.3, 5.8, 4.3)
            rect_local(hx, hy, hyaw, 5.8, -1.2, 6.8, 1.2)
            rect_local(hx, hy, hyaw, 6.7, -3.1, 7.3, -2.5)
            include('rangoli' if i % 2 == 0 else 'kolam', 'rangoli', *L(7.6, 0.0, 0.0))
            include('kolam_small', 'kolam', *L(4.5, 0.0, 0.5))
            for k in range(8):                                   # ring of diyas around the rangoli
                a = k * math.pi / 4
                include('diya_visual_only', 'diya_ring', *L(7.6 + math.cos(a), math.sin(a), 0.0, a))
            for y in (-3.3, -2.65, -2.0, 2.0, 2.65, 3.3):
                include('diya_visual_only', 'diya_veranda', *L(5.2, y, 0.5))
            for y in (-0.65, 0.65):                              # only these emit real light
                include('diya', 'diya_lit', *L(5.2, y, 0.5))
            for y in (-2.1, 2.1):
                include('marigold_garland', 'garland', *L(5.65, y, 2.85, math.pi / 2))
                include('led_string_4m', 'led4', *L(5.72, y, 2.6, math.pi / 2))
            include('toran', 'toran', *L(3.62, 0.0, 2.72, math.pi / 2))
    # gate-pillar and wall-top diyas (visual only)
    for sg in (1, -1):
        for hx in HOUSE_X:
            for s2 in (-1, 1):
                include('diya_visual_only', 'diya_gate', hx + s2 * 1.75, sg * WALL_Y, 2.1)
        for x in range(-28, 29, 4):
            if all(abs(x - hx) > 2.4 for hx in HOUSE_X):
                include('diya_visual_only', 'diya_wall', float(x), sg * WALL_Y, 1.38)
    # streetlights + LED strings across the street + banners
    for x in POLE_X:
        for sg in (1, -1):
            include('streetlight', 'streetlight', x, sg * POLE_Y, 0.0, -sg * math.pi / 2)
            OBST.append((x - 0.2, sg * POLE_Y - 0.2, x + 0.2, sg * POLE_Y + 0.2))
        include('led_string_9m', 'led_across', x, 0.0, 5.3, math.pi / 2)
    for x in (-18.0, 18.0):
        include('festival_banner', 'banner', x, 0.0, 0.0, math.pi / 2)
        for sg in (-1, 1):
            OBST.append((x - 0.15, sg * 4.8 - 0.15, x + 0.15, sg * 4.8 + 0.15))
    # ---- Crackers (centre street only). Each sidewalk slot holds a main cracker plus a rocket or a saravedi;
    # cracker_show lights them in this order when a number is published on /festival/burn_count.
    crackers, slots = [], []
    ids = (f'cp{n}' for n in range(1000))
    colours = iter(CRACKER_COLOURS * 20)

    def model(name, x, y, z, yaw, body, static=True, extra=''):
        inline.append(f'<model name="{name}"><static>{str(static).lower()}</static>{P((x, y, z, 0, 0, yaw))}'
                      f'{body}{extra}</model>')

    def parts_models(prefix, x, y, z, yaw, P_):
        out = {}
        for name, pt in P_.items():
            mname = f'{prefix}_{name}'
            body = pt['visuals'] + pt['xml']
            if pt['dynamic']:       # chakkar spinner: free body without gravity, turned by VelocityControl
                inertial = ('<inertial><mass>0.05</mass><inertia><ixx>7e-5</ixx><iyy>7e-5</iyy><izz>1.4e-4</izz>'
                            '<ixy>0</ixy><ixz>0</ixz><iyz>0</iyz></inertia></inertial>')
                model(mname, x, y, PARK_Z, yaw, link('link', '<gravity>false</gravity>' + inertial + body),
                      static=False,
                      extra='<plugin filename="gz-sim-velocity-control-system" name="gz::sim::systems::VelocityControl"/>')
            else:
                model(mname, x, y, PARK_Z, yaw, link('link', body))
            out[name] = dict(model=mname, pose=[round(x, 3), round(y, 3), round(z + pt['dz'], 4), round(yaw, 4)])
        return out

    def cracker(kind, x, y, yaw=0.0):
        cid, colour = next(ids), next(colours)
        z = SIDEWALK_Z
        if kind == 'rocket':
            V, P_ = rocket_parts(cid, colour, z)
            model(f'rocket_bottle_{cid}', x, y, z, yaw, link('link', rocket_bottle_body()))
            z += 0.02                                     # the rocket's stick stands in the bottle
        else:
            V, P_ = CRACKERS[kind][0](cid, colour)
        model(f'{kind}_{cid}', x, y, z + (0.0126 if kind == 'chakkar' else 0.0), yaw, link('link', V))
        parts = parts_models(cid, x, y, z + (0.0126 if kind == 'chakkar' else 0.0), yaw, P_)
        crackers.append(dict(id=cid, type=kind, name=CRACKERS[kind][1], colour=colour,
                             at=[round(x, 3), round(y, 3), z], body=f'{kind}_{cid}',
                             pose=[round(x, 3), round(y, 3), round(z + (0.0126 if kind == 'chakkar' else 0.0), 4),
                                   round(yaw, 4)], parts=parts))
        if kind in ('flower_pot', 'pattasu', 'cracker_cake', 'roman_candle', 'rocket'):
            OBST.append((x - 0.2, y - 0.2, x + 0.2, y + 0.2))
        return cid

    north = ['flower_pot', 'chakkar', 'pattasu', 'flower_pot', 'cracker_cake', 'chakkar', 'pattasu', 'roman_candle']
    south = ['pattasu', 'flower_pot', 'chakkar', 'roman_candle', 'pattasu', 'flower_pot', 'cracker_cake', 'chakkar']
    E_, W_ = 0.0, math.pi
    for sg, kinds, order, yaw in ((1, north, SLOT_X, E_), (-1, south, SLOT_X[::-1], W_)):
        for x in order:
            k = SLOT_X.index(x)
            main = cracker(kinds[k], x, sg * 4.0, 0.3 * k)
            if (k + (sg < 0)) % 2 == 0:
                extra = cracker('rocket', x + 1.0, sg * 4.6)
            else:
                extra = cracker('saravedi', x + 1.5, sg * 4.15, sg * 0.15)
            slots.append(dict(slot=f'{"N" if sg > 0 else "S"}{x:+.0f}', goal=[x, sg * 2.5, round(yaw, 4)],
                              ids=[main, extra]))
    lines = ['# generated by diwali_sim/scripts/generate_assets.py -- every burnable cracker, in burn order.',
             '# cracker_show lights the next N unburnt ones when N is published on /festival/burn_count.',
             f'world: {WORLD}', f'flash_lights: {json.dumps(FLASH_LIGHTS)}', f'park_z: {PARK_Z}', 'crackers:']
    lines += ['  - ' + json.dumps(c) for c in crackers]
    sites = {}
    for site, (x, y) in FW_SITES.items():               # sky-shot tubes at the street ends (festival_manager)
        V, P_ = firework_parts(site)
        model(site, x, y, 0.0, 0.0, link('link', V))
        sites[site] = parts_models(site, x, y, 0.0, 0.0, P_)
        OBST.append((x - 0.5, y - 0.5, x + 0.5, y + 0.5))
    lines.append(f'sites: {json.dumps(sites)}')
    write(CONFIG / 'crackers.yaml', '\n'.join(lines) + '\n')
    tour = ['# generated by diwali_sim/scripts/generate_assets.py -- AMR cracker tour, in visiting order.',
            '# goal: [x, y, yaw] approach pose in the map frame; ids: crackers lit (via cracker_show) on arrival.',
            f'world: {WORLD}', f'home: {list(HOME)}', 'stops:']
    tour += ['  - ' + json.dumps(s) for s in slots]
    write(CONFIG / 'cracker_tour.yaml', '\n'.join(tour) + '\n')
    # the house sparklers (festival_manager: sparkler_on / sparkler_off)
    for sid, (hx, sg, lx, ly) in enumerate([(-18.0, 1, 7.9, 1.3), (6.0, 1, 7.9, -1.3),
                                           (-6.0, -1, 7.9, 1.3), (18.0, -1, 7.9, -1.3)]):
        hy, hyaw = sg * HOUSE_Y, -sg * math.pi / 2
        wx, wy = xf(hx, hy, hyaw, lx, ly)
        inline.append(f'<model name="sparkler_sp{sid}"><static>true</static>{P((wx, wy, 0))}{sparkler_body(f"sp{sid}", lit=False)}</model>')
    # base street + walls
    V, C = street_base()
    V2, C2 = compound_walls()
    inline.append('<model name="street_base"><static>true</static>' + link('link', ''.join(V + C)) + '</model>')
    inline.append('<model name="compound_walls"><static>true</static>' + link('link', ''.join(V2 + C2)) + '</model>')
    # sky: stars + moon (emissive visuals only; the directional light below does the lighting)
    stars = []
    for k in range(240):
        az, el = rnd.uniform(0, 2 * math.pi), rnd.uniform(math.radians(8), math.radians(88))
        R = 320.0
        c = rnd.choice([(255, 255, 255), (200, 220, 255), (255, 235, 200)])
        stars.append(vis(f's{k}', sph(rnd.uniform(0.35, 0.8)),
                         (R * math.cos(el) * math.cos(az), R * math.cos(el) * math.sin(az), R * math.sin(el)),
                         mat((20, 20, 20), 1.0, emis=c), shadow=False))
    maz, mel = 2.2, 0.8
    mpos = (320 * math.cos(mel) * math.cos(maz), 320 * math.cos(mel) * math.sin(maz), 320 * math.sin(mel))
    stars.append(vis('moon', sph(9.0), mpos, mat((30, 30, 30), 1.0, emis=(235, 238, 255)), shadow=False))
    inline.append('<model name="night_sky"><static>true</static>' + link('link', ''.join(stars)) + '</model>')
    n = math.sqrt(sum(c * c for c in mpos))
    mdir = ' '.join(f'{-c / n:.4f}' for c in mpos)
    # controllable world-level lights (names are what /festival/lighting adjusts via /world/<w>/light_config)
    yaml = ['# generated by diwali_sim/scripts/generate_assets.py', 'lights:']
    wl = []
    for k, x in enumerate(POLE_X):
        nm = f'string_light_{k}'
        wl.append(f'<light name="{nm}" type="point">{P((x, 0, 5.0))}<cast_shadows>false</cast_shadows>'
                  '<diffuse>1 0.72 0.35 1</diffuse><specular>1 0.7 0.35 1</specular><intensity>1.0</intensity>'
                  '<attenuation><range>16</range><constant>0.4</constant><linear>0.06</linear>'
                  '<quadratic>0.01</quadratic></attenuation></light>')
        yaml += [f'  - name: {nm}', f'    pose: [{x}, 0.0, 5.0, 0.0, 0.0, 0.0]', '    diffuse: [1.0, 0.72, 0.35]',
                 '    range: 16.0', '    attenuation: [0.4, 0.06, 0.01]', '    base_intensity: 1.0']
    for nm in FLASH_LIGHTS:                              # parked under the street until a cracker needs one
        wl.append(f'<light name="{nm}" type="point">{P((0, 0, -20))}<cast_shadows>false</cast_shadows>'
                  '<diffuse>1 0.7 0.3 1</diffuse><specular>1 0.7 0.3 1</specular><intensity>0</intensity>'
                  '<attenuation><range>8</range><constant>0.3</constant><linear>0.2</linear>'
                  '<quadratic>0.05</quadratic></attenuation></light>')
    write(CONFIG / 'festival_lights.yaml', '\n'.join(yaml) + '\n')

    plugins = ''.join(
        f'<plugin filename="{f}" name="{n_}">{extra}</plugin>' for f, n_, extra in [
            ('gz-sim-physics-system', 'gz::sim::systems::Physics', ''),
            ('gz-sim-user-commands-system', 'gz::sim::systems::UserCommands', ''),
            ('gz-sim-scene-broadcaster-system', 'gz::sim::systems::SceneBroadcaster', ''),
            ('gz-sim-sensors-system', 'gz::sim::systems::Sensors', '<render_engine>ogre2</render_engine>'),
            ('gz-sim-particle-emitter-system', 'gz::sim::systems::ParticleEmitter', '')])
    world = (f'<sdf version="1.9"><world name="{WORLD}">'
             '<physics name="default_physics" type="dart"><max_step_size>0.004</max_step_size>'
             '<real_time_factor>1.0</real_time_factor></physics>' + plugins +
             '<gravity>0 0 -9.8</gravity>'
             '<scene><ambient>0.07 0.08 0.14 1</ambient><background>0.005 0.007 0.02 1</background>'
             '<shadows>true</shadows><grid>false</grid></scene>'
             '<light name="moon" type="directional"><cast_shadows>true</cast_shadows>' + P((0, 0, 50)) +
             f'<diffuse>0.35 0.42 0.7 1</diffuse><specular>0.1 0.12 0.2 1</specular><intensity>0.5</intensity>'
             f'<direction>{mdir}</direction></light>' + ''.join(wl) + ''.join(inline) + ''.join(inc) +
             '</world></sdf>')
    write(WORLDS / 'diwali_street.sdf', pretty(world))
    write(CONFIG / 'emitter_topics.yaml',
          '# generated by diwali_sim/scripts/generate_assets.py\n'
          '# part topic -> number of particle jets; jet k listens on <part topic>/<k>\n' +
          ''.join(f'{t}: {n}\n' for t, n in sorted(EMITTER_TOPICS.items())))
    return len(inc)


# ----------------------------------------------------------------------------
# Map for Nav2 (rasterised from the same geometry as the world)
# ----------------------------------------------------------------------------
def write_map():
    res, ox, oy, wm, hm = 0.05, -32.0, -24.0, 64.0, 48.0
    Wd, Ht = int(wm / res), int(hm / res)
    img = bytearray([254]) * (Wd * Ht)

    def fill(x0, y0, x1, y1, val):
        j0, j1 = max(0, int((x0 - ox) / res)), min(Wd, int(math.ceil((x1 - ox) / res)))
        i0, i1 = max(0, int((oy + hm - y1) / res)), min(Ht, int(math.ceil((oy + hm - y0) / res)))
        for i in range(i0, i1):
            img[i * Wd + j0:i * Wd + j1] = bytes([val]) * max(0, j1 - j0)

    for r in OBST:
        fill(*r, 0)
    MAPS.mkdir(parents=True, exist_ok=True)
    (MAPS / 'diwali_street.pgm').write_bytes(f'P5\n{Wd} {Ht}\n255\n'.encode() + bytes(img))
    write(MAPS / 'diwali_street.yaml',
          'image: diwali_street.pgm\nmode: trinary\nresolution: 0.05\n'
          f'origin: [{ox}, {oy}, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.25\n')


# ----------------------------------------------------------------------------
# Sounds (synthetic, so no third-party audio is needed)
# ----------------------------------------------------------------------------
def save_wav(name, samples, sr=22050):
    SOUNDS.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SOUNDS / name), 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b''.join(struct.pack('<h', int(max(-1, min(1, s)) * 30000)) for s in samples))


def build_sounds():
    sr = 22050
    d = 1.4
    ph, out = 0.0, []
    for i in range(int(sr * d)):                      # rising whistle
        t = i / sr
        ph += 2 * math.pi * (500 + 1300 * t / d) / sr
        out.append(0.35 * math.sin(ph) * (1 - t / d) + rnd.uniform(-0.03, 0.03))
    save_wav('firework_launch.wav', out)
    out = []
    for i in range(int(sr * 2.0)):                    # burst: noise + thump
        t = i / sr
        out.append(0.9 * rnd.uniform(-1, 1) * math.exp(-t * 3.2) + 0.6 * math.sin(2 * math.pi * 55 * t) * math.exp(-t * 5))
    save_wav('firework_burst.wav', out)
    out = [0.0] * int(sr * 1.8)
    for _ in range(70):                               # crackle: sparse clicks, thinning out
        p = int((rnd.random() ** 1.6) * (len(out) - 400))
        amp = rnd.uniform(0.3, 0.9)
        for k in range(rnd.randint(30, 90)):
            out[p + k] += amp * rnd.uniform(-1, 1) * math.exp(-k / 18.0)
    save_wav('firework_crackle.wav', out)
    out = []
    for i in range(int(sr * 3.5)):                    # temple-bell-like partials
        t = i / sr
        out.append(sum(a * math.sin(2 * math.pi * f * t) * math.exp(-t * dcy) for f, a, dcy in
                       ((523, 0.4, 1.2), (1318, 0.25, 1.8), (1580, 0.2, 2.2), (2150, 0.1, 3.0))))
    save_wav('temple_bell.wav', out)
    out = []
    for i in range(int(sr * 1.6)):                    # pattasu: sharp crack + chest thump + rumble
        t = i / sr
        out.append(min(1.0, 1.6 * rnd.uniform(-1, 1) * math.exp(-t * 28) + 0.8 * math.sin(2 * math.pi * 58 * t) *
                       math.exp(-t * 7) + 0.25 * rnd.uniform(-1, 1) * math.exp(-t * 3.5)))
    save_wav('pattasu_bang.wav', out)
    out = [0.0] * int(sr * 3.8)
    p = int(sr * 0.05)
    while p < len(out) - 2000:                        # saravedi: rapid irregular pops
        amp = rnd.uniform(0.45, 1.0)
        for k in range(1400):
            out[p + k] += amp * rnd.uniform(-1, 1) * math.exp(-k / 160.0) + 0.3 * amp * math.sin(k * 0.03) * math.exp(-k / 300.0)
        p += int(sr * rnd.uniform(0.06, 0.13))
    save_wav('saravedi.wav', [max(-1, min(1, v)) for v in out])
    out, lp = [], 0.0
    for i in range(int(sr * 7.0)):                    # busuvanam: rushing hiss with crackle
        t = i / sr
        lp += 0.35 * (rnd.uniform(-1, 1) - lp)
        env = min(1.0, t / 0.3) * min(1.0, (7.0 - t) / 0.8)
        crackle = rnd.uniform(-1, 1) * 0.8 if rnd.random() < 0.002 else 0.0
        out.append(0.45 * env * lp + crackle * env)
    save_wav('busuvanam.wav', out)
    out, ph, lp = [], 0.0, 0.0
    for i in range(int(sr * 6.2)):                    # sanguchakaram: warbling whistle + hiss
        t = i / sr
        ph += 2 * math.pi * (1700 + 380 * math.sin(2 * math.pi * 13 * t)) / sr
        lp += 0.3 * (rnd.uniform(-1, 1) - lp)
        env = min(1.0, t / 0.4) * min(1.0, (6.2 - t) / 0.6)
        out.append(env * (0.22 * math.sin(ph) + 0.35 * lp))
    save_wav('chakkar.wav', out)
    out = []
    for i in range(int(sr * 0.6)):                    # sky-shot tube pop
        t = i / sr
        out.append(0.7 * rnd.uniform(-1, 1) * math.exp(-t * 30) + 0.6 * math.sin(2 * math.pi * 90 * t) * math.exp(-t * 12))
    save_wav('shot_pop.wav', out)


if __name__ == '__main__':
    build_models()
    n = build_world()
    write_map()
    build_sounds()
    print(f'world includes: {n}, obstacle rects: {len(OBST)}')
