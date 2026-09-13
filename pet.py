#!/usr/bin/env python3
"""
Tamagotchi Linux — pixel art edition.

Dependances : PySide6, psutil
    pip install PySide6 psutil
"""

import math, random, sys, time
from dataclasses import dataclass, field
from enum import Enum, auto

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QAction
from PySide6.QtWidgets import QApplication, QWidget, QMenu

# ── Config ───────────────────────────────────────────────────────────────
WIN_W, WIN_H = 280, 200
FPS       = 60
PROBE_MS  = 2000
PX        = 5          # taille d'un pixel logique en pixels écran
SPRITE_W  = 14         # largeur sprite en pixels logiques
SPRITE_H  = 16         # hauteur (corps 14 + 2 lignes pieds)

CPU_HOT    = 70.0
RAM_FULL   = 80.0
DISK_FULL  = 90.0
SLEEP_AFTER = 20.0

# ── Humeurs ──────────────────────────────────────────────────────────────
class Mood(Enum):
    CALM     = auto()
    AGITATED = auto()
    SLUGGISH = auto()
    HUNGRY   = auto()
    SLEEPING = auto()

# (corps, contour/pieds, blanc yeux, pupilles)
PALETTE = {
    Mood.CALM:     ("#7fb890", "#3d6b4f", "#f0f0ea", "#1e1826"),
    Mood.AGITATED: ("#e86a5c", "#9e3828", "#f0f0ea", "#1e1826"),
    Mood.SLUGGISH: ("#8a7ca8", "#4e4470", "#f0f0ea", "#1e1826"),
    Mood.HUNGRY:   ("#e3a857", "#a06828", "#f0f0ea", "#1e1826"),
    Mood.SLEEPING: ("#5a6b82", "#2e3e52", "#d4dce8", "#2a3646"),
}

# ── Forme du corps (14×14, BODY_MASK[row] = (col_debut, col_fin)) ────────
BODY_MASK = [
    (4, 10),  # 0
    (2, 12),  # 1
    (1, 13),  # 2
    (0, 14),  # 3
    (0, 14),  # 4
    (0, 14),  # 5
    (0, 14),  # 6
    (0, 14),  # 7
    (0, 14),  # 8
    (0, 14),  # 9
    (0, 14),  # 10
    (1, 13),  # 11
    (2, 12),  # 12
    (4, 10),  # 13
]

def _in_body(row, col):
    if 0 <= row < len(BODY_MASK):
        c0, c1 = BODY_MASK[row]
        return c0 <= col < c1
    return False

def _is_outline(row, col):
    if _in_body(row, col):
        return False
    return any(_in_body(row+dr, col+dc) for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)))

# pré-calcul des pixels corps et contour
_BODY_PX    = [(r, c) for r in range(14) for c in range(SPRITE_W) if _in_body(r, c)]
_OUTLINE_PX = [(r, c) for r in range(-1, 15) for c in range(-1, SPRITE_W+1) if _is_outline(r, c)]

# ── Pixel art « z » (4×5 logique) ────────────────────────────────────────
_Z_SHAPE = [
    "1110",
    "0011",
    "0110",
    "1100",
    "1111",
]

# ── Physique ─────────────────────────────────────────────────────────────
SPEED = {
    Mood.CALM: 42.0, Mood.AGITATED: 135.0,
    Mood.SLUGGISH: 16.0, Mood.HUNGRY: 55.0, Mood.SLEEPING: 0.0,
}

@dataclass
class SysState:
    cpu: float = 0.0
    ram: float = 0.0
    disk: float = 0.0

def read_system():
    try:
        return SysState(psutil.cpu_percent(None),
                        psutil.virtual_memory().percent,
                        psutil.disk_usage("/").percent)
    except Exception:
        return SysState()

def derive_mood(s: SysState, calm_since: float) -> Mood:
    if s.cpu  >= CPU_HOT:    return Mood.AGITATED
    if s.ram  >= RAM_FULL:   return Mood.SLUGGISH
    if s.disk >= DISK_FULL:  return Mood.HUNGRY
    if calm_since >= SLEEP_AFTER: return Mood.SLEEPING
    return Mood.CALM

