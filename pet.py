#!/usr/bin/env python3
"""
Tamagotchi Linux — pixel art, plein écran.

Fenetre transparente plein-ecran (click-through partout sauf le pet).
Le pet se balade sur tout le bureau. Clic gauche = glisser, clic droit = menu.

Dependances : PySide6, psutil
    pip install PySide6 psutil
"""

import math, random, sys, time
from dataclasses import dataclass, field
from enum import Enum, auto

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF, QRect
from PySide6.QtGui import QColor, QPainter, QAction, QRegion
from PySide6.QtWidgets import QApplication, QWidget, QMenu

# ── Dimensions (remplies dans main() depuis la résolution réelle) ─────────
WIN_W: int = 1920
WIN_H: int = 1080

FPS      = 60
PROBE_MS = 2000
PX       = 5       # pixels écran par pixel logique
SPRITE_W = 14
SPRITE_H = 16

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

PALETTE = {
    Mood.CALM:     ("#7fb890", "#3d6b4f", "#f0f0ea", "#1e1826"),
    Mood.AGITATED: ("#e86a5c", "#9e3828", "#f0f0ea", "#1e1826"),
    Mood.SLUGGISH: ("#8a7ca8", "#4e4470", "#f0f0ea", "#1e1826"),
    Mood.HUNGRY:   ("#e3a857", "#a06828", "#f0f0ea", "#1e1826"),
    Mood.SLEEPING: ("#5a6b82", "#2e3e52", "#d4dce8", "#2a3646"),
}

# ── Sprite ───────────────────────────────────────────────────────────────
BODY_MASK = [
    (4, 10), (2, 12), (1, 13), (0, 14),
    (0, 14), (0, 14), (0, 14), (0, 14),
    (0, 14), (0, 14), (0, 14), (1, 13),
    (2, 12), (4, 10),
]

def _in_body(row, col):
    if 0 <= row < len(BODY_MASK):
        c0, c1 = BODY_MASK[row]
        return c0 <= col < c1
    return False

def _is_outline(row, col):
    if _in_body(row, col): return False
    return any(_in_body(row+dr, col+dc) for dr, dc in ((-1,0),(1,0),(0,-1),(0,1)))

_BODY_PX    = [(r, c) for r in range(14)      for c in range(SPRITE_W) if _in_body(r, c)]
_OUTLINE_PX = [(r, c) for r in range(-1, 15)  for c in range(-1, SPRITE_W+1) if _is_outline(r, c)]

_Z_SHAPE = ["1110","0011","0110","1100","1111"]

