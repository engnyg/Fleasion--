"""Windows 11 liquid-glass window effects.

Top-level dialogs get a translucent client area backed by the DWM Acrylic
system backdrop, while widgets are painted with frosted, softly lit,
rounded translucent surfaces.  Everything here is a no-op outside Windows 11
22H2+ (build 22621), so other platforms keep their regular Qt appearance.
"""

from __future__ import annotations

import ctypes
import functools
import logging
import sys
from ctypes import wintypes
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication, QDialog, QMainWindow, QMessageBox, QWidget

if TYPE_CHECKING:
    from collections.abc import Callable

log = logging.getLogger(__name__)

_MIN_BUILD = 22621
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWA_SYSTEMBACKDROP_TYPE = 38
_DWMWCP_ROUND = 2
_DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
_GLASS_PROPERTY = '_fleasion_glass_window'


@dataclass
class _State:
    enabled: bool = False
    dark: bool = True
    event_filter: _GlassWindowFilter | None = None
    patched: bool = False
    stylesheet: str | None = None


_state = _State()


class _Margins(ctypes.Structure):
    _fields_ = (
        ('cxLeftWidth', ctypes.c_int),
        ('cxRightWidth', ctypes.c_int),
        ('cyTopHeight', ctypes.c_int),
        ('cyBottomHeight', ctypes.c_int),
    )


def is_supported() -> bool:
    """Return whether the DWM system backdrop is available on this machine."""
    if sys.platform != 'win32':
        return False
    return sys.getwindowsversion().build >= _MIN_BUILD


def set_enabled(enabled: bool) -> None:
    """Choose whether glass is used for this session."""
    _state.enabled = enabled


def is_active() -> bool:
    """Return whether glass is both requested and supported."""
    return _state.enabled and is_supported()


def _apply_backdrop(hwnd: int, *, dark: bool) -> bool:
    if sys.platform != 'win32':
        return False

    dwmapi = ctypes.windll.dwmapi
    dwmapi.DwmSetWindowAttribute.argtypes = (
        wintypes.HWND,
        wintypes.DWORD,
        wintypes.LPCVOID,
        wintypes.DWORD,
    )
    dwmapi.DwmExtendFrameIntoClientArea.argtypes = (wintypes.HWND, ctypes.POINTER(_Margins))

    def set_attribute(attribute: int, value: int) -> bool:
        data = ctypes.c_int(value)
        return dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(data), 4) == 0

    margins = _Margins(-1, -1, -1, -1)
    extended = dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins)) == 0
    set_attribute(_DWMWA_USE_IMMERSIVE_DARK_MODE, int(dark))
    set_attribute(_DWMWA_WINDOW_CORNER_PREFERENCE, _DWMWCP_ROUND)
    return extended and set_attribute(_DWMWA_SYSTEMBACKDROP_TYPE, _DWMSBT_TRANSIENTWINDOW)


class _GlassWindowFilter(QObject):
    """Apply the DWM backdrop to glass windows each time they are shown."""

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if a0 is None or a1 is None or a1.type() != QEvent.Type.Show:
            return False
        if isinstance(a0, QWidget) and a0.isWindow() and a0.property(_GLASS_PROPERTY):
            if not _apply_backdrop(int(a0.winId()), dark=_state.dark):
                log.warning('Could not apply the Windows backdrop to %s', type(a0).__name__)
        return False


def _prepare(window: QWidget) -> None:
    """Make a not-yet-shown top-level window translucent glass."""
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    window.setProperty(_GLASS_PROPERTY, True)
    _restyle(window)


def _restyle(window: QWidget) -> None:
    app = QApplication.instance()
    if isinstance(app, QApplication):
        window.setPalette(glass_palette(app.palette(), dark=_state.dark))


def _patch_window_class(cls: type[QWidget]) -> None:
    """Prepare every new window of ``cls`` (and its Python subclasses) as glass.

    Qt creates a dialog's native window before any event reaches an application
    filter, and the translucent attribute only works if set before that, so it
    is applied straight after construction instead.
    """
    original: Callable[..., None] = cls.__init__

    @functools.wraps(original)
    def init(self: QWidget, *args: Any, **kwargs: Any) -> None:
        original(self, *args, **kwargs)
        if is_active() and self.isWindow():
            _prepare(self)

    cls.__init__ = init  # pyright: ignore[reportAttributeAccessIssue]