@dataclass
class Creature:
    pos:    QPointF = field(default_factory=lambda: QPointF(WIN_W/2, WIN_H/2))
    target: QPointF = field(default_factory=lambda: QPointF(WIN_W/2, WIN_H/2))
    facing: int   = 1      # 1=droite -1=gauche
    phase:  float = 0.0    # phase animation globale
    mood:   Mood  = Mood.CALM
    frame:  int   = 0      # 0/1 frame marche
    _retime: float = 0.0
    _ftime:  float = 0.0

    def _bounds(self):
        m = SPRITE_W * PX // 2 + 8
        return m, WIN_W - m, m, WIN_H - m

    def pick_target(self):
        x0, x1, y0, y1 = self._bounds()
        self.target = QPointF(random.uniform(x0, x1), random.uniform(y0, y1))

    def update(self, dt: float, mood: Mood):
        self.mood   = mood
        self.phase += dt * (6.0 if mood == Mood.AGITATED else 2.2)

        fps_anim = 10 if mood == Mood.AGITATED else 5
        self._ftime += dt
        if self._ftime >= 1.0 / fps_anim:
            self._ftime = 0.0
            self.frame ^= 1

        if mood == Mood.SLEEPING:
            return

        self._retime -= dt
        reached = (abs(self.pos.x() - self.target.x()) < 5 and
                   abs(self.pos.y() - self.target.y()) < 5)
        if self._retime <= 0 or reached:
            self.pick_target()
            self._retime = random.uniform(0.8, 2.8)
            if mood == Mood.AGITATED:
                self._retime *= 0.35

        dx = self.target.x() - self.pos.x()
        dy = self.target.y() - self.pos.y()
        dist = math.hypot(dx, dy)
        if dist > 1:
            step = min(SPEED[mood] * dt, dist)
            self.pos.setX(self.pos.x() + dx / dist * step)
            self.pos.setY(self.pos.y() + dy / dist * step)
            if abs(dx) > 1:
                self.facing = 1 if dx > 0 else -1


# ── Rendu pixel-art ──────────────────────────────────────────────────────

def _c(hex_str: str) -> QColor:
    return QColor(hex_str)

