"""Appearance-rate buckets for the online ranking: a card's share of sampled games decides how often it counts as played."""
from __future__ import annotations

from tools.gundam_meta.models import MsaBucket

# Fixed cutoffs on appearance rate (% of games a card appears in). Expected to be tuned.
BUCKET_CUTOFFS: tuple[tuple[float, MsaBucket], ...] = (
    (10.0, MsaBucket.CORE_META),
    (3.0, MsaBucket.OFTEN_PLAYED),
    (1.0, MsaBucket.PLAYED),
    (0.4, MsaBucket.SOMETIMES_PLAYED),
)


def bucket_for(appearance_rate_pct: float) -> MsaBucket:
    for cutoff, bucket in BUCKET_CUTOFFS:
        if appearance_rate_pct >= cutoff:
            return bucket
    return MsaBucket.NICHE
