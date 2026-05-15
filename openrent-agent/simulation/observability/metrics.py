class MetricsCollector:
    def __init__(self, runtime_metrics: dict):
        self.runtime_metrics = runtime_metrics
        self._prompt_tokens = 0
        self._completion_tokens = 0
        self._total_tokens = 0
        self._generation_latency_ms = 0
        self._evaluation_timing_ms = 0

    def record_generation(self, result, latency_ms: int) -> None:
        self._prompt_tokens += result.prompt_tokens
        self._completion_tokens += result.completion_tokens
        self._total_tokens += result.total_tokens
        self._generation_latency_ms += latency_ms
        self.runtime_metrics["prompt_size_chars"] = len(result.prompt or "")
        self.runtime_metrics["completion_size_chars"] = len(
            result.completion or ""
        )

    def record_evaluation(self, evaluation_timing_ms: int) -> None:
        self._evaluation_timing_ms += evaluation_timing_ms

    def finalize(self, run_duration_ms: int) -> dict:
        return {
            "prompt_tokens": self._prompt_tokens,
            "completion_tokens": self._completion_tokens,
            "total_tokens": self._total_tokens,
            "generation_latency_ms": self._generation_latency_ms,
            "evaluation_timing_ms": self._evaluation_timing_ms,
            "run_duration_ms": run_duration_ms,
            "prompt_size_chars": self.runtime_metrics.get(
                "prompt_size_chars",
                0,
            ),
            "completion_size_chars": self.runtime_metrics.get(
                "completion_size_chars",
                0,
            ),
        }

