"""Platform media dimensions, kept here so spec changes never touch the workflow."""

from dataclasses import dataclass


@dataclass(frozen=True)
class MediaSpec:
    width: int
    height: int
    safe_margin: int


# 4:5 portrait works in both the Instagram and Facebook feeds, so one image set serves both.
CAROUSEL_SPEC = MediaSpec(width=1080, height=1350, safe_margin=80)
