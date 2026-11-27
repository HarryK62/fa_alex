"""Local checks for the Langfuse v5 instrumentation. No project credentials required."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parent
DEPRECATED = (
    "update_current_trace",
    "set_current_trace_io",
    "set_trace_io",
    "start_as_current_span",
    "start_generation",
    "blocked_instrumentation_scopes",
    "api.trace",
    "api.ingestion",
    "observations_v_2",
    "/api/public/ingestion",
    "/api/public/traces",
)


def load_tracing(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class RecordingRoot:
    def __init__(self, events: list) -> None:
        self.events = events

    def update(self, **kwargs):
        self.events.append(("root-update", kwargs))

    def __enter__(self):
        self.events.append("root-enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("root-exit")
        return False


class RecordingClient:
    def __init__(self, events: list) -> None:
        self.events = events

    def start_as_current_observation(self, **kwargs):
        self.events.append(("start", kwargs))
        return RecordingRoot(self.events)

    def flush(self):
        self.events.append("flush")

    def get_current_trace_id(self):
        return "trace-1"

    def get_current_observation_id(self):
        return "obs-1"

    def create_score(self, **kwargs):
        self.events.append(("score", kwargs))


class Propagate:
    def __init__(self, events: list) -> None:
        self.events = events

    def __enter__(self):
        self.events.append("propagate-enter")
        return self

    def __exit__(self, exc_type, exc, tb):
        self.events.append("propagate-exit")
        return False


class TracingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.modules = {
            "backend": load_tracing("alex_backend_tracing", BACKEND / "tracing.py"),
            "researcher": load_tracing(
                "alex_researcher_tracing", BACKEND / "researcher" / "tracing.py"
            ),
        }

    def test_metadata_mask_round_trips_json_and_leaves_prompts_raw(self):
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                email = "person@example.com"
                params = SimpleNamespace(
                    spans={
                        "span-1": SimpleNamespace(
                            attributes={
                                "langfuse.observation.metadata.feature": json.dumps(
                                    f"planner {email}"
                                ),
                                "langfuse.trace.metadata.contacts": json.dumps(
                                    [email, "ok"]
                                ),
                                "langfuse.observation.metadata.raw": email,
                                "langfuse.observation.metadata.count": json.dumps(5),
                                "gen_ai.prompt.0.content": f"Call me at 415-555-1212 or {email}",
                                "langfuse.observation.metadata.clean": json.dumps("planner"),
                            }
                        )
                    }
                )
                result = tracing.mask_otel_spans(params=params)
                updates = result.span_patches["span-1"].set_attributes
                self.assertEqual(
                    json.loads(updates["langfuse.observation.metadata.feature"]),
                    "planner [REDACTED EMAIL]",
                )
                self.assertEqual(
                    json.loads(updates["langfuse.trace.metadata.contacts"]),
                    ["[REDACTED EMAIL]", "ok"],
                )
                self.assertEqual(
                    json.loads(updates["langfuse.observation.metadata.raw"]),
                    "[REDACTED EMAIL]",
                )
                self.assertNotIn("langfuse.observation.metadata.count", updates)
                self.assertNotIn("langfuse.observation.metadata.clean", updates)
                self.assertEqual(
                    updates["gen_ai.prompt.0.content"],
                    "Call me at [REDACTED PHONE] or [REDACTED EMAIL]",
                )
                self.assertIsNone(
                    tracing.mask_otel_spans(
                        params=SimpleNamespace(
                            spans={
                                "clean": SimpleNamespace(
                                    attributes={
                                        "gen_ai.prompt.0.content": "hello",
                                        "langfuse.observation.metadata.feature": json.dumps(
                                            "planner"
                                        ),
                                    }
                                )
                            }
                        )
                    )
                )

    def test_mask_failure_exports_the_batch_unchanged(self):
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                self.assertIsNone(tracing.mask_otel_spans(params=SimpleNamespace(spans=None)))

    def test_root_is_created_inside_propagated_attributes(self):
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                events: list = []
                client = RecordingClient(events)

                def propagate(**kwargs):
                    events.append(("propagate", kwargs))
                    return Propagate(events)

                tracing._ready = True
                with patch.object(tracing, "setup_tracing", return_value=True):
                    with patch("langfuse.get_client", return_value=client):
                        with patch("langfuse.propagate_attributes", side_effect=propagate):
                            with tracing.observe(
                                trace_name="orchestrate-portfolio-analysis",
                                feature="planner",
                                user_id="user_1",
                                session_id="job_1",
                                input={"job_id": "job_1"},
                                metadata={"job_id": "job_1", "note": "x" * 199},
                                tags=["portfolio-analysis"],
                            ) as span:
                                events.append("body")
                                with tracing.observation(
                                    name="classify-instrument",
                                    as_type="agent",
                                    input={"symbol": "VTI"},
                                ):
                                    events.append("child-body")
                                span.update(output={"status": "completed"})

                propagate_at = events.index("propagate-enter")
                root_at = events.index("root-enter")
                body_at = events.index("body")
                child_at = next(
                    index
                    for index, event in enumerate(events)
                    if isinstance(event, tuple)
                    and event[0] == "start"
                    and event[1]["name"] == "classify-instrument"
                )
                self.assertLess(propagate_at, root_at)
                self.assertLess(root_at, body_at)
                self.assertLess(body_at, child_at)
                self.assertLess(child_at, events.index("propagate-exit"))

                propagated = next(event[1] for event in events if event[0] == "propagate")
                self.assertEqual(propagated["session_id"], "job_1")
                self.assertEqual(propagated["user_id"], "user_1")
                self.assertEqual(propagated["environment"], tracing.tracing_environment())
                self.assertEqual(propagated["trace_name"], "orchestrate-portfolio-analysis")
                self.assertIn("portfolio-analysis", propagated["tags"])
                self.assertEqual(propagated["metadata"]["job_id"], "job_1")
                self.assertNotIn("note", propagated["metadata"])

                root_start = next(
                    event[1]
                    for event in events
                    if isinstance(event, tuple)
                    and event[0] == "start"
                    and event[1]["name"] == "orchestrate-portfolio-analysis"
                )
                self.assertEqual(root_start["as_type"], "agent")
                self.assertEqual(root_start["input"], {"job_id": "job_1"})
                update_at = next(
                    index
                    for index, event in enumerate(events)
                    if isinstance(event, tuple) and event[0] == "root-update"
                )
                self.assertEqual(events[update_at][1], {"output": {"status": "completed"}})
                self.assertLess(update_at, events.index("propagate-exit"))
                self.assertEqual(events[-1], "flush")

    def test_unconfigured_tracing_is_a_noop(self):
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                tracing._ready = False
                with patch.dict(
                    os.environ,
                    {"LANGFUSE_PUBLIC_KEY": "", "LANGFUSE_SECRET_KEY": ""},
                    clear=False,
                ):
                    with tracing.observe(
                        trace_name="orchestrate-portfolio-analysis",
                        feature="planner",
                        session_id="job_1",
                        input={"job_id": "job_1"},
                    ) as span:
                        span.update(output={"status": "completed"})

    def test_evaluation_input_is_self_contained(self):
        reporter = (BACKEND / "reporter" / "lambda_handler.py").read_text(encoding="utf-8")
        self.assertIn("evaluation_input(", reporter)
        self.assertIn('name="evaluate-report"', reporter)
        self.assertIn('as_type="evaluator"', reporter)
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                self.assertEqual(
                    tracing.evaluation_input(
                        job_id="job_1",
                        instructions="Be precise",
                        task="Summarize the portfolio",
                        report="The portfolio is concentrated.",
                    ),
                    {
                        "job_id": "job_1",
                        "instructions": "Be precise",
                        "task": "Summarize the portfolio",
                        "report": "The portfolio is concentrated.",
                    },
                )

    def test_score_uses_the_active_observation(self):
        for name, tracing in self.modules.items():
            with self.subTest(module=name):
                events: list = []
                tracing._ready = True
                with patch("langfuse.get_client", return_value=RecordingClient(events)):
                    tracing.score_current(name="report-quality", value=0.8, comment="ok")
                self.assertEqual(
                    events,
                    [
                        (
                            "score",
                            {
                                "name": "report-quality",
                                "value": 0.8,
                                "trace_id": "trace-1",
                                "observation_id": "obs-1",
                                "data_type": "NUMERIC",
                                "comment": "ok",
                            },
                        )
                    ],
                )

    def test_sources_do_not_call_removed_v4_apis(self):
        roots = [BACKEND, BACKEND / "researcher"]
        offenders = []
        for root in roots:
            for path in root.rglob("*.py"):
                if path.name == "test_tracing.py" or ".venv" in path.parts:
                    continue
                text = path.read_text(encoding="utf-8")
                if "langfuse" not in text and "LANGFUSE" not in text:
                    continue
                for token in DEPRECATED:
                    if token in text:
                        offenders.append(f"{path.relative_to(BACKEND)}:{token}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
