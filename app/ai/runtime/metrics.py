"""Runtime metrics.

A minimal, dependency-free sink (counters + bounded observations) behind the
MetricsSink protocol. Swapping in Prometheus/StatsD later means registering a
different sink — call sites never change."""
from collections import defaultdict
from threading import Lock
from typing import Dict, List, Tuple

_MAX_OBSERVATIONS = 1000


class InMemoryMetricsSink:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: Dict[Tuple[str, frozenset], float] = defaultdict(float)
        self._observations: Dict[Tuple[str, frozenset], List[float]] = defaultdict(list)

    def increment(self, name: str, value: float = 1.0, **labels: str) -> None:
        key = (name, frozenset(labels.items()))
        with self._lock:
            self._counters[key] += value

    def observe(self, name: str, value: float, **labels: str) -> None:
        key = (name, frozenset(labels.items()))
        with self._lock:
            series = self._observations[key]
            series.append(value)
            if len(series) > _MAX_OBSERVATIONS:
                del series[: len(series) - _MAX_OBSERVATIONS]

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counters": {
                    f"{name}{dict(labels) if labels else ''}": count
                    for (name, labels), count in self._counters.items()
                },
                "observations": {
                    f"{name}{dict(labels) if labels else ''}": {
                        "count": len(series),
                        "avg": sum(series) / len(series) if series else 0.0,
                        "max": max(series) if series else 0.0,
                    }
                    for (name, labels), series in self._observations.items()
                },
            }


metrics = InMemoryMetricsSink()
