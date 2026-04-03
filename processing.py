"""
processing.py — Non-destructive image processing pipeline.
Applied to preview frames; never modifies saved images.
"""

import numpy as np
import cv2


class ProcessingPipeline:
    def __init__(self):
        self.grayscale_enabled = False   # force single-channel display
        self.threshold_enabled = False
        self.threshold_value   = 128     # 0–255
        self.threshold_mode    = "binary"  # "binary" | "otsu"

    # ------------------------------------------------------------------

    def process(self, frame: np.ndarray) -> np.ndarray:
        """
        Apply enabled processing steps to a frame.
        Input : H x W (gray) or H x W x C (color) uint8
        Output: H x W uint8 (always single channel after pipeline)
        """
        out = frame.copy()

        # Ensure grayscale
        if out.ndim == 3:
            out = cv2.cvtColor(out, cv2.COLOR_BGR2GRAY if out.shape[2] == 3
                               else cv2.COLOR_BGRA2GRAY)

        if self.threshold_enabled:
            out = self._apply_threshold(out)

        return out

    def _apply_threshold(self, gray: np.ndarray) -> np.ndarray:
        if self.threshold_mode == "otsu":
            _, out = cv2.threshold(gray, 0, 255,
                                   cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            _, out = cv2.threshold(gray, self.threshold_value, 255,
                                   cv2.THRESH_BINARY)
        return out