def glass_palette(base: QPalette, *, dark: bool) -> QPalette:
    """Return ``base`` with translucent surfaces so the backdrop shows through."""
    palette = QPalette(base)
    if dark:
        surfaces = {
            QPalette.ColorRole.Window: QColor(32, 32, 36, 48),
            QPalette.ColorRole.Base: QColor(24, 24, 28, 120),
            QPalette.ColorRole.AlternateBase: QColor(255, 255, 255, 14),
            QPalette.ColorRole.Button: QColor(255, 255, 255, 24),
        }
    else:
        surfaces = {
            QPalette.ColorRole.Window: QColor(255, 255, 255, 70),
            QPalette.ColorRole.Base: QColor(255, 255, 255, 150),
            QPalette.ColorRole.AlternateBase: QColor(255, 255, 255, 90),
            QPalette.ColorRole.Button: QColor(255, 255, 255, 150),
        }
    for role, color in surfaces.items():
        palette.setColor(role, color)
    return palette


def glass_stylesheet(*, dark: bool) -> str:
    """Return the rounded, softly lit widget styling for the glass look."""
    if dark:
        fill, hover, pressed = (
            'rgba(255,255,255,0.07)',
            'rgba(255,255,255,0.15)',
            'rgba(255,255,255,0.03)',
        )
        pane, selected = 'rgba(255,255,255,0.05)', 'rgba(255,255,255,0.14)'
        lit, edge, shade = (
            'rgba(255,255,255,0.34)',
            'rgba(255,255,255,0.13)',
            'rgba(255,255,255,0.05)',
        )
    else:
        fill, hover, pressed = (
            'rgba(255,255,255,0.60)',
            'rgba(255,255,255,0.85)',
            'rgba(255,255,255,0.35)',
        )
        pane, selected = 'rgba(255,255,255,0.40)', 'rgba(255,255,255,0.80)'
        lit, edge, shade = 'rgba(255,255,255,0.95)', 'rgba(0,0,0,0.10)', 'rgba(0,0,0,0.16)'
    # Border colors are top, right, bottom, left: a bright top edge gives the
    # specular highlight of a glass pane.
    border = f'border: 1px solid; border-color: {lit} {edge} {shade} {edge};'
    return f"""
QPushButton {{ background-color: {fill}; {border} border-radius: 8px; padding: 4px 12px; }}
QPushButton:hover {{ background-color: {hover}; }}
QPushButton:pressed {{ background-color: {pressed}; }}
QPushButton:checked {{ background-color: palette(highlight); color: palette(highlighted-text); }}
QPushButton:default {{ border-color: palette(highlight); }}
QPushButton:disabled {{ background-color: transparent; }}
QPushButton:flat {{ background-color: transparent; border: none; }}
QLineEdit {{ {border} border-radius: 6px; padding: 3px 6px; }}
QTabWidget::pane {{
    border: 1px solid {edge}; border-radius: 10px; background-color: {pane}; top: -1px;
}}
QTabBar::tab {{
    background-color: transparent; border: 1px solid transparent;
    border-top-left-radius: 8px; border-top-right-radius: 8px; padding: 6px 14px; margin: 2px 2px 0 2px;
}}
QTabBar::tab:selected {{ background-color: {selected}; border-color: {edge}; }}
QTabBar::tab:hover:!selected {{ background-color: {fill}; }}
QGroupBox {{ border: 1px solid {edge}; border-radius: 10px; margin-top: 1.2ex; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; }}
"""


def install(app: QApplication, *, dark: bool) -> None:
    """Start turning new windows into glass and (re)apply the widget styling."""
    _state.dark = dark
    if _state.event_filter is None:
        _state.event_filter = _GlassWindowFilter(app)
        app.installEventFilter(_state.event_filter)
    if not _state.patched:
        for cls in (QDialog, QMainWindow, QMessageBox):
            _patch_window_class(cls)
        _state.patched = True

    sheet = glass_stylesheet(dark=dark)
    current = app.styleSheet()
    if _state.stylesheet:
        current = current.replace(_state.stylesheet, '')
    _state.stylesheet = sheet
    app.setStyleSheet(current + sheet)


def refresh_windows(app: QApplication) -> None:
    """Let windows that are already open follow a light/dark change."""
    for widget in app.topLevelWidgets():
        if widget.property(_GLASS_PROPERTY):
            _restyle(widget)
            if widget.isVisible():
                _apply_backdrop(int(widget.winId()), dark=_state.dark)


def remove(app: QApplication) -> None:
    """Drop the glass widget styling, if it was applied."""
    if _state.stylesheet is None:
        return
    app.setStyleSheet(app.styleSheet().replace(_state.stylesheet, ''))
    _state.stylesheet = None
