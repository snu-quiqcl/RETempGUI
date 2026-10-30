"""Average photon counts through validated acquire/assign in one queued operation."""
from datetime import datetime, timezone
import time
from labremote.runtime.io import Context


def measure_counts(p, channel, exposure_ms, average):
    started = time.perf_counter()
    timings = {}
    ctx = Context()
    ctx.assign(p.average, average)
    ctx.assign(p.channel, channel)
    ctx.assign(p.exposure_ms, exposure_ms)
    total = 0
    for _ in range(average):
        result = ctx.acquire(p.measurement)
        total += result['count']
        for stage, duration in result.get('timings_ms', {}).items():
            timings[stage] = timings.get(stage, 0.0) + duration
    return dict(channel=result['channel'], ms=result['ms'], average=average,
                count=total / average, total_count=total, timings_ms=timings,
                operation_ms=(time.perf_counter() - started) * 1000,
                time_utc=datetime.now(timezone.utc).isoformat(), monotonic_s=time.monotonic())
