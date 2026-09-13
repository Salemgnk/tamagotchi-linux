#!/usr/bin/env python3
"""
Tamagotchi Linux - variante systeme (Route A).

Un petit compagnon flottant, dans sa propre fenetre sans bordure,
translucide et toujours au-dessus. Il se deplace dans son territoire
et son humeur reflete l'etat de la machine (CPU / RAM / disque / uptime).

Dependances : PySide6, psutil
    pip install PySide6 psutil

Lancement :
    python pet.py

Interaction :
    - clic gauche maintenu : deplacer le territoire (via le compositeur)
    - clic droit : menu (etat courant, quitter)
"""

import math
import random
import sys
import time
from dataclasses import dataclass, field
from enum import Enum, auto

import psutil
from PySide6.QtCore import Qt, QTimer, QPointF
from PySide6.QtGui import QColor, QPainter, QBrush, QPen, QAction
from PySide6.QtWidgets import QApplication, QWidget, QMenu


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

WIN_W, WIN_H = 260, 200          # taille du territoire
FPS = 60                          # tick d'animation
PROBE_MS = 2000                   # periode de la sonde systeme
BODY_R = 34                       # rayon du corps

# Seuils de bascule d'humeur (en %)
CPU_HOT = 70.0
RAM_FULL = 80.0
DISK_FULL = 90.0

# Temps de calme (s) avant que la creature s'endorme
SLEEP_AFTER = 20.0

# Palette par humeur : (couleur du corps, couleur d'accent)
PALETTE = {
    "CALM":     (QColor(127, 184, 143), QColor(90, 140, 105)),
    "AGITATED": (QColor(232, 106, 92),  QColor(180, 70, 60)),
    "SLUGGISH": (QColor(138, 124, 168), QColor(100, 88, 128)),
    "HUNGRY":   (QColor(227, 168, 87),  QColor(180, 130, 60)),
    "SLEEPING": (QColor(90, 107, 130),  QColor(60, 74, 96)),
}


class Mood(Enum):
    CALM = auto()
    AGITATED = auto()
    SLUGGISH = auto()
    HUNGRY = auto()
    SLEEPING = auto()


# --------------------------------------------------------------------------
# Lecture systeme -> humeur
# --------------------------------------------------------------------------

@dataclass
class SysState:
    cpu: float = 0.0
    ram: float = 0.0
    disk: float = 0.0
    uptime_h: float = 0.0


def read_system() -> SysState:
    """Sonde non bloquante. cpu_percent() sans intervalle mesure depuis
    le dernier appel, ce qui colle exactement a notre horloge de sonde."""
    try:
        cpu = psutil.cpu_percent(interval=None)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("/").percent
        uptime_h = (time.time() - psutil.boot_time()) / 3600.0
        return SysState(cpu, ram, disk, uptime_h)
    except Exception:
        # jamais planter le pet a cause d'une lecture systeme
        return SysState()


def derive_mood(s: SysState, calm_since: float) -> Mood:
    """Priorite : agite > amorphe > affame > (endormi si calme depuis un moment) > calme."""
    if s.cpu >= CPU_HOT:
        return Mood.AGITATED
    if s.ram >= RAM_FULL:
        return Mood.SLUGGISH
    if s.disk >= DISK_FULL:
        return Mood.HUNGRY
    if calm_since >= SLEEP_AFTER:
        return Mood.SLEEPING
    return Mood.CALM


# vitesse de deplacement (px/s) par humeur
SPEED = {
    Mood.CALM: 45.0,
    Mood.AGITATED: 140.0,
    Mood.SLUGGISH: 18.0,
    Mood.HUNGRY: 60.0,
    Mood.SLEEPING: 0.0,
}


# --------------------------------------------------------------------------
# La creature
# --------------------------------------------------------------------------

@dataclass
class Creature:
    pos: QPointF = field(default_factory=lambda: QPointF(WIN_W / 2, WIN_H / 2))
    target: QPointF = field(default_factory=lambda: QPointF(WIN_W / 2, WIN_H / 2))
    facing: int = 1                 # 1 = droite, -1 = gauche
    phase: float = 0.0              # phase d'animation (bob / respiration)
    mood: Mood = Mood.CALM
    _retarget_in: float = 0.0

    def _bounds(self):
        m = BODY_R + 6
        return m, WIN_W - m, m, WIN_H - m

    def pick_target(self):
        x0, x1, y0, y1 = self._bounds()
        self.target = QPointF(random.uniform(x0, x1), random.uniform(y0, y1))

    def update(self, dt: float, mood: Mood):
        self.mood = mood
        self.phase += dt * (6.0 if mood == Mood.AGITATED else 2.2)

        if mood == Mood.SLEEPING:
            return

        # choix d'une nouvelle cible periodiquement (plus souvent si agite)
        self._retarget_in -= dt
        reached = (abs(self.pos.x() - self.target.x()) < 4 and
                   abs(self.pos.y() - self.target.y()) < 4)
        if self._retarget_in <= 0 or reached:
            self.pick_target()
            self._retarget_in = random.uniform(0.6, 2.4)
            if mood == Mood.AGITATED:
                self._retarget_in *= 0.4

        # deplacement vers la cible
        dx = self.target.x() - self.pos.x()
        dy = self.target.y() - self.pos.y()
        dist = math.hypot(dx, dy)
        if dist > 1e-3:
            step = SPEED[mood] * dt
            if step > dist:
                step = dist
            self.pos.setX(self.pos.x() + dx / dist * step)
            self.pos.setY(self.pos.y() + dy / dist * step)
            if abs(dx) > 2:
                self.facing = 1 if dx > 0 else -1


