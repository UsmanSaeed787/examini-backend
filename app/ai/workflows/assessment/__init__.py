"""Assessment Intelligence workflow.

A stateful, human-in-the-loop pipeline over the AI foundation. Stages are
pluggable handlers (deterministic in v1; specialist agents — Curriculum
Analyst, Assessment Designer, Quality Reviewer, Difficulty Analyzer,
Scheduler — plug in later via stages.AgentStageHandler without touching the
orchestrator).

Question generation is NOT a stage: the planning pipeline ends at COMPLETED
with an approved AssessmentPlan, and `materialization.py` consumes that
result to produce a draft exam the teacher then publishes.
"""
