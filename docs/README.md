# Documentation Index

Read order for the refactored project:

1. `project_status_and_roadmap.md` - active source of truth: what is done, how to play, current risks, and next priorities.
2. `cv_shadow_dtw_v2_plan.md` - future gesture-classification evaluation plan after real CV Training logs exist.
3. `next_optimization_plan.md` - current implementation plan for measurable CV evaluation, cyclic DTW, and decoupled server delivery.
4. `wand_tracking_code_optimization.md` - bright-marker wand stabilization notes.

Archived files are kept only for provenance. Do not use archived plans as current implementation guidance unless the current brief explicitly reactivates them.

Current rule for new agents:

- keep gameplay scope stable
- keep character selection and buffs lightweight until real art assets exist
- follow `next_optimization_plan.md` for the active optimization scope
- measure CV changes on versioned data before changing live classification
- keep CV inference local and battle resolution server-authoritative
- decouple server ticks from bounded per-connection delivery
- do not reintroduce plain wand / unmarked pen-tip detection
