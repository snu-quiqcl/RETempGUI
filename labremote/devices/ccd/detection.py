"""Image analysis independent of Qt and display visibility."""
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class DetectionConfig:
    threshold: float = 1000
    min_area: float = 3
    target: int = 1
    roi: tuple | None = None  # x1, y1, x2, y2; native sensor coordinates

    def validate(self, shape):
        if not math.isfinite(self.threshold) or not 0 <= self.threshold <= 65535:
            raise ValueError('Threshold must be between 0 and 65535')
        if not math.isfinite(self.min_area) or self.min_area < 0:
            raise ValueError('Minimum contour area must be nonnegative')
        positive_int(self.target, 'Target')
        if self.roi is not None:
            if len(self.roi) != 4 or any(type(v) is not int for v in self.roi):
                raise ValueError('ROI requires four integers: x1, y1, x2, y2')
            x1, y1, x2, y2 = self.roi
            h, w = shape
            if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                raise ValueError('ROI must be nonempty and inside the sensor')
        return self


def positive_int(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(label + ' must be a positive integer')
    return value


def positive_seconds(value):
    if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
        raise ValueError('Timeout must be finite and positive')
    return float(value)


def crop(image, roi):
    if roi is None:
        return image
    x1, y1, x2, y2 = roi
    return image[y1:y2, x1:x2]


def detect_ions(image, config):
    """Preserve legacy threshold + RETR_EXTERNAL + contourArea >= 3 semantics.

    Count means bright connected regions, not a calibrated ion classifier.
    Return centroids instead of shipping all contour points to the UI.
    """
    import cv2
    config.validate(image.shape)
    mask = np.asarray(crop(image, config.roi) > config.threshold, dtype=np.uint8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    offset = config.roi[:2] if config.roi else (0, 0)
    centers = []
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < config.min_area or len(contour) < 3:
            continue
        moments = cv2.moments(contour)
        if moments['m00']:
            centers.append((moments['m10']/moments['m00'] + offset[0],
                            moments['m01']/moments['m00'] + offset[1]))
    return {'count': len(centers), 'matched': len(centers) >= config.target,
            'centers': centers, 'target': config.target}
