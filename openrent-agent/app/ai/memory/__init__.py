"""OpenRent ⇄ Hippocampus memory bridge.

This package wraps the @hippocampus/memory-kit MCP stdio server with
OpenRent-shaped helpers (per-message thread ingest, recall-for-reply,
outcome derivation from sim state). It is the only place OpenRent
code should talk to Hippocampus; downstream code imports from here.

The integration is feature-flagged off by default in the simulation
runtime (`RuntimeContext.flags["hippo_memory"]`, default `"off"`).
See docs/OUTREACH-HIPPO-IMPLEMENTATION-PLAN.md in the hippocampus
repo for the §S3 pilot scaffold.
"""

from app.ai.memory.hippo_client import (
    HippoOutreachClient,
    HippoOutreachError,
    OutreachOutcome,
    sim_state_to_outcome,
)

__all__ = [
    "HippoOutreachClient",
    "HippoOutreachError",
    "OutreachOutcome",
    "sim_state_to_outcome",
]
