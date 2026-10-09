"""Appearance-rate buckets."""
from __future__ import annotations

import pytest

from tools.gundam_meta.buckets import bucket_for
from tools.gundam_meta.models import MsaBucket


@pytest.mark.parametrize(
    ("rate", "bucket"),
    [(30.2, MsaBucket.CORE_META), (10.0, MsaBucket.CORE_META), (9.99, MsaBucket.OFTEN_PLAYED), (3.0, MsaBucket.OFTEN_PLAYED), (1.0, MsaBucket.PLAYED),
     (0.4, MsaBucket.SOMETIMES_PLAYED), (0.39, MsaBucket.NICHE), (0.0, MsaBucket.NICHE)],
)
def test_bucket_cutoffs(rate: float, bucket: MsaBucket) -> None:
    assert bucket_for(rate) is bucket
