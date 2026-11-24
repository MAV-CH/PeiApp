import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QUrl
from PySide6.QtGui import QColor, QIcon, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QShortcut
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
    QLabel, QProgressBar, QPushButton, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from analysis import AnalysisThread, Analyzer, Segment, find_analyzer
from widgets import Timeline, TitleBar, VideoView, timecode


LOGO_PATH = Path(__file__).with_name("Pei-01-CRT.png")
VIDEO_FILTER = "Видео (*.mp4 *.m4v *.mov *.mkv *.avi *.webm *.wmv *.mpeg *.mpg *.ts);;Все файлы (*)"
STYLE = """
QWidget {
    color: #f3efd9;
    font-family: "Segoe UI", sans-serif;
    font-size: 13px;
}
QFrame#Panel {
    background-color: rgba(29, 32, 24, 229);
    border: 1px solid #3c4130;
    border-radius: 15px;
}
QStackedWidget#VideoSurface { background-color: #0a0c09; border: 1px solid #363b2c; }
QLabel[role="heading"] { font-size: 16px; font-weight: 700; }
QLabel[role="title"] { font-size: 20px; font-weight: 700; }
QLabel[role="muted"] { color: #b8bbaa; }
QLabel[role="metric"] { color: #f5edcb; font-size: 16px; font-weight: 700; }
QLabel[role="legend"] { color: #c8e58c; }
QPushButton {
    background-color: #2c3124;
    border: 1px solid #464b39;
    border-radius: 8px;
    padding: 6px 10px;
    min-height: 21px;
}
QPushButton:hover { background-color: #3a422f; border-color: #707c53; }
QPushButton:focus { border-color: #b9db61; }
QPushButton:disabled { color: #84887b; background-color: #24271f; border-color: #34382d; }
QPushButton[role="primary"] { color: #171b10; background-color: #d9e9a6; font-weight: 700; }
QPushButton[role="primary"]:hover { background-color: #edf6ca; }
QPushButton[role="primary"]:disabled { color: #84887b; background-color: #24271f; }
QPushButton[role="window"], QPushButton[role="close"] {
    background-color: transparent;
    border-color: transparent;
    padding: 0;
    font-size: 20px;
}
QPushButton[role="window"]:hover, QPushButton[role="window"]:focus { background-color: #353a2d; }
QPushButton[role="close"]:hover, QPushButton[role="close"]:focus { background-color: #852d28; }
QProgressBar { background-color: #34392a; border: none; border-radius: 3px; }
QProgressBar::chunk { background-color: #b9db61; border-radius: 3px; }
"""