# --------------------------------------------------------------------------
# Le widget / la fenetre
# --------------------------------------------------------------------------

class PetWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("tamagotchi")
        self.setFixedSize(WIN_W, WIN_H)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool                      # pas d'entree dans la barre des taches
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.creature = Creature()
        self.state = SysState()
        self._calm_since = 0.0
        self._last = time.monotonic()

        # amorce cpu_percent (le premier appel renvoie 0.0)
        psutil.cpu_percent(interval=None)

        self.anim = QTimer(self)
        self.anim.timeout.connect(self._tick)
        self.anim.start(int(1000 / FPS))

        self.probe = QTimer(self)
        self.probe.timeout.connect(self._probe)
        self.probe.start(PROBE_MS)
        self._probe()

    # ---- boucles -------------------------------------------------------

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last
        self._last = now
        self.creature.update(dt, self.creature.mood)
        self.update()

    def _probe(self):
        self.state = read_system()
        prev = self.creature.mood
        mood = derive_mood(self.state, self._calm_since)
        if mood == Mood.CALM:
            self._calm_since += PROBE_MS / 1000.0
        else:
            self._calm_since = 0.0
        self.creature.mood = mood
        if prev != mood:
            self.update()

    # ---- rendu ---------------------------------------------------------

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        c = self.creature
        body_col, accent = PALETTE[c.mood.name]
        cx, cy = c.pos.x(), c.pos.y()

        # respiration / rebond
        bob = math.sin(c.phase) * (4 if c.mood != Mood.SLEEPING else 1)
        squash = 1.0 + 0.06 * math.sin(c.phase * 2)
        cy_draw = cy - abs(bob) * (0.6 if c.mood != Mood.SLEEPING else 0.0)

        # ombre portee
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, 45)))
        p.drawEllipse(QPointF(cx, cy + BODY_R * 0.9),
                      BODY_R * 0.8, BODY_R * 0.30)

        # corps
        rw = BODY_R * (2 - squash)
        rh = BODY_R * squash
        p.setBrush(QBrush(body_col))
        p.setPen(QPen(accent, 3))
        p.drawEllipse(QPointF(cx, cy_draw), rw, rh)

        # yeux
        eye_dx = 11 * c.facing
        eye_y = cy_draw - 4
        if c.mood == Mood.SLEEPING:
            p.setPen(QPen(QColor(20, 24, 34), 2.5))
            for sx in (-1, 1):
                ex = cx + sx * 11
                p.drawArc(int(ex - 6), int(eye_y - 4), 12, 10, 0, -180 * 16)
            self._draw_zzz(p, cx + 18, cy_draw - BODY_R)
        else:
            wide = c.mood == Mood.AGITATED
            half = c.mood == Mood.SLUGGISH
            for sx in (-1, 1):
                ex = cx + sx * 11 + (eye_dx * 0.15)
                er = 7 if wide else 6
                p.setBrush(QBrush(QColor(245, 245, 245)))
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(ex, eye_y), er, er if not half else er * 0.6)
                # pupille orientee vers le sens de marche
                p.setBrush(QBrush(QColor(20, 24, 34)))
                p.drawEllipse(QPointF(ex + 2 * c.facing, eye_y), 3, 3)

        # bouche selon l'humeur
        p.setPen(QPen(QColor(30, 30, 40), 2.4))
        mx, my = cx, cy_draw + 12
        if c.mood == Mood.HUNGRY:
            p.setBrush(QBrush(QColor(60, 30, 30)))
            p.drawEllipse(QPointF(mx, my), 5, 6)
        elif c.mood == Mood.AGITATED:
            p.drawLine(int(mx - 6), int(my + 2), int(mx + 6), int(my - 2))
        elif c.mood == Mood.SLUGGISH:
            p.drawLine(int(mx - 5), int(my), int(mx + 5), int(my))
        elif c.mood != Mood.SLEEPING:
            p.drawArc(int(mx - 7), int(my - 6), 14, 12, 0, -180 * 16)

        # gouttes de sueur si agite
        if c.mood == Mood.AGITATED:
            p.setBrush(QBrush(QColor(120, 190, 230, 220)))
            p.setPen(Qt.NoPen)
            drip = (c.phase * 20) % 24
            p.drawEllipse(QPointF(cx + BODY_R * 0.7, cy_draw - 10 + drip), 3, 4)

    def _draw_zzz(self, p, x, y):
        p.setPen(QPen(QColor(200, 210, 230), 2))
        for i, s in enumerate((6, 8, 11)):
            zx = x + i * 7
            zy = y - i * 9
            p.drawText(int(zx), int(zy), "z")

    # ---- interaction ---------------------------------------------------

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            # deplacement de la fenetre delegue au compositeur (fiable sous Wayland)
            wh = self.windowHandle()
            if wh is not None:
                wh.startSystemMove()
        elif ev.button() == Qt.RightButton:
            self._menu(ev.globalPosition().toPoint())

    def _menu(self, gpos):
        m = QMenu(self)
        s = self.state
        info = m.addAction(
            f"CPU {s.cpu:.0f}%  RAM {s.ram:.0f}%  Disk {s.disk:.0f}%"
        )
        info.setEnabled(False)
        mood = m.addAction(f"Humeur : {self.creature.mood.name.lower()}")
        mood.setEnabled(False)
        m.addSeparator()
        quit_a = QAction("Quitter", self)
        quit_a.triggered.connect(QApplication.quit)
        m.addAction(quit_a)
        m.exec(gpos)


def main():
    app = QApplication(sys.argv)
    w = PetWidget()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
