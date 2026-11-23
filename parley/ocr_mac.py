"""macOS text recognition backend (Apple Vision framework)."""
from __future__ import annotations


def available() -> bool:
    import Vision  # noqa: F401

    return True


def recognize(data: bytes) -> list[str]:
    import Quartz
    import Vision
    from Foundation import NSData

    from .ocr import merge_rows

    source = Quartz.CGImageSourceCreateWithData(NSData.dataWithBytes_length_(data, len(data)), None)
    image = Quartz.CGImageSourceCreateImageAtIndex(source, 0, None) if source else None
    if image is None:
        raise ValueError("The image could not be opened. Try a PNG or JPG file.")
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    request.setRecognitionLanguages_(["en-US"])
    request.setUsesLanguageCorrection_(True)
    handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(image, None)
    ok, error = handler.performRequests_error_([request], None)
    if not ok:
        raise RuntimeError(str(error))
    boxes = []
    for observation in request.results() or []:
        candidates = observation.topCandidates_(1)
        if not candidates:
            continue
        box = observation.boundingBox()  # normalised, origin at bottom-left
        top = 1.0 - (box.origin.y + box.size.height)
        boxes.append((box.origin.x, top, box.size.height, str(candidates[0].string())))
    return merge_rows(boxes)
