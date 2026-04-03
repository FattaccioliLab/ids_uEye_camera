# IDS uEye Camera Acquisition

A lightweight Python/PyQt6 acquisition software for IDS uEye USB3 cameras (tested on UI-3040CP-M), developed for scientific brightfield imaging.

The codes and the github wrapping have been created using Anthropic Claude Sonnet 4.6.

## Features

- Live preview with adjustable exposure and gain
- Hardware ROI selection
- Single frame grab, timelapse, and burst acquisition
- 16-bit TIFF output with embedded JSON metadata (exposure, gain, ROI, timestamp)
- Non-destructive preview processing: grayscale, threshold/binarization (binary or Otsu)
- Clean camera disconnect via UI button or window close

## Requirements

### System

- Ubuntu 22.04 / 24.04 (64-bit)
- IDS peak SDK ≥ 2.17 with uEye transport layer installed
  → Download: https://en.ids-imaging.com/downloads.html (IDS peak, Linux, USB)
- `libxcb-cursor0` for Qt xcb platform:
  ```bash
  sudo apt install libxcb-cursor0
  ```

### Python

Python 3.10+ recommended. Install dependencies in a virtual environment:

```bash
python3 -m venv ~/envs/camera
source ~/envs/camera/bin/activate
pip install -r requirements.txt
```

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/ids-ueye-acquisition.git
cd ids-ueye-acquisition
source ~/envs/camera/bin/activate
python main.py
```

## Repository structure

```
ids-ueye-acquisition/
├── main.py            # Entry point
├── main_window.py     # PyQt6 GUI and threading logic
├── ids_camera.py      # IDS peak API wrapper (device, stream, parameters)
├── acquisition.py     # Frame saving: single, timelapse, burst (16-bit TIFF)
├── processing.py      # Preview pipeline: grayscale, threshold
├── requirements.txt
└── README.md
```

## Usage

```bash
source ~/egit remote add origin https://github.com/FattaccioliLab/ids_uEye_camera.git
git branch -M main
git push -u origin mainnvs/camera/bin/activate
python main.py
```

1. The camera is detected and connected automatically on launch.
2. Click **Start Preview** to begin live streaming.
3. Adjust **Exposure** (spinbox or logarithmic slider) and **Gain** on the fly.
4. Set a hardware **ROI** and click **Apply ROI** (stream restarts automatically).
5. Enable **Threshold** overlay for preview-only binarization (does not affect saved files).
6. Select acquisition mode (**Single / Timelapse / Burst**), set save directory and prefix, then click **Acquire**.
7. Click **Stop stream & Quit** or close the window to properly release the camera.

## Output format

Frames are saved as **16-bit TIFF** files. Metadata is embedded in the `ImageDescription` tag as JSON:

```json
{
  "timestamp": "2025-04-03T14:32:10.123456",
  "frame_index": 0,
  "exposure_us": 5000.0,
  "gain": 1.0,
  "roi_x": 0,
  "roi_y": 0,
  "roi_width": 2048,
  "roi_height": 1536
}
```

Read metadata in Python:

```python
import tifffile, json
with tifffile.TiffFile("frame_00000.tiff") as tif:
    meta = json.loads(tif.pages[0].description)
    img  = tif.asarray()
```

## Notes

- Exposure and gain are adjustable while streaming without interrupting the preview.
- ROI changes require a brief acquisition restart (buffer reallocation), handled automatically.
- The `DataStream` is opened once per session and reused across stop/start cycles to avoid `GC_ERR_RESOURCE_IN_USE` errors.
- Saved TIFFs are always 16-bit regardless of the camera pixel format (uint8 frames are upscaled to preserve dynamic range headroom).

## To add in the future

- Possibility to add a scale manually, with a scalebar on the stream

## License

MIT
