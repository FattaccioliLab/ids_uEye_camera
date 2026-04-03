"""
ids_camera.py — Low-level wrapper around ids_peak for the UI-3040CP-M.
Handles device lifecycle, parameter setting, and frame grabbing.

Key design: the DataStream is opened once and reused across stop/start cycles
to avoid GC_ERR_RESOURCE_IN_USE errors.
"""

import ids_peak.ids_peak as ids
import ids_peak_ipl.ids_peak_ipl as ipl
import numpy as np


class IDSCamera:
    def __init__(self):
        self._device      = None
        self._data_stream = None
        self._node_map    = None
        self._streaming   = False
        self._num_buffers = 5
        ids.Library.Initialize()

    # ------------------------------------------------------------------
    # Device open / close
    # ------------------------------------------------------------------

    def open(self):
        dm = ids.DeviceManager.Instance()
        dm.Update()
        if dm.Devices().empty():
            raise RuntimeError("No IDS camera found. Check USB connection.")
        self._device   = dm.Devices()[0].OpenDevice(ids.DeviceAccessType_Control)
        self._node_map = self._device.RemoteDevice().NodeMaps()[0]

    def close(self):
        self.stop_stream()
        self._close_data_stream()
        del self._device
        self._device   = None
        self._node_map = None
        ids.Library.Close()

    # ------------------------------------------------------------------
    # Camera info
    # ------------------------------------------------------------------

    def info(self) -> dict:
        nm = self._node_map
        return {
            "model":  nm.FindNode("DeviceModelName").Value(),
            "serial": nm.FindNode("DeviceSerialNumber").Value(),
            "width":  nm.FindNode("Width").Value(),
            "height": nm.FindNode("Height").Value(),
        }

    # ------------------------------------------------------------------
    # Parameters  (all safe to call while streaming)
    # ------------------------------------------------------------------

    def set_exposure(self, value_us: float):
        node = self._node_map.FindNode("ExposureTime")
        value_us = max(node.Minimum(), min(node.Maximum(), value_us))
        node.SetValue(value_us)

    def get_exposure(self) -> float:
        return self._node_map.FindNode("ExposureTime").Value()

    def get_exposure_range(self) -> tuple:
        node = self._node_map.FindNode("ExposureTime")
        return node.Minimum(), node.Maximum()

    def set_gain(self, value: float):
        node = self._node_map.FindNode("Gain")
        value = max(node.Minimum(), min(node.Maximum(), value))
        node.SetValue(value)

    def get_gain(self) -> float:
        return self._node_map.FindNode("Gain").Value()

    def get_gain_range(self) -> tuple:
        node = self._node_map.FindNode("Gain")
        return node.Minimum(), node.Maximum()

    def set_roi(self, x: int, y: int, width: int, height: int):
        """
        Set hardware ROI.
        Stops acquisition, changes ROI, reallocates buffers, restarts.
        The data stream object is reused — never reopened.
        """
        was_streaming = self._streaming
        if was_streaming:
            self._stop_acquisition()

        nm = self._node_map

        def _clamp(val, minimum, maximum, increment):
            val = max(minimum, min(maximum, val))
            val = minimum + round((val - minimum) / increment) * increment
            return int(val)

        w_node = nm.FindNode("Width")
        h_node = nm.FindNode("Height")
        x_node = nm.FindNode("OffsetX")
        y_node = nm.FindNode("OffsetY")

        x_node.SetValue(0)
        y_node.SetValue(0)

        w  = _clamp(width,  w_node.Minimum(), w_node.Maximum(), w_node.Increment())
        h  = _clamp(height, h_node.Minimum(), h_node.Maximum(), h_node.Increment())
        ox = _clamp(x,      x_node.Minimum(), x_node.Maximum(), x_node.Increment())
        oy = _clamp(y,      y_node.Minimum(), y_node.Maximum(), y_node.Increment())

        w_node.SetValue(w)
        h_node.SetValue(h)
        x_node.SetValue(ox)
        y_node.SetValue(oy)

        # Reallocate buffers for new payload size (ROI changed frame size)
        if self._data_stream is not None:
            self._revoke_buffers()
            self._allocate_buffers()

        if was_streaming:
            self._start_acquisition()

    def get_roi(self) -> dict:
        nm = self._node_map
        return {
            "x":      nm.FindNode("OffsetX").Value(),
            "y":      nm.FindNode("OffsetY").Value(),
            "width":  nm.FindNode("Width").Value(),
            "height": nm.FindNode("Height").Value(),
        }

    def get_sensor_size(self) -> tuple:
        nm = self._node_map
        nm.FindNode("OffsetX").SetValue(0)
        nm.FindNode("OffsetY").SetValue(0)
        return nm.FindNode("Width").Maximum(), nm.FindNode("Height").Maximum()

    # ------------------------------------------------------------------
    # Streaming public API
    # ------------------------------------------------------------------

    def start_stream(self, num_buffers: int = 5):
        if self._streaming:
            return
        self._num_buffers = num_buffers
        # Open data stream only once
        if self._data_stream is None:
            ds_list = self._device.DataStreams()
            if ds_list.empty():
                raise RuntimeError("No data stream available.")
            self._data_stream = ds_list[0].OpenDataStream()
            self._allocate_buffers()
        self._start_acquisition()

    def stop_stream(self):
        if not self._streaming:
            return
        self._stop_acquisition()
        # Buffers stay allocated — re-queue them for next start_stream
        try:
            self._data_stream.Flush(ids.DataStreamFlushMode_DiscardAll)
            for buf in self._data_stream.AnnouncedBuffers():
                try:
                    self._data_stream.QueueBuffer(buf)
                except Exception:
                    pass
        except Exception:
            pass

    def grab_frame(self, timeout_ms: int = 2000) -> np.ndarray:
        buffer = self._data_stream.WaitForFinishedBuffer(timeout_ms)
        ipl_img = ipl.Image.CreateFromSizeAndBuffer(
            buffer.PixelFormat(),
            buffer.BasePtr(),
            buffer.Size(),
            buffer.Width(),
            buffer.Height(),
        )
        try:
            converted = ipl_img.ConvertTo(ipl.PixelFormatName_Mono8)
        except Exception:
            converted = ipl_img.ConvertTo(ipl.PixelFormatName_BGRa8)

        arr = converted.get_numpy_1D().reshape(
            buffer.Height(), buffer.Width(), -1).squeeze().copy()
        self._data_stream.QueueBuffer(buffer)
        return arr

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _start_acquisition(self):
        self._data_stream.StartAcquisition()
        self._node_map.FindNode("TLParamsLocked").SetValue(1)
        self._node_map.FindNode("AcquisitionStart").Execute()
        self._node_map.FindNode("AcquisitionStart").WaitUntilDone()
        self._streaming = True

    def _stop_acquisition(self):
        try:
            self._node_map.FindNode("AcquisitionStop").Execute()
            self._node_map.FindNode("AcquisitionStop").WaitUntilDone()
            self._node_map.FindNode("TLParamsLocked").SetValue(0)
            self._data_stream.StopAcquisition()
        except Exception:
            pass
        self._streaming = False

    def _allocate_buffers(self):
        payload_size = self._node_map.FindNode("PayloadSize").Value()
        for _ in range(self._num_buffers):
            buf = self._data_stream.AllocAndAnnounceBuffer(payload_size)
            self._data_stream.QueueBuffer(buf)

    def _revoke_buffers(self):
        try:
            self._data_stream.Flush(ids.DataStreamFlushMode_DiscardAll)
            for buf in self._data_stream.AnnouncedBuffers():
                self._data_stream.RevokeBuffer(buf)
        except Exception:
            pass

    def _close_data_stream(self):
        """Full teardown — call only on camera close."""
        if self._data_stream is None:
            return
        self._revoke_buffers()
        self._data_stream = None
