import subprocess
import unittest
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[1] / "plugins/ai-native-devkit/skills"


class DeliverySkillTest(unittest.TestCase):
    def test_execute_uses_the_approved_plan_as_a_serial_execution_contract(self):
        text = (SKILLS / "sop-execute/SKILL.md").read_text()
        normalized = " ".join(text.split())
        for token in (
            "approved PlanDoc",
            "ordered vertical slice",
            "public seam",
            "relevant Red",
            "minimal Green",
            "focused test",
            "final checks",
            "candidate commit",
            "Spec",
            "Standards",
            "re-run",
            "ExecutionResult",
        ):
            self.assertIn(token, normalized)
        for forbidden in (
            "TicketGraph",
            "ExecutionLedger",
            "frontier",
            "review after each task",
            "Invoke `$sop-verify`",
            "Invoke `$sop-sync-docs`",
            "Return `TaskOutcome`",
        ):
            self.assertNotIn(forbidden, text)

    def test_execute_keeps_one_baseline_and_one_end_of_plan_review(self):
        text = (SKILLS / "sop-execute/SKILL.md").read_text()
        start = text.index("stage.start")
        baseline = text.index("baseline", start)
        slices = text.index("ordered vertical slice", baseline)
        final_checks = text.index("final checks", slices)
        candidate = text.index("candidate commit", final_checks)
        review = text.index("Spec", candidate)
        complete = text.index("stage.complete", review)
        self.assertLess(start, baseline)
        self.assertLess(baseline, slices)
        self.assertLess(slices, final_checks)
        self.assertLess(final_checks, candidate)
        self.assertLess(candidate, review)
        self.assertLess(review, complete)

    def test_execute_isolates_existing_changes_and_gates_the_candidate(self):
        text = " ".join((SKILLS / "sop-execute/SKILL.md").read_text().split())
        for token in (
            "pre-existing staged",
            "isolated workspace",
            "Do not stash, reset",
            "staged diff contains only",
            "match every applicable Expected",
            "Do not create the candidate commit",
        ):
            self.assertIn(token, text)

    def test_execute_closes_every_started_run_and_stops_downstream_on_failure(self):
        execute = " ".join(
            (SKILLS / "sop-execute/SKILL.md").read_text().split()
        )
        router = " ".join(
            (SKILLS / "coding-sop/SKILL.md").read_text().split()
        )
        for token in (
            "stage.fail",
            "execute.replan_required",
            "execute.final_checks_failed",
            "execute.environment_blocked",
            "status: completed | blocked | failed | replan_required",
        ):
            self.assertIn(token, execute)
        self.assertIn("Do not continue to Verify, Sync Docs, or workflow.finish", router)
        self.assertIn("`ExecutionResult.status` is not `completed`", router)

    def test_sop_debug_is_a_thin_lifecycle_adapter_for_diagnosing_bugs(self):
        wrapper = (SKILLS / "sop-debug/SKILL.md").read_text()
        start = wrapper.index("stage.start")
        delegate = wrapper.index("Invoke `$diagnosing-bugs`")
        complete = wrapper.index("stage.complete", delegate)
        verify = wrapper.index("Invoke `$sop-verify`", complete)

        self.assertLess(start, delegate)
        self.assertLess(delegate, complete)
        self.assertLess(complete, verify)
        self.assertIn("stage.fail", wrapper)
        self.assertIn("TaskOutcome", wrapper)
        self.assertNotIn("reproduce before fixing", wrapper)
        self.assertNotIn("failing regression test", wrapper)

    def test_packaged_diagnosing_bugs_owns_the_debug_method_and_hitl_helper(self):
        method = (SKILLS / "diagnosing-bugs/SKILL.md").read_text()
        helper = SKILLS / "diagnosing-bugs/scripts/hitl-loop.template.sh"

        for token in (
            "Phase 1: Build a feedback loop",
            "No red-capable command, no Phase 2",
            "Phase 2: Reproduce + minimise",
            "Generate **3–5 ranked hypotheses**",
            "Phase 4: Instrument",
            "Phase 5: Fix + regression test",
            "Phase 6: Cleanup",
        ):
            self.assertIn(token, method)
        self.assertTrue(helper.is_file())
        syntax = subprocess.run(
            ["bash", "-n", str(helper)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(syntax.returncode, 0, syntax.stderr)


if __name__ == "__main__":
    unittest.main()
