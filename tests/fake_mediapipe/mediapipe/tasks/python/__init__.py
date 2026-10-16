import types

NS = types.SimpleNamespace


def BaseOptions(**kw):  # noqa: N802
    return NS(**kw)


def lm(x, y):
    return NS(x=x, y=y, z=0.0)


class _Landmarker:
    kind = ""

    @classmethod
    def create_from_options(cls, options):
        return cls()

    def detect_for_video(self, image, ts):
        t = ts / 1000.0
        if self.kind == "hand":
            marks = [lm(0.1 + 0.1 * t, 0.5) for _ in range(21)]
            marks[8] = lm(0.1 + 0.1 * t, 0.42)
            return NS(hand_landmarks=[marks], handedness=[[NS(category_name="Right", score=0.9)]])
        return NS(detections=[NS(bounding_box=NS(origin_x=100, origin_y=80, width=120, height=140),
                                 categories=[NS(score=0.9)])])

    def close(self):
        pass


class HandLandmarker(_Landmarker):
    kind = "hand"


class FaceDetector(_Landmarker):
    kind = "face"


class PoseLandmarker(_Landmarker):
    kind = "pose"


vision = NS(RunningMode=NS(VIDEO="VIDEO"), HandLandmarker=HandLandmarker, FaceDetector=FaceDetector,
            PoseLandmarker=PoseLandmarker, HandLandmarkerOptions=lambda **kw: NS(**kw),
            FaceDetectorOptions=lambda **kw: NS(**kw), PoseLandmarkerOptions=lambda **kw: NS(**kw))
