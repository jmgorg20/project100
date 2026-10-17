"""A stand-in for the `mediapipe` package, for tests that run the engine as a separate process
(put this folder on PYTHONPATH). It "finds" a right hand that moves slowly across the frame
(0.1 + 0.1 per second) and a face in the middle; nothing is detected for real."""

import types

__version__ = "0.0-test-stand-in"
ImageFormat = types.SimpleNamespace(SRGB="SRGB")


def Image(image_format, data):  # noqa: N802
    return types.SimpleNamespace(shape=data.shape, data=data)