def render_creature(p: QPainter, c: Creature):
    p.setRenderHint(QPainter.Antialiasing, False)

    col_body, col_dark, col_white, col_pupil = [_c(s) for s in PALETTE[c.mood]]
    cx = int(c.pos.x())
    cy = int(c.pos.y())
    x0 = cx - SPRITE_W * PX // 2
    y0 = cy - SPRITE_H * PX // 2

    def draw(row, col, color):
        """Dessine un pixel logique avec flip horizontal selon facing."""
        dc = (SPRITE_W - 1 - col) if c.facing == -1 else col
        p.fillRect(x0 + dc * PX, y0 + row * PX, PX, PX, color)

    def draw_abs(row, col, color):
        """Pixel sans flip (pour les accessoires latéraux)."""
        p.fillRect(x0 + col * PX, y0 + row * PX, PX, PX, color)

    # ── Corps ────────────────────────────────────────────────────────────
    for (row, col) in _BODY_PX:
        draw(row, col, col_body)
    for (row, col) in _OUTLINE_PX:
        draw(row, col, col_dark)

    # ── Yeux ─────────────────────────────────────────────────────────────
    # Définis pour facing=droite ; draw() flip automatiquement
    #   œil gauche : (row=4-5, col=2-3)   œil droit : (row=4-5, col=10-11)
    mood = c.mood

    if mood == Mood.SLEEPING:
        # traits horizontaux = yeux fermés
        for col in (2, 3, 4):
            draw(5, col, col_dark)
        for col in (9, 10, 11):
            draw(5, col, col_dark)
        # ZZZ pixel art
        zzz_col = _c("#b8cce0")
        sizes = [(1, SPRITE_W + 1, 0), (2, SPRITE_W + 3, -2), (3, SPRITE_W + 5, -4)]
        for scale, sc, sr in sizes:
            for zrow, bits in enumerate(_Z_SHAPE):
                for zcol, bit in enumerate(bits):
                    if bit == "1":
                        draw_abs(sr + zrow * scale, sc + zcol * scale, zzz_col)

    elif mood == Mood.SLUGGISH:
        # yeux mi-clos : seulement la rangée basse
        for col in (2, 3, 4):
            draw(5, col, col_white)
            draw(4, col, col_dark)   # paupière
        for col in (9, 10, 11):
            draw(5, col, col_white)
            draw(4, col, col_dark)
        draw(5, 3,  col_pupil)
        draw(5, 10, col_pupil)

    elif mood == Mood.AGITATED:
        # yeux écarquillés 3×3
        for row in (3, 4, 5):
            for col in (2, 3, 4):
                draw(row, col, col_white)
            for col in (9, 10, 11):
                draw(row, col, col_white)
        draw(5, 4,  col_pupil)
        draw(5, 9,  col_pupil)
        # goutte de sueur (tombe vers le bas)
        drip = int(c.phase * 3 % (SPRITE_H - 2))
        sweat = _c("#78bede")
        draw_abs(drip,     SPRITE_W + 1, sweat)
        draw_abs(drip + 1, SPRITE_W + 1, sweat)

    else:
        # yeux normaux 3×2 + pupille
        for row in (4, 5):
            for col in (2, 3, 4):
                draw(row, col, col_white)
            for col in (9, 10, 11):
                draw(row, col, col_white)
        # pupilles vers l'avant (facing=droite → col 4/9 = côté intérieur)
        draw(5, 4,  col_pupil)
        draw(5, 9,  col_pupil)

    # ── Bouche ───────────────────────────────────────────────────────────
    if mood == Mood.CALM:
        # sourire en arc
        for col in (4, 5):
            draw(9, col, col_dark)
        draw(10, 6, col_dark)
        draw(10, 7, col_dark)
        for col in (8, 9):
            draw(9, col, col_dark)

    elif mood == Mood.AGITATED:
        # grimace zig-zag
        for col in range(4, 10):
            draw(9 + (col % 2), col, col_dark)

    elif mood == Mood.SLUGGISH:
        # ligne plate
        for col in range(5, 9):
            draw(9, col, col_dark)

    elif mood == Mood.HUNGRY:
        # bouche ouverte (carré creux + intérieur rouge)
        for col in range(5, 9):
            draw(8,  col, col_dark)
            draw(10, col, col_dark)
        draw(9, 4, col_dark)
        draw(9, 9, col_dark)
        for col in range(5, 9):
            draw(9, col, _c("#3c1010"))

    elif mood == Mood.SLEEPING:
        # pas de bouche — on garde le look endormi
        for col in (5, 6, 7, 8):
            draw(9, col, col_dark)

    # ── Pieds (2 frames d'animation) ─────────────────────────────────────
    if mood != Mood.SLEEPING:
        # frame 0 : pied gauche en avant (row 14), pied droit en arrière (row 15)
        # frame 1 : inversé
        if c.frame == 0:
            for col in (2, 3, 4):   draw(14, col, col_dark)   # gauche avancé
            for col in (9, 10, 11): draw(15, col, col_dark)   # droit reculé
        else:
            for col in (2, 3, 4):   draw(15, col, col_dark)
            for col in (9, 10, 11): draw(14, col, col_dark)
    else:
        # assis — pieds à plat
        for col in range(2, 6):  draw(14, col, col_dark)
        for col in range(8, 12): draw(14, col, col_dark)

    # ── Ombre portée ─────────────────────────────────────────────────────
    shadow = QColor(0, 0, 0, 40)
    sy = y0 + (SPRITE_H + 1) * PX
    for col in range(2, SPRITE_W - 2):
        p.fillRect(x0 + col * PX, sy, PX, PX // 2, shadow)


# ── Widget ───────────────────────────────────────────────────────────────

class PetWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("tamagotchi")
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
            | Qt.X11BypassWindowManagerHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.creature    = Creature()
        self.state       = SysState()
        self._calm_since = 0.0
        self._last       = time.monotonic()

        psutil.cpu_percent(interval=None)  # amorce

        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)
        self.anim.start(int(1000 / FPS))

        self.probe = QTimer(self)
        self.probe.timeout.connect(self._probe)
        self.probe.start(PROBE_MS)
        self._probe()

    def _tick(self):
        now = time.monotonic()
        dt  = now - self._last
        self._last = now
        self.creature.update(dt, self.creature.mood)
        self.update()

    def _probe(self):
        self.state = read_system()
        prev  = self.creature.mood
        mood  = derive_mood(self.state, self._calm_since)
        if mood == Mood.CALM:
            self._calm_since += PROBE_MS / 1000.0
        else:
            self._calm_since = 0.0
        self.creature.mood = mood
        if prev != mood:
            self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        render_creature(p, self.creature)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            wh = self.windowHandle()
            if wh:
                wh.startSystemMove()
        elif ev.button() == Qt.RightButton:
            self._menu(ev.globalPosition().toPoint())

    def _menu(self, gpos):
        m    = QMenu(self)
        s    = self.state
        info = m.addAction(f"CPU {s.cpu:.0f}%  RAM {s.ram:.0f}%  Disk {s.disk:.0f}%")
        info.setEnabled(False)
        hmood = m.addAction(f"Humeur : {self.creature.mood.name.lower()}")
        hmood.setEnabled(False)
        m.addSeparator()
        q = QAction("Quitter", self)
        q.triggered.connect(QApplication.quit)
        m.addAction(q)
        m.exec(gpos)


def main():
    app = QApplication(sys.argv)
    w   = PetWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
