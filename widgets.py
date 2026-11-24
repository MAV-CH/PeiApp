from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import QFrame, QGraphicsScene, QGraphicsView, QWidget

from analysis import Segment


def timecode(milliseconds: int, precise: bool = False) -> str:
    seconds, remainder = divmod(max(0, milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    clock = f"{hours}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
    return f"{clock}.{remainder:03}" if precise else clock


class VideoView(QGraphicsView):
    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QColor("#070807"))
        self.setAccessibleName("Видеоплеер")
        self.video_item = QGraphicsVideoItem()
        self.video_item.setAspectRatioMode(Qt.AspectRatioMode.KeepAspectRatio)
        self.scene().addItem(self.video_item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        size = QSizeF(self.viewport().size())
        self.setSceneRect(QRectF(QPointF(), size))
        self.video_item.setSize(size)


class Timeline(QWidget):
    seek_requested = Signal("qint64")

    def __init__(self):
        super().__init__()
        self.duration = 0
        self.position = 0
        self.segments: list[Segment] = []
        self.setMinimumHeight(55)
        self.setMaximumHeight(55)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName("Таймлайн пайки")
        self.setAccessibleDescription("Используйте стрелки для перехода на пять секунд.")
        self.setEnabled(False)

    def set_position(self, milliseconds: int):
        self.position = max(0, min(milliseconds, self.duration))
        self.update()

    def track(self) -> QRectF:
        return QRectF(7, 9, max(1, self.width() - 14), 13)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = self.track()
        clip = QPainterPath()
        clip.addRoundedRect(track, 5, 5)
        painter.fillPath(clip, QColor("#32352a"))
        scale = track.width() / max(1, self.duration)

        painter.save()
        painter.setClipPath(clip)
        for start, end in self.segments:
            left = track.left() + start * scale
            painter.fillRect(QRectF(left, track.top(), max(2, (end - start) * scale), track.height()), QColor("#b9db61"))
        painter.restore()

        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        metrics = painter.fontMetrics()
        for index in range(5):
            x = track.left() + track.width() * index / 4
            painter.setPen(QColor("#515545"))
            painter.drawLine(QPointF(x, 28), QPointF(x, 33))
            if self.duration or index == 0:
                label = timecode(self.duration * index // 4)
                label_width = metrics.horizontalAdvance(label)
                label_x = max(track.left(), min(x - label_width / 2, track.right() - label_width))
                painter.setPen(QColor("#b8bbaa"))
                painter.drawText(QPointF(label_x, 48), label)

        if self.duration:
            x = track.left() + self.position * scale
            painter.setPen(QPen(QColor("#fff2c2"), 2))
            painter.drawLine(QPointF(x, 4), QPointF(x, 26))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#fff2c2"))
            painter.drawEllipse(QPointF(x, 4), 2.5, 2.5)
        if self.hasFocus():
            painter.setPen(QPen(QColor("#a7ac83"), 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)

    def time_at(self, x: float) -> int:
        track = self.track()
        ratio = (x - track.left()) / track.width()
        return round(max(0, min(1, ratio)) * self.duration)

    def mousePressEvent(self, event):
        if self.duration and event.button() == Qt.MouseButton.LeftButton:
            self.seek_requested.emit(self.time_at(event.position().x()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if not self.duration:
            return
        target = self.time_at(event.position().x())
        if event.buttons() & Qt.MouseButton.LeftButton:
            self.seek_requested.emit(target)
            return
        label = timecode(target)
        for start, end in self.segments:
            if start <= target < end:
                label = f"Пайка  {timecode(start, True)} – {timecode(end, True)}"
                break
        self.setToolTip(label)

    def keyPressEvent(self, event):
        targets = {
            Qt.Key.Key_Left: self.position - 5000,
            Qt.Key.Key_Right: self.position + 5000,
            Qt.Key.Key_Home: 0,
            Qt.Key.Key_End: self.duration,
        }
        if self.duration and event.key() in targets:
            self.seek_requested.emit(max(0, min(targets[event.key()], self.duration)))
            event.accept()
        else:
            super().keyPressEvent(event)


class TitleBar(QWidget):
    def __init__(self, window):
        super().__init__(window)
        self.drag_offset = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            handle = window.windowHandle()
            if not (handle and handle.startSystemMove()) and not window.isMaximized():
                self.drag_offset = event.globalPosition().toPoint() - window.frameGeometry().topLeft()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.window().move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event):
        self.drag_offset = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            window = self.window()
            if window.isMaximized():
                window.showNormal()
            else:
                window.showMaximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
