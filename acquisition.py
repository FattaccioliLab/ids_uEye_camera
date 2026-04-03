"""
acquisition.py — Frame saving logic.
Single grab, timelapse, and burst acquisition.
Saves 16-bit TIFF with metadata embedded in ImageDescription.
"""

import time
import json
import numpy as np
import tifffile
from pathlib import Path
from datetime import datetime


def _build_metadata(camera, frame_index: int = 0, extra: dict = None) -> dict:
    roi = camera.get_roi()
    meta = {
        "timestamp":   datetime.now().isoformat(),
        "frame_index": frame_index,
        "exposure_us": camera.get_exposure(),
        "gain":        camera.get_gain(),
        "roi_x":       roi["x"],
        "roi_y":       roi["y"],
        "roi_width":   roi["width"],
        "roi_height":  roi["height"],
    }
    if extra:
        meta.update(extra)
    return meta


def _save_tiff(frame: np.ndarray, path: Path, metadata: dict):
    """Save frame as 16-bit TIFF with JSON metadata in ImageDescription."""
    # Promote to uint16 for scientific use (preserves headroom even if input is uint8)
    if frame.dtype == np.uint8:
        data16 = frame.astype(np.uint16) * 257  # scale 0-255 → 0-65535
    else:
        data16 = frame.astype(np.uint16)

    tifffile.imwrite(
        str(path),
        data16,
        photometric="minisblack",
        description=json.dumps(metadata),
        compression=None,
    )


def grab_single(camera, save_dir: str, prefix: str = "frame") -> Path:
    """Grab one frame and save it."""
    frame = camera.grab_frame()
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = save_dir / f"{prefix}_{ts}.tiff"
    meta = _build_metadata(camera, frame_index=0)
    _save_tiff(frame, path, meta)
    return path


def run_timelapse(camera, save_dir: str, n_frames: int,
                  interval_s: float, prefix: str = "timelapse",
                  progress_callback=None, stop_flag=None) -> list:
    """
    Acquire n_frames with interval_s between frames.
    progress_callback(i, n_frames) called after each frame.
    stop_flag: a threading.Event; acquisition stops if set.
    Returns list of saved paths.
    """
    save_dir = Path(save_dir)
    save_dir.mkdir(parents=True, exist_ok=True)
    paths = []

    for i in range(n_frames):
        if stop_flag and stop_flag.is_set():
            break
        t0 = time.perf_counter()
        frame = camera.grab_frame()
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        path = save_dir / f"{prefix}_{i:05d}_{ts}.tiff"
        meta = _build_metadata(camera, frame_index=i)
        _save_tiff(frame, path, meta)
        paths.append(path)

        if progress_callback:
            progress_callback(i + 1, n_frames)

        # Sleep for remaining interval
        elapsed = time.perf_counter() - t0
        remaining = interval_s - elapsed
        if remaining > 0:
            time.sleep(remaining)

    return paths


def run_burst(camera, save_dir: str, n_frames: int,
              prefix: str = "burst",
              progress_callback=None, stop_flag=None) -> list:
    """
    Grab n_frames as fast as possible (no inter-frame delay).
    """
    return run_timelapse(camera, save_dir, n_frames,
                         interval_s=0.0, prefix=prefix,
                         progress_callback=progress_callback,
                         stop_flag=stop_flag)