# ── Physique ─────────────────────────────────────────────────────────────
SPEED = {
    Mood.CALM: 80.0, Mood.AGITATED: 220.0,
    Mood.SLUGGISH: 30.0, Mood.HUNGRY: 100.0, Mood.SLEEPING: 0.0,
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
    if s.cpu  >= CPU_HOT:     return Mood.AGITATED
    if s.ram  >= RAM_FULL:    return Mood.SLUGGISH
    if s.disk >= DISK_FULL:   return Mood.HUNGRY
    if calm_since >= SLEEP_AFTER: return Mood.SLEEPING
    return Mood.CALM

@dataclass
class Creature:
    pos:    QPointF = field(default_factory=lambda: QPointF(WIN_W/2, WIN_H/2))
    target: QPointF = field(default_factory=lambda: QPointF(WIN_W/2, WIN_H/2))
    facing: int   = 1
    phase:  float = 0.0
    mood:   Mood  = Mood.CALM
    frame:  int   = 0
    _retime: float = 0.0
    _ftime:  float = 0.0

    def _bounds(self):
        m = SPRITE_W * PX // 2 + 12
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
        reached = (abs(self.pos.x() - self.target.x()) < 6 and
                   abs(self.pos.y() - self.target.y()) < 6)
        if self._retime <= 0 or reached:
            self.pick_target()
            self._retime = random.uniform(0.8, 3.0)
            if mood == Mood.AGITATED: self._retime *= 0.3

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

def _c(h): return QColor(h)

def render_creature(p: QPainter, c: Creature):
    p.setRenderHint(QPainter.Antialiasing, False)

    col_body, col_dark, col_white, col_pupil = [_c(s) for s in PALETTE[c.mood]]
    x0 = int(c.pos.x()) - SPRITE_W * PX // 2
    y0 = int(c.pos.y()) - SPRITE_H * PX // 2

    def draw(row, col, color):
        dc = (SPRITE_W - 1 - col) if c.facing == -1 else col
        p.fillRect(x0 + dc * PX, y0 + row * PX, PX, PX, color)

    def draw_abs(row, col, color):
        p.fillRect(x0 + col * PX, y0 + row * PX, PX, PX, color)

    # Corps + contour
    for (row, col) in _BODY_PX:    draw(row, col, col_body)
    for (row, col) in _OUTLINE_PX: draw(row, col, col_dark)

    mood = c.mood

    # Yeux
    if mood == Mood.SLEEPING:
        for col in (2, 3, 4):  draw(5, col, col_dark)
        for col in (9,10,11):  draw(5, col, col_dark)
        zzz = _c("#b8cce0")
        for i, (sc, sr) in enumerate([(SPRITE_W+1, 0),(SPRITE_W+3,-2),(SPRITE_W+5,-4)]):
            sz = 1 + (i % 2)
            for zr, bits in enumerate(_Z_SHAPE):
                for zc, b in enumerate(bits):
                    if b == "1": draw_abs(sr + zr*sz, sc + zc*sz, zzz)

    elif mood == Mood.SLUGGISH:
        for col in (2,3,4):   draw(5, col, col_white); draw(4, col, col_dark)
        for col in (9,10,11): draw(5, col, col_white); draw(4, col, col_dark)
        draw(5, 3, col_pupil); draw(5, 10, col_pupil)

    elif mood == Mood.AGITATED:
        for row in (3,4,5):
            for col in (2,3,4):   draw(row, col, col_white)
            for col in (9,10,11): draw(row, col, col_white)
        draw(5, 4, col_pupil); draw(5, 9, col_pupil)
        drip = int(c.phase * 3 % (SPRITE_H - 2))
        sweat = _c("#78bede")
        draw_abs(drip,   SPRITE_W+1, sweat)
        draw_abs(drip+1, SPRITE_W+1, sweat)

    else:
        for row in (4,5):
            for col in (2,3,4):   draw(row, col, col_white)
            for col in (9,10,11): draw(row, col, col_white)
        draw(5, 4, col_pupil); draw(5, 9, col_pupil)

    # Bouche
    if mood == Mood.CALM:
        for col in (4,5,8,9): draw(9, col, col_dark)
        for col in (6,7):     draw(10, col, col_dark)
    elif mood == Mood.AGITATED:
        for col in range(4,10): draw(9+(col%2), col, col_dark)
    elif mood == Mood.SLUGGISH:
        for col in range(5,9): draw(9, col, col_dark)
    elif mood == Mood.HUNGRY:
        for col in range(5,9): draw(8, col, col_dark); draw(10, col, col_dark)
        draw(9,4,col_dark); draw(9,9,col_dark)
        for col in range(5,9): draw(9, col, _c("#3c1010"))
    elif mood == Mood.SLEEPING:
        for col in range(5,9): draw(9, col, col_dark)

    # Pieds
    if mood != Mood.SLEEPING:
        if c.frame == 0:
            for col in (2,3,4):   draw(14, col, col_dark)
            for col in (9,10,11): draw(15, col, col_dark)
        else:
            for col in (2,3,4):   draw(15, col, col_dark)
            for col in (9,10,11): draw(14, col, col_dark)
    else:
        for col in range(2,6):  draw(14, col, col_dark)
        for col in range(8,12): draw(14, col, col_dark)

    # Ombre
    shadow = QColor(0,0,0,40)
    sy = y0 + (SPRITE_H+1)*PX
    for col in range(2, SPRITE_W-2):
        p.fillRect(x0+col*PX, sy, PX, PX//2, shadow)


# ── Widget ───────────────────────────────────────────────────────────────

class PetWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("tamagotchi")

        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)

        self.creature    = Creature()
        self.state       = SysState()
        self._calm_since = 0.0
        self._last       = time.monotonic()
        self._dragging   = False
        self._drag_off   = QPointF(0, 0)

        psutil.cpu_percent(interval=None)

        # Animation
        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)
        self.anim.start(int(1000 / FPS))

        # Sonde système
        self.probe = QTimer(self)
        self.probe.timeout.connect(self._probe)
        self.probe.start(PROBE_MS)
        self._probe()

        # Garde la fenêtre au premier plan (fallback pour les compositeurs
        # qui ignorent WindowStaysOnTopHint, notamment sur Wayland)
        self.top_timer = QTimer(self)
        self.top_timer.timeout.connect(self._keep_top)
        self.top_timer.start(800)

    # ── Boucles ──────────────────────────────────────────────────────────

    def _tick(self):
        now = time.monotonic()
        dt  = now - self._last
        self._last = now
        if not self._dragging:
            self.creature.update(dt, self.creature.mood)
        self._update_mask()
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

    def _keep_top(self):
        self.raise_()

    # ── Masque click-through ─────────────────────────────────────────────
    # Seule la zone du sprite capte les événements souris ;
    # le reste de la fenêtre plein-écran est transparent aux clics.

    def _update_mask(self):
        pad = PX * 3
        r = QRect(
            int(self.creature.pos.x()) - SPRITE_W * PX // 2 - pad,
            int(self.creature.pos.y()) - SPRITE_H * PX // 2 - pad,
            SPRITE_W * PX + pad * 2,
            SPRITE_H * PX + pad * 2,
        )
        self.setMask(QRegion(r))

    # ── Rendu ────────────────────────────────────────────────────────────

    def paintEvent(self, _):
        p = QPainter(self)
        render_creature(p, self.creature)

    # ── Interaction ──────────────────────────────────────────────────────

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_off = ev.position() - self.creature.pos
        elif ev.button() == Qt.RightButton:
            self._menu(ev.globalPosition().toPoint())

    def mouseMoveEvent(self, ev):
        if self._dragging:
            new_pos = ev.position() - self._drag_off
            m = SPRITE_W * PX // 2 + 4
            self.creature.pos = QPointF(
                max(m, min(WIN_W - m, new_pos.x())),
                max(m, min(WIN_H - m, new_pos.y())),
            )
            self.creature.target = self.creature.pos
            self._update_mask()
            self.update()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._dragging = False

    def _menu(self, gpos):
        m    = QMenu(self)
        s    = self.state
        info = m.addAction(f"CPU {s.cpu:.0f}%  RAM {s.ram:.0f}%  Disk {s.disk:.0f}%")
        info.setEnabled(False)
        hm = m.addAction(f"Humeur : {self.creature.mood.name.lower()}")
        hm.setEnabled(False)
        m.addSeparator()
        q = QAction("Quitter", self)
        q.triggered.connect(QApplication.quit)
        m.addAction(q)
        m.exec(gpos)


def main():
    global WIN_W, WIN_H
    app    = QApplication(sys.argv)
    screen = app.primaryScreen().geometry()
    WIN_W  = screen.width()
    WIN_H  = screen.height()

    w = PetWidget()
    w.show()
    w.raise_()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