def label(text: str, role: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        widget.setProperty("role", role)
    return widget


def button(text: str, role: str = "") -> QPushButton:
    widget = QPushButton(text)
    widget.setCursor(Qt.CursorShape.PointingHandCursor)
    if role:
        widget.setProperty("role", role)
    return widget


def panel(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("Panel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 13, 16, 13)
    layout.setSpacing(10)
    layout.addWidget(label(title, "heading"))
    return frame, layout


class PeiWindow(QWidget):
    def __init__(self, analyzer: Analyzer | None = None):
        super().__init__(None, Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setWindowTitle("Pei — анализ пайки")
        self.setWindowIcon(QIcon(str(LOGO_PATH)))
        self.setMinimumSize(820, 610)
        self.resize(1150, 730)
        self.logo = QPixmap(str(LOGO_PATH))
        self.analyzer = analyzer
        self.video_path: Path | None = None
        self.duration = 0
        self.results: list[Segment] | None = None
        self.analysis_thread: AnalysisThread | None = None
        self.cancel_requested = False
        self.close_after_analysis = False
        self.media_failed = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.audio.setVolume(0.65)
        self.player.setAudioOutput(self.audio)
        self.build_interface()
        self.player.setVideoOutput(self.video_view.video_item)
        self.video_view.video_item.videoSink().videoFrameChanged.connect(self.show_video_frame)
        self.player.positionChanged.connect(self.update_position)
        self.player.durationChanged.connect(self.update_duration)
        self.player.playbackStateChanged.connect(self.refresh_controls)
        self.player.mediaStatusChanged.connect(self.media_status_changed)
        self.player.hasVideoChanged.connect(self.refresh_controls)
        self.player.hasAudioChanged.connect(self.refresh_controls)
        self.player.seekableChanged.connect(self.refresh_controls)
        self.player.errorOccurred.connect(self.media_error)

        self.open_shortcut = QShortcut(QKeySequence.StandardKey.Open, self)
        self.open_shortcut.activated.connect(self.choose_video)
        self.refresh_controls()

    def build_interface(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 17, 22, 23)
        root.setSpacing(12)
        root.addWidget(self.build_title_bar())

        body = QHBoxLayout()
        body.setSpacing(14)
        root.addLayout(body, 1)

        sidebar = QWidget()
        sidebar.setFixedWidth(258)
        left = QVBoxLayout(sidebar)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(13)
        left.addWidget(self.build_file_panel(), 3)
        left.addWidget(self.build_stats_panel(), 2)
        body.addWidget(sidebar)

        right = QVBoxLayout()
        right.setSpacing(13)
        right.addWidget(self.build_video_panel(), 1)
        right.addWidget(self.build_timeline_panel())
        body.addLayout(right, 1)

    def logo_label(self, size: int) -> QLabel:
        widget = label("")
        widget.setFixedSize(size, size)
        widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        if not self.logo.isNull():
            image = self.logo.scaled(size * 2, size * 2, Qt.AspectRatioMode.KeepAspectRatio,
                                     Qt.TransformationMode.SmoothTransformation)
            image.setDevicePixelRatio(2)
            widget.setPixmap(image)
        return widget

    def build_title_bar(self) -> TitleBar:
        title_bar = TitleBar(self)
        title_bar.setFixedHeight(62)
        row = QHBoxLayout(title_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        row.addWidget(self.logo_label(62))
        title = label("Анализ пайки", "title")
        title.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        row.addWidget(title)
        row.addStretch()

        minimize = button("−", "window")
        self.maximize = button("□", "window")
        close = button("×", "close")
        for control, name in ((minimize, "Свернуть"), (self.maximize, "Развернуть"), (close, "Закрыть")):
            control.setFixedSize(37, 34)
            control.setAccessibleName(name)
            control.setToolTip(name)
            row.addWidget(control)
        minimize.clicked.connect(self.showMinimized)
        self.maximize.clicked.connect(self.toggle_maximized)
        close.clicked.connect(self.close)
        return title_bar

    def build_file_panel(self) -> QFrame:
        frame, layout = panel("Файл видео")
        self.open_button = button("Выбрать файл…", "primary")
        self.open_button.clicked.connect(self.choose_video)
        layout.addWidget(self.open_button)

        self.file_name = label("Файл не выбран", "muted")
        self.file_name.setWordWrap(True)
        self.file_name.setMaximumHeight(48)
        layout.addWidget(self.file_name)
        self.file_info = label("", "muted")
        self.file_info.setWordWrap(True)
        layout.addWidget(self.file_info)
        layout.addStretch()

        self.run_button = button("Анализировать видео")
        self.run_button.clicked.connect(self.run_or_cancel_analysis)
        layout.addWidget(self.run_button)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setFixedHeight(6)
        self.progress.setTextVisible(False)
        self.progress.setAccessibleName("Ход анализа")
        self.progress.hide()
        layout.addWidget(self.progress)
        status = "Выберите видео для анализа" if self.analyzer else "Модель пайки не подключена"
        self.analysis_status = label(status, "muted")
        self.analysis_status.setWordWrap(True)
        self.analysis_status.setMaximumHeight(48)
        layout.addWidget(self.analysis_status)
        return frame

    def build_stats_panel(self) -> QFrame:
        frame, layout = panel("Статистика")
        self.stats = []
        for title in ("Участки пайки", "Время пайки", "Доля видео"):
            row = QHBoxLayout()
            row.addWidget(label(title, "muted"))
            row.addStretch()
            value = label("—", "metric")
            row.addWidget(value)
            self.stats.append(value)
            layout.addLayout(row)
        layout.addStretch()
        return frame

    def build_video_panel(self) -> QFrame:
        frame, layout = panel("Видео")
        self.surface = QStackedWidget()
        self.surface.setObjectName("VideoSurface")
        self.surface.setMinimumHeight(215)
        placeholder = QWidget()
        center = QVBoxLayout(placeholder)
        center.setContentsMargins(16, 16, 16, 16)
        center.setSpacing(11)
        center.addStretch()
        mark = self.logo_label(106)
        opacity = QGraphicsOpacityEffect(mark)
        opacity.setOpacity(0.55)
        mark.setGraphicsEffect(opacity)
        center.addWidget(mark, 0, Qt.AlignmentFlag.AlignHCenter)
        self.video_hint = label("Выберите видео", "muted")
        self.video_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_hint.setWordWrap(True)
        center.addWidget(self.video_hint)
        center.addStretch()
        self.surface.addWidget(placeholder)
        self.video_view = VideoView()
        self.surface.addWidget(self.video_view)
        layout.addWidget(self.surface, 1)

        controls = QHBoxLayout()
        self.play_button = button("▶  Воспроизвести")
        self.play_button.setMinimumWidth(154)
        self.play_button.clicked.connect(self.toggle_playback)
        controls.addWidget(self.play_button)
        controls.addStretch()
        self.sound_button = button("Звук включён")
        self.sound_button.setCheckable(True)
        self.sound_button.toggled.connect(self.set_muted)
        controls.addWidget(self.sound_button)
        layout.addLayout(controls)
        return frame

    def build_timeline_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("Panel")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 11, 16, 7)
        layout.setSpacing(1)
        row = QHBoxLayout()
        row.addWidget(label("Таймлайн", "heading"))
        row.addSpacing(10)
        row.addWidget(label("■  Пайка", "legend"))
        row.addStretch()
        self.clock = label("00:00 / —", "muted")
        row.addWidget(self.clock)
        layout.addLayout(row)
        self.timeline = Timeline()
        self.timeline.seek_requested.connect(self.seek)
        layout.addWidget(self.timeline)
        return frame

    def choose_video(self):
        if self.analysis_thread is not None:
            return
        directory = str(self.video_path.parent) if self.video_path else ""
        selected, _ = QFileDialog.getOpenFileName(self, "Выберите видео", directory, VIDEO_FILTER)
        if selected:
            self.open_video(Path(selected))

    def open_video(self, path: Path):
        if self.analysis_thread is not None:
            return
        self.player.stop()
        self.player.setSource(QUrl())
        self.video_path = path.resolve()
        self.media_failed = False
        self.results = None
        self.update_duration(0)
        self.update_position(0)
        self.file_name.setText(path.name)
        self.file_name.setToolTip(str(self.video_path))
        self.file_info.clear()
        self.file_info.setToolTip("")
        self.surface.setCurrentIndex(0)
        self.video_hint.setText("Загрузка видео…")
        if self.analyzer:
            self.analysis_status.setText("Ожидание загрузки видео")
            self.analysis_status.setToolTip("")
        self.player.setSource(QUrl.fromLocalFile(str(self.video_path)))
        self.refresh_controls()

    def media_status_changed(self, status):
        state = QMediaPlayer.MediaStatus
        if status == state.LoadedMedia and self.video_path and not self.media_failed:
            self.video_hint.setText("Нажмите «Воспроизвести»" if self.player.hasVideo()
                                    else "В файле нет видеодорожки")
            if self.player.hasVideo() and self.analyzer:
                self.analysis_status.setText("Видео готово к анализу")
        self.refresh_controls()

    def media_error(self, error, message: str):
        if not self.video_path:
            return
        self.media_failed = True
        self.surface.setCurrentIndex(0)
        self.video_hint.setText("Не удалось открыть видео")
        self.file_info.setText(message or "Проверьте формат файла.")
        self.file_info.setToolTip(message)
        self.refresh_controls()

    def show_video_frame(self, frame):
        if self.video_path and not self.media_failed and frame.isValid():
            self.surface.setCurrentWidget(self.video_view)

    def can_play(self) -> bool:
        state = QMediaPlayer.MediaStatus
        return bool(self.video_path and not self.media_failed and self.player.hasVideo()
                    and self.player.mediaStatus() not in (state.NoMedia, state.LoadingMedia, state.InvalidMedia))

    def refresh_controls(self, *_):
        playing = self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ready = self.can_play()
        self.play_button.setText("Ⅱ  Пауза" if playing else "▶  Воспроизвести")
        self.play_button.setEnabled(ready)
        self.sound_button.setEnabled(ready and self.player.hasAudio())
        self.timeline.setEnabled(ready and self.duration > 0 and self.player.isSeekable())
        self.open_button.setEnabled(self.analysis_thread is None)
        if self.analysis_thread is not None:
            self.run_button.setText("Отмена…" if self.cancel_requested else "Отменить анализ")
            self.run_button.setEnabled(not self.cancel_requested)
        else:
            self.run_button.setText("Анализировать видео")
            self.run_button.setEnabled(bool(self.analyzer and ready and self.duration))

    def toggle_playback(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        elif self.can_play():
            if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                self.player.setPosition(0)
            self.player.play()

    def set_muted(self, muted: bool):
        self.audio.setMuted(muted)
        self.sound_button.setText("Звук выключен" if muted else "Звук включён")

    def seek(self, milliseconds: int):
        if self.timeline.isEnabled():
            self.player.setPosition(milliseconds)

    def update_position(self, milliseconds: int):
        self.timeline.set_position(milliseconds)
        total = timecode(self.duration) if self.duration else "—"
        self.clock.setText(f"{timecode(milliseconds)} / {total}")

    def update_duration(self, milliseconds: int):
        self.duration = max(0, milliseconds)
        self.timeline.duration = self.duration
        if self.duration and not self.media_failed:
            self.file_info.setText(f"Длительность  {timecode(self.duration)}")
        self.update_position(self.player.position())
        self.update_statistics()
        self.refresh_controls()

    def run_or_cancel_analysis(self):
        if self.analysis_thread is not None:
            self.request_analysis_cancel()
            return
        if not self.analyzer or not self.video_path or not self.can_play() or not self.duration:
            return
        self.results = None
        self.update_statistics()
        self.cancel_requested = False
        self.analysis_status.setText("Анализ видео…")
        self.analysis_status.setToolTip("")
        self.progress.setRange(0, 0)
        self.progress.show()

        worker = AnalysisThread(self.analyzer, self.video_path, self)
        self.analysis_thread = worker
        worker.progress_changed.connect(self.analysis_progress)
        worker.completed.connect(self.analysis_completed)
        worker.failed.connect(self.analysis_failed)
        worker.finished.connect(self.analysis_finished)
        self.refresh_controls()
        worker.start()

    def analysis_progress(self, percent: int):
        if not self.cancel_requested:
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            self.analysis_status.setText(f"Анализ видео · {percent}%")

    def analysis_completed(self, result: list[Segment]):
        if not self.cancel_requested:
            self.results = result
            self.update_statistics()
            self.analysis_status.setText("Анализ завершён")
            self.analysis_status.setToolTip("")

    def analysis_failed(self, message: str):
        if not self.cancel_requested:
            self.analysis_status.setText(f"Ошибка анализа: {message}")
            self.analysis_status.setToolTip(message)

    def request_analysis_cancel(self):
        if self.analysis_thread is not None:
            self.cancel_requested = True
            self.analysis_thread.requestInterruption()
            self.analysis_status.setText("Отмена анализа…")
            self.refresh_controls()

    def analysis_finished(self):
        worker = self.analysis_thread
        self.analysis_thread = None
        if worker is not None:
            worker.deleteLater()
        self.progress.hide()
        if self.cancel_requested:
            self.analysis_status.setText("Анализ отменён")
        self.refresh_controls()
        if self.close_after_analysis:
            self.close()

    def update_statistics(self):
        segments = [(start, min(end, self.duration)) for start, end in (self.results or [])
                    if start < self.duration]
        self.timeline.segments = segments
        self.timeline.update()
        texts = ("—", "—", "—")
        if self.results is not None and self.duration:
            total = sum(end - start for start, end in segments)
            share = f"{100 * total / self.duration:.1f}".replace(".", ",")
            texts = (str(len(segments)), timecode(total, precise=True).replace(".", ","), f"{share}%")
        for widget, text in zip(self.stats, texts):
            widget.setText(text)

    def toggle_maximized(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "maximize"):
            maximized = self.isMaximized()
            title = "Восстановить размер" if maximized else "Развернуть"
            self.maximize.setText("❐" if maximized else "□")
            self.maximize.setToolTip(title)
            self.maximize.setAccessibleName(title)
            self.update()

    def resize_edges(self, point):
        edges = Qt.Edge(0)
        if not self.isMaximized():
            if point.x() < 7:
                edges |= Qt.Edge.LeftEdge
            elif point.x() >= self.width() - 7:
                edges |= Qt.Edge.RightEdge
            if point.y() < 7:
                edges |= Qt.Edge.TopEdge
            elif point.y() >= self.height() - 7:
                edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event):
        handle = self.windowHandle()
        edges = self.resize_edges(event.position())
        if edges and handle and event.button() == Qt.MouseButton.LeftButton and handle.startSystemResize(edges):
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        edges = self.resize_edges(event.position())
        horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
        vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
        cursor = Qt.CursorShape.ArrowCursor
        if horizontal and vertical:
            diagonal = edges in (Qt.Edge.TopEdge | Qt.Edge.LeftEdge, Qt.Edge.BottomEdge | Qt.Edge.RightEdge)
            cursor = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
        elif horizontal:
            cursor = Qt.CursorShape.SizeHorCursor
        elif vertical:
            cursor = Qt.CursorShape.SizeVerCursor
        self.setCursor(cursor)
        super().mouseMoveEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
        frame = QPainterPath()
        radius = 0 if self.isMaximized() else 25
        frame.addRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
        background = QRadialGradient(QPointF(50, 20), self.width() * 0.86)
        background.setColorAt(0, QColor("#282d16"))
        background.setColorAt(0.55, QColor("#171a12"))
        background.setColorAt(1, QColor("#10120f"))
        painter.fillPath(frame, background)
        painter.strokePath(frame, QPen(QColor("#4c5237"), 1))
        painter.setClipPath(frame)

        if not self.logo.isNull():
            extent = min(self.height(), self.width()) * 0.88
            watermark = QRectF(self.width() - extent * 0.88, self.height() - extent * 0.84, extent, extent)
            painter.setOpacity(0.10)
            painter.drawPixmap(watermark, self.logo, QRectF(self.logo.rect()))
            painter.setOpacity(1)

        for index, color in enumerate(("#e86951", "#92c752", "#538bdf")):
            inset = 8 + index * 5
            right = self.width() - inset
            bottom = self.height() - inset
            bend = 20 - index * 3
            origin_y = 35 + index * 6
            trace = QPainterPath(QPointF(73, origin_y))
            trace.cubicTo(96, origin_y, 91, inset, 111, inset)
            trace.lineTo(right - bend, inset)
            trace.quadTo(right, inset, right, inset + bend)
            trace.lineTo(right, bottom - bend)
            trace.quadTo(right, bottom, right - bend, bottom)
            trace.lineTo(inset + bend, bottom)
            trace.quadTo(inset, bottom, inset, bottom - bend)
            trace.lineTo(inset, 79 + index * 4)
            rail = QColor(color)
            rail.setAlpha(168)
            painter.strokePath(trace, QPen(rail, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))

    def closeEvent(self, event):
        if self.analysis_thread is not None:
            self.close_after_analysis = True
            self.request_analysis_cancel()
            event.ignore()
            return
        self.player.stop()
        self.player.setSource(QUrl())
        super().closeEvent(event)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Pei")
    app.setWindowIcon(QIcon(str(LOGO_PATH)))
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = PeiWindow(find_analyzer())
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
