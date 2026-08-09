import math
import random

import cv2
import numpy as np

from renderer.effects import draw_glow_circle


def draw_projectile(frame, proj, now):
    c = tuple(np.int32(proj.pos))
    color = proj.color
    speed = max(np.linalg.norm(proj.vel), 1.0)
    direction = proj.vel / speed
    normal = np.array([-direction[1], direction[0]], dtype=np.float32)
    if proj.spell == "incendio":
        tail = proj.pos - direction * (proj.radius * 2.8)
        flame = np.array(
            [
                proj.pos + direction * proj.radius * 0.9,
                proj.pos - direction * proj.radius * 0.5 + normal * proj.radius * 0.75,
                tail - normal * proj.radius * 0.45,
                proj.pos - direction * proj.radius * 0.4 - normal * proj.radius * 0.72,
            ],
            dtype=np.int32,
        )
        draw_glow_circle(frame, proj.pos, proj.radius * 2.4, color, 0.22, 5)
        cv2.fillConvexPoly(frame, flame, (45, 95, 235), cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.62), (95, 210, 255), -1, cv2.LINE_AA)
        for _ in range(5):
            ember = tail + np.array([random.uniform(-18, 18), random.uniform(-18, 18)])
            cv2.circle(frame, tuple(np.int32(ember)), random.randint(1, 3), (70, 180, 255), -1, cv2.LINE_AA)
    elif proj.spell == "stupefy":
        pts = []
        for i in range(5):
            t = i / 4
            base = proj.pos - direction * (84 * (1 - t))
            offset = normal * ((-1) ** i) * random.uniform(8, 18)
            pts.append(base + offset)
        pts.append(proj.pos)
        cv2.polylines(frame, [np.array(pts, dtype=np.int32)], False, color, 7, cv2.LINE_AA)
        cv2.polylines(frame, [np.array(pts, dtype=np.int32)], False, (215, 215, 255), 2, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.66), (255, 255, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 1.1), (95, 95, 255), 2, cv2.LINE_AA)
    elif proj.spell == "glacius":
        draw_glow_circle(frame, proj.pos, proj.radius * 2.1, color, 0.16, 5)
        shard = np.array(
            [
                proj.pos + direction * proj.radius * 1.25,
                proj.pos + normal * proj.radius * 0.48,
                proj.pos - direction * proj.radius * 1.05,
                proj.pos - normal * proj.radius * 0.48,
            ],
            dtype=np.int32,
        )
        cv2.fillConvexPoly(frame, shard, (255, 232, 160), cv2.LINE_AA)
        cv2.polylines(frame, [shard], True, (255, 255, 255), 2, cv2.LINE_AA)
        for k in range(6):
            ang = now * 3.5 + k * math.tau / 6
            p1 = proj.pos + np.array([math.cos(ang), math.sin(ang)]) * (proj.radius * 1.0)
            p2 = proj.pos + np.array([math.cos(ang), math.sin(ang)]) * (proj.radius * 1.55)
            cv2.line(frame, tuple(np.int32(p1)), tuple(np.int32(p2)), color, 1, cv2.LINE_AA)
    elif proj.spell == "overload":
        draw_glow_circle(frame, proj.pos, proj.radius * 2.8, color, 0.24, 6)
        for k in range(6):
            ang = now * 7.0 + k * math.tau / 6
            p1 = proj.pos + np.array([math.cos(ang), math.sin(ang)]) * (proj.radius * 0.45)
            p2 = proj.pos + np.array([math.cos(ang + 0.8), math.sin(ang + 0.8)]) * (proj.radius * 1.45)
            cv2.line(frame, tuple(np.int32(p1)), tuple(np.int32(p2)), color, 2, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 0.72), (250, 235, 255), -1, cv2.LINE_AA)
        cv2.circle(frame, c, int(proj.radius * 1.15), color, 2, cv2.LINE_AA)


def draw_particles(frame, particles):
    overlay = frame.copy()
    for particle in particles:
        t = max(0.0, min(1.0, particle.life / particle.max_life))
        radius = max(1, int(particle.radius * t))
        color = tuple(int(c * t + 20 * (1 - t)) for c in particle.color)
        cv2.circle(overlay, tuple(np.int32(particle.pos)), radius, color, -1, cv2.LINE_AA)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
