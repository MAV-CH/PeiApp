from collections.abc import Callable, Iterable
from importlib import import_module, util
from pathlib import Path

from PySide6.QtCore import QThread, Signal


# Интервалы задаются парами (начало, конец) в миллисекундах видео.
Segment = tuple[int, int]
Analyzer = Callable[[Path, Callable[[int], None], Callable[[], bool]], Iterable[Segment]]


def find_analyzer() -> Analyzer | None:
    """Найти соседний pei_model.py. Модель загружается в рабочем потоке."""
    if util.find_spec("pei_model") is None:
        return None

    def analyze(path: Path, progress: Callable[[int], None], cancelled: Callable[[], bool]):
        return import_module("pei_model").analyze_video(path, progress, cancelled)

    return analyze


def merge_segments(segments: Iterable[Segment]) -> list[Segment]:
    """Проверить ответ модели и объединить смежные и пересекающиеся интервалы."""
    valid: list[Segment] = []
    for start, end in segments:
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("Ожидаются интервалы (начало, конец) в целых миллисекундах.")
        valid.append((start, end))

    merged: list[Segment] = []
    for start, end in sorted(valid):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


class AnalysisThread(QThread):
    progress_changed = Signal(int)
    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, analyzer: Analyzer, path: Path, parent=None):
        super().__init__(parent)
        self.analyzer = analyzer
        self.path = path

    def run(self):
        try:
            segments = self.analyzer(self.path, self.report_progress, self.isInterruptionRequested)
            if not self.isInterruptionRequested():
                result = merge_segments(segments)
                if not self.isInterruptionRequested():
                    self.completed.emit(result)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.failed.emit(str(error) or type(error).__name__)

    def report_progress(self, percent: int):
        self.progress_changed.emit(max(0, min(100, int(percent))))
