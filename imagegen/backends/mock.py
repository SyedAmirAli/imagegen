"""Offline test backend.

Generates a synthetic image locally so the queue, resume, retry and
post-processing paths can be exercised end-to-end without spending real
generations or opening a browser. Not for production output.
"""

from __future__ import annotations

import hashlib
import io
import os
import random
import time

from PIL import Image, ImageDraw

from .base import Backend, BackendError, GenerationResult


class MockBackend(Backend):
    name = "mock"

    @staticmethod
    def add_arguments(parser) -> None:
        g = parser.add_argument_group("mock backend (testing only)")
        g.add_argument("--mock-fail-rate", type=float, default=0.0,
                       help="probability that a mock generation raises (0-1)")
        g.add_argument("--mock-delay", type=float, default=0.0,
                       help="seconds to fake-render, for watching the progress display")
        g.add_argument("--mock-transparent", action="store_true",
                       help="emit an image that already has an alpha cut-out")

    def open(self) -> None:
        pass

    def generate(self, job) -> GenerationResult:
        if random.random() < getattr(self.args, "mock_fail_rate", 0.0):
            raise BackendError("mock failure (injected)")

        delay = getattr(self.args, "mock_delay", 0.0)
        if delay:
            steps = max(1, int(delay * 10))
            for step in range(steps + 1):
                self.report("rendering", step / steps)
                time.sleep(delay / steps)

        size = job.size or (512, 512)
        digest = hashlib.sha256(job.id.encode()).digest()
        colour = (digest[0], digest[1], digest[2], 255)
        transparent = getattr(self.args, "mock_transparent", False)

        im = Image.new("RGBA", size, (0, 0, 0, 0) if transparent else (255, 255, 255, 255))
        draw = ImageDraw.Draw(im)
        pad = min(size) // 5
        draw.ellipse((pad, pad, size[0] - pad, size[1] - pad), fill=colour)
        draw.text((10, 10), job.id, fill=(0, 0, 0, 255))

        buf = io.BytesIO()
        im.save(buf, "PNG")
        return GenerationResult(
            data=buf.getvalue(),
            provider_image_id=f"mock-{os.getpid()}-{job.id[:24]}",
            content_type="image/png",
        )
