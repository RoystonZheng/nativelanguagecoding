import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins/ai-native-devkit/skills"
EXPECTED = {
    "coding-sop", "sop-init", "sop-clarify", "sop-design", "sop-plan",
    "sop-execute", "sop-debug", "sop-verify", "sop-sync-docs",
}

UPSTREAM_LINES = (
    "Check out the current project state first (files, docs, recent commits)",
    "Before asking detailed questions, assess scope: if the request describes multiple independent subsystems (e.g., \"build a platform with chat, file storage, billing, and analytics\"), flag this immediately. Don't spend questions refining details of a project that needs to be decomposed first.",
    "For appropriately-scoped projects, ask questions one at a time to refine the idea",
    "Prefer multiple choice questions when possible, but open-ended is fine too",
    "Only one question per message - if a topic needs more exploration, break it into multiple questions",
    "Focus on understanding: purpose, constraints, success criteria",
)
ADAPTED_DECOMPOSITION = (
    "If the project is too large for a single requirements document, help the user "
    "decompose into sub-projects: what are the independent pieces, how do they relate, "
    "what order should they be built? Then clarify the first sub-project through this "
    "requirement-understanding flow. Each sub-project gets its own requirements → design "
    "→ plan → implementation cycle."
)
DESIGN_UPSTREAM_LINES = (
    "Propose 2-3 different approaches with trade-offs",
    "Present options conversationally with your recommendation and reasoning",
    "Lead with your recommended option and explain why",
    "YAGNI ruthlessly - remove unnecessary features from every approach and design",
    "Once you believe you understand what you're building, present the design",
    "Scale each section to its complexity: a few sentences if straightforward, up to 200-300 words if nuanced",
    "Ask after each section whether it looks right so far",
    "Cover: architecture, components, data flow, error handling, testing",
    "Be ready to go back and clarify if something doesn't make sense",
    "Break the system into smaller units that each have one clear purpose, communicate through well-defined interfaces, and can be understood and tested independently",
    "For each unit, you should be able to answer: what does it do, how do you use it, and what does it depend on?",
    "Can someone understand what a unit does without reading its internals? Can you change the internals without breaking consumers? If not, the boundaries need work.",
    "Smaller, well-bounded units are also easier for you to work with - you reason better about code you can hold in context at once, and your edits are more reliable when files are focused. When a file grows large, that's often a signal that it's doing too much.",
    "Explore the current structure before proposing changes. Follow existing patterns.",
    "Where existing code has problems that affect the work (e.g., a file that's grown too large, unclear boundaries, tangled responsibilities), include targeted improvements as part of the design - the way a good developer improves code they're working in.",
    "Don't propose unrelated refactoring. Stay focused on what serves the current goal.",
)


class SkillContractTest(unittest.TestCase):
    def test_every_skill_routes_document_language_to_the_chinese_default(self):
        rule = SKILLS / "coding-sop/references/output-language.md"
        text = rule.read_text()
        self.assertIn("默认使用简体中文", text)
        self.assertIn("用户明确指定输出语言时，以用户要求为准", text)
        self.assertIn("保持代码标识符、命令、文件路径、URL、JSON 字段", text)
        for skill in SKILLS.glob("*/SKILL.md"):
            with self.subTest(skill=skill):
                match = re.search(r"\[output-language.md\]\(([^)]+)\)", skill.read_text())
                self.assertIsNotNone(match)
                self.assertEqual((skill.parent / match.group(1)).resolve(), rule.resolve())
        plan = (SKILLS / "sop-plan/SKILL.md").read_text()
        for heading in ("## 目标", "## 设计约束", "## 验收覆盖", "## 任务 1：", "## 最终集成验证"):
            self.assertIn(heading, plan)

    def test_existing_skills_have_matching_frontmatter_names(self):
        for path in SKILLS.glob("*/SKILL.md"):
            text = path.read_text()
            match = re.search(r"^name:\s*([^\n]+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, path)
            name = match.group(1).strip()
            self.assertEqual(name, path.parent.name)

    def test_router_skill_exists(self):
        self.assertTrue((SKILLS / "coding-sop/SKILL.md").is_file())

    def test_router_relies_on_automatic_trace_and_validated_runtime_events(self):
        router = (SKILLS / "coding-sop/SKILL.md").read_text()
        trace_contract = (
            SKILLS / "coding-sop/references/execution-trace.md"
        ).read_text()
        self.assertIn("Collector Hook is a no-op before that activation", router)
        self.assertIn("Codex lifecycle events automatically", router)
        self.assertIn("runtime_cli.py", router)
        self.assertIn("Do not ask the user or invoke a logging command", router)
        self.assertIn("not add a route-status preamble", router)
        self.assertIn("out of order", router)
        self.assertNotIn("State intent, tier, route", router)
        self.assertIn("Agent does not start, update, finish", trace_contract)
        self.assertIn("session_id 1 : 1 trace_id", trace_contract)
        for field in (
            "trace_id",
            "seq",
            "event_id",
            "timestamp",
            "event_type",
            "stage",
            "actor",
            "source",
            "correlation",
            "payload",
        ):
            self.assertIn(field, trace_contract)
        self.assertNotIn("expected_route", trace_contract)
        self.assertNotIn("hook_should_trigger", trace_contract)

    def test_stage_and_approval_boundaries_use_typed_runtime_operations(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        plan = (SKILLS / "sop-plan/SKILL.md").read_text()
        for text, stage, approval_kind in (
            (design, "design", "design.solution"),
            (plan, "plan", "plan.implementation"),
        ):
            self.assertIn("stage.start", text)
            self.assertIn("approval.request", text)
            self.assertIn("approval.resolve", text)
            self.assertIn("stage.complete", text)
            self.assertIn(f"stage: {stage}", text)
            self.assertIn(approval_kind, text)
        for name in ("sop-execute", "sop-debug", "sop-verify", "sop-sync-docs"):
            text = (SKILLS / name / "SKILL.md").read_text()
            self.assertIn("stage.start", text, name)
            self.assertIn("stage_run_id", text, name)

    def test_design_plan_execute_use_one_digest_bound_document_chain(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        plan = (SKILLS / "sop-plan/SKILL.md").read_text()
        execute = (SKILLS / "sop-execute/SKILL.md").read_text()
        router = (SKILLS / "coding-sop/SKILL.md").read_text()

        for text in (design, plan):
            normalized = " ".join(text.split())
            self.assertIn("sha256:<64 lowercase hex>", normalized)
            self.assertIn("pass the same `subject` again", normalized)
        self.assertIn("exact complete Markdown", design)
        self.assertIn("exact complete PlanDoc Markdown", plan)
        self.assertIn('"kind":"design_document"', design)
        self.assertIn("source_subject_digest", plan)
        self.assertIn("approved DesignDoc digest", plan)
        self.assertIn('"kind":"plan_document"', plan)
        self.assertIn("source_subject_digest", execute)
        self.assertIn("approved PlanDoc digest", execute)
        self.assertIn("ExecutionResult", execute)
        self.assertIn("Execute -> Verify -> Sync Docs", router)
        self.assertIn("not document storage or a resume cursor", router)

    def test_verify_uses_runtime_triggered_docs_hook(self):
        verify = (SKILLS / "sop-verify/SKILL.md").read_text()
        execute = (SKILLS / "sop-execute/SKILL.md").read_text()
        debug = (SKILLS / "sop-debug/SKILL.md").read_text()
        self.assertIn("verification.complete", verify)
        self.assertIn("automatically triggers the Docs Hook", verify)
        self.assertIn("NO_CHANGE", verify)
        self.assertNotIn("askHandoff", verify)
        self.assertNotIn("Handoff question", verify)
        self.assertNotIn("$sop-verify", execute)
        self.assertNotIn("Docs Hook", execute)
        self.assertNotIn("$sop-sync-docs", execute)
        self.assertIn("automatic Docs Hook result", debug)
        self.assertIn("do not run a", debug)
        router = (SKILLS / "coding-sop/SKILL.md").read_text()
        self.assertIn("Execute -> Verify -> Sync Docs", router)

    def test_retired_handoff_is_not_discoverable_or_recommended(self):
        self.assertFalse((SKILLS / "sop-handoff").exists())
        for path in SKILLS.rglob("*.md"):
            with self.subTest(path=path):
                text = path.read_text()
                self.assertNotIn("$sop-handoff", text)
                self.assertNotIn("handoffDetected", text)
                self.assertNotIn("handoffMigrationSuggested", text)
        for name in ("sop-init/SKILL.md", "sop-init/references/init-contract.md"):
            text = (SKILLS / name).read_text()
            self.assertIn("Human-facing Handoff documents are outside plugin scope", text)
            self.assertIn("create, migrate, update, or ask about them", text)

    def test_init_contract(self):
        text = (SKILLS / "sop-init/SKILL.md").read_text()
        required = {
            "Bootstrap", "Adapt", "Refresh", "InitReport",
            "preflight_docs_scan.py", "check_managed_docs.py",
            "validate_project_docs.py",
            "OUTDATED_UNMODIFIED", "LOCAL_MODIFIED",
            "Human-facing Handoff documents are outside plugin scope",
        }
        for token in required:
            self.assertIn(token, text)
        self.assertIn("Do not write managed docs before the preview", text)
        for token in (
            "recognized",
            "generated",
            "overwritten",
            "preserved",
            "conflicting",
            "Do not rescan, summarize",
        ):
            self.assertIn(token, text)
        self.assertLess(text.index("preflight_docs_scan.py"), text.index("Inventory"))
        self.assertLess(text.index("preflight_docs_scan.py"), text.index("init_cli.py"))

    def test_init_refreshes_context_after_approved_docs_writes(self):
        skill = (SKILLS / "sop-init/SKILL.md").read_text()
        for token in (
            "post-write Workflow Task",
            "choice: new",
            "do not hand the original",
        ):
            self.assertIn(token, skill)

    def test_init_implicit_identity_collision_is_initial_only(self):
        for path in (
            SKILLS / "sop-init/SKILL.md",
            SKILLS / "sop-init/references/init-contract.md",
        ):
            text = " ".join(path.read_text().split())
            for token in (
                "For an initial request only",
                "CODEX_THREAD_ID",
                "CODEX_TASK_ID",
                "fresh Workflow Task",
                "without rebinding or mutating the existing task",
                "Any supplied `task_id`, `choice`, `authority_grant`, or `instruction_selection` is a strict continuation",
                "init.task_target_mismatch",
            ):
                self.assertIn(token, text, f"{path}: {token}")

    def test_init_write_preview_requires_a_later_user_turn(self):
        paths = (
            SKILLS / "sop-init/SKILL.md",
            SKILLS / "sop-init/references/init-contract.md",
        )
        required = {
            "stop the current assistant turn",
            "a later user message",
            "the exact preview",
            "the same turn",
            "The original development request is not approval",
        }
        for path in paths:
            raw = path.read_text()
            section_start = (
                "## Phase 2: project docs preparation"
                if path.name == "SKILL.md"
                else "## Workflow contract"
            )
            text = " ".join(raw.split(section_start, 1)[1].split())
            for token in required:
                self.assertIn(token, text, f"{path}: {token}")
            preview = text.index("the exact preview")
            stop = text.index("stop the current assistant turn", preview)
            later = text.index("a later user message", stop)
            apply = text.index("Apply approved changes", later)
            self.assertLess(preview, stop, path)
            self.assertLess(stop, later, path)
            self.assertLess(later, apply, path)

    def test_init_choice_and_authority_require_a_later_user_turn(self):
        paths = (
            SKILLS / "sop-init/SKILL.md",
            SKILLS / "sop-init/references/init-contract.md",
        )
        for path in paths:
            raw = path.read_text()
            if path.name == "SKILL.md":
                phase = raw.split("## Phase 1: persisted context inspection", 1)[1]
                phase = phase.split("## Phase 2: project docs preparation", 1)[0]
                choice_text, authority_text = phase.split(
                    "5. A later authority grant", 1
                )
            else:
                phase = raw.split("For an initial request only", 1)[1]
                phase = phase.split("## Modes", 1)[0]
                choice_text, authority_text = phase.split(
                    "For a latest `blocked.repository.read_authority`", 1
                )
            choice_text = " ".join(choice_text.split())
            authority_text = " ".join(authority_text.split())
            choice = choice_text.index("choice_required")
            choice_stop = choice_text.index("stop the current assistant turn", choice)
            choice_later = choice_text.index("a later user message", choice_stop)
            authority = authority_text.index("Present the exact capability and scope")
            authority_stop = authority_text.index(
                "stop the current assistant turn", authority
            )
            authority_later = authority_text.index(
                "a later user message", authority_stop
            )
            self.assertLess(choice, choice_stop, path)
            self.assertLess(choice_stop, choice_later, path)
            self.assertIn("same turn", choice_text, path)
            self.assertLess(authority, authority_stop, path)
            self.assertLess(authority_stop, authority_later, path)
            self.assertIn("same turn", authority_text, path)
            self.assertIn(
                "The original development request is not approval",
                authority_text,
                path,
            )

    def test_init_omits_new_docs_root_readme_but_preserves_existing_content(self):
        skill = (SKILLS / "sop-init/SKILL.md").read_text()
        contract = (SKILLS / "sop-init/references/init-contract.md").read_text()
        for text in (skill, contract):
            self.assertIn("Bootstrap does not create `docs/README.md`", text)
            self.assertIn("Preserve an existing `docs/README.md`", text)
            self.assertIn("migration preview", text)

    def test_docs_sync_routes_through_project_and_child_indexes(self):
        text = (SKILLS / "sop-sync-docs/SKILL.md").read_text()
        self.assertIn("project entry", text)
        self.assertIn("relevant child", text)
        self.assertNotIn("and `docs/README.md`", text)
        self.assertIn("When `docs/README.md` exists", text)
        self.assertNotIn("only when the project entry routes", text)

    def test_clarify_reuses_only_the_upstream_requirement_understanding_behavior(self):
        clarify = (SKILLS / "sop-clarify/SKILL.md").read_text()
        for line in UPSTREAM_LINES:
            self.assertIn(line, clarify)
        self.assertIn(ADAPTED_DECOMPOSITION, clarify)
        for token in (
            "requirements.write", "clarify.requirements", "RequirementDocRef",
            "approval.resolve", "stage.complete", "purpose: clarify_revision",
            "supersedes", "stop the current assistant turn",
            "a later user-authored response",
            "[upstream-superpowers-brainstorming.md](references/upstream-superpowers-brainstorming.md)",
        ):
            self.assertIn(token, clarify)
        for forbidden in (
            "clarification.checkpoint", "ClarificationResult",
            "Three Paths", "approach exploration", "solution design",
            "spec authoring", "implementation planning",
        ):
            self.assertNotIn(forbidden, clarify)
        self.assertIn(
            "Never invoke `superpowers:brainstorming` at runtime.", clarify
        )
        self.assertIn(
            "Do not create a checkpoint,\nstructured baseline", clarify
        )
        self.assertNotIn(
            "REQUIRED SUB-SKILL: Use superpowers:brainstorming", clarify
        )
        self.assertLess(clarify.index("Check out the current project state first"),
                        clarify.index("ask questions one at a time"))
        self.assertLess(clarify.index("requirements.write"),
                        clarify.index("approval.request"))
        approval = clarify.split(
            "## Request and resolve exact approval", 1
        )[1].split("## Explicit revision and drift entry modes", 1)[0]
        request = approval.index("approval.request")
        stop = approval.index("stop the current assistant turn", request)
        later = approval.index("a later user-authored response", stop)
        resolve = approval.index("approval.resolve", later)
        complete = approval.index("stage.complete", resolve)
        self.assertLess(request, stop)
        self.assertLess(stop, later)
        self.assertLess(later, resolve)
        self.assertLess(resolve, complete)

    def test_design_loads_exact_approval_before_design_and_reports_drift(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        for token in (
            "RequirementDocRef", "requirements.load", "purpose: design",
            "requirements.source_drift",
            "requirements.document_worktree_drift", "requirements.document_index_drift",
            "requirements.document_committed_drift", "requirements.document_missing",
            "changed", "unavailable",
            "version_uncomparable", "worktree", "index", "committed", "missing",
            ".scratch/ai-native-devkit/tasks/requirement-<64-hex>/design.md",
            "refuse to overwrite", "full RequirementDocRef",
        ):
            self.assertIn(token, design)
        for forbidden in ("task_id", "ClarificationResult", "clarification_ref"):
            self.assertNotIn(forbidden, design)
        load_section = design.split(
            "## Load the only design input", 1
        )[1].split("## Design and approve the solution", 1)[0]
        load = load_section.index(
            "Call `requirements.load` with `purpose: design`"
        )
        current = load_section.index(
            "Only after the exact approved Markdown", load
        )
        start = load_section.index(
            "`stage.start` with `stage: design`", current
        )
        self.assertLess(load, current)
        self.assertLess(current, start)

    def test_design_reports_drift_without_automatically_entering_clarify(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        drift = design.split("Map Loader failures before Design starts:", 1)[1].split(
            "Only after the exact approved Markdown", 1
        )[0]
        normalized = " ".join(drift.split())
        for token in (
            "exact input `reference`",
            "drifted path or source",
            "recorded state",
            "current state",
            "bounded difference",
            "recommended next steps",
            "wait for explicit user direction",
            "Do not automatically start or enter Clarify",
        ):
            self.assertIn(token, normalized)
        for forbidden in (
            "returns to fresh Clarify",
            "returns to Clarify",
            "stage.start(clarify",
            "purpose: clarify_revision",
        ):
            self.assertNotIn(forbidden, normalized)

    def test_design_reuses_upstream_solution_design_wording(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        for line in DESIGN_UPSTREAM_LINES:
            self.assertIn(line, design)
        self.assertIn(
            "[upstream-superpowers-brainstorming.md]"
            "(references/upstream-superpowers-brainstorming.md)",
            design,
        )
        for forbidden in (
            "Three Paths", "Spec Self-Review", "writing-plans", "Visual Companion"
        ):
            self.assertNotIn(forbidden, design)

    def test_design_keeps_section_feedback_before_one_final_runtime_approval(self):
        design = " ".join(
            (SKILLS / "sop-design/SKILL.md").read_text().split()
        )
        start = design.index("`stage.start` with `stage: design`")
        approaches = design.index("### Exploring approaches", start)
        check_ins = design.index(
            "Section check-ins are conversational feedback", approaches
        )
        request = design.index("approval.request", check_ins)
        stop = design.index("stop the current assistant turn", request)
        later = design.index("On the later user response", stop)
        resolve = design.index("approval.resolve", later)
        complete = design.index("stage.complete", resolve)
        self.assertLess(start, approaches)
        self.assertLess(approaches, check_ins)
        self.assertLess(check_ins, request)
        self.assertLess(request, stop)
        self.assertLess(stop, later)
        self.assertLess(later, resolve)
        self.assertLess(resolve, complete)

    def test_router_waits_for_direction_after_design_input_drift(self):
        paths = (
            SKILLS / "coding-sop/SKILL.md",
            SKILLS / "coding-sop/references/workflow-contract.md",
            SKILLS / "coding-sop/references/execution-trace.md",
        )
        for path in paths:
            text = " ".join(path.read_text().split())
            self.assertIn("bounded drift details and recommendations", text, path)
            self.assertIn("wait for explicit user direction", text, path)
            self.assertNotIn(
                "requirements_source_drift -> stage.start(clarify)", text, path
            )
            self.assertNotIn(
                "requirements_document_drift -> stage.start(clarify", text, path
            )

    def test_router_and_docs_sync_use_the_exact_normal_handoff_sequence(self):
        router = (SKILLS / "coding-sop/SKILL.md").read_text()
        sync = (SKILLS / "sop-sync-docs/SKILL.md").read_text()
        for token in (
            "stage.start(clarify)", "stage.complete(clarify, exact subject)",
            "requirements.load(purpose: design)",
        ):
            self.assertIn(token, router)
        self.assertLess(router.index("stage.complete(clarify, exact subject)"),
                        router.index("requirements.load(purpose: design)"))
        self.assertLess(router.index("requirements.load(purpose: design)"),
                        router.index("stage.start(design)"))
        self.assertIn("stage.start", sync)
        self.assertIn("stage: sync-docs", sync)
        self.assertIn("requirements.load", sync)
        self.assertIn("purpose: docs_promotion", sync)
        self.assertIn("exact approved RequirementDocRef", sync)
        self.assertLess(sync.index("stage.start"), sync.index("purpose: docs_promotion"))

    def test_packaged_provenance_is_linked_and_independent(self):
        clarify = (SKILLS / "sop-clarify/SKILL.md").read_text()
        clarify_provenance = (
            SKILLS / "sop-clarify/references/upstream-superpowers-brainstorming.md"
        ).read_text()
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        design_provenance = (
            SKILLS / "sop-design/references/upstream-superpowers-brainstorming.md"
        ).read_text()
        plan = (SKILLS / "sop-plan/SKILL.md").read_text()
        plan_provenance = (
            SKILLS / "sop-plan/references/upstream-matt-to-tickets.md"
        ).read_text()
        execute = (SKILLS / "sop-execute/SKILL.md").read_text()
        execute_provenance = (
            SKILLS / "sop-execute/references/upstream-matt-stable-execution.md"
        ).read_text()
        debug = (SKILLS / "sop-debug/SKILL.md").read_text()
        diagnosing = (SKILLS / "diagnosing-bugs/SKILL.md").read_text()
        diagnosing_provenance = (
            SKILLS
            / "diagnosing-bugs/references/upstream-matt-diagnosing-bugs.md"
        ).read_text()
        repository_notice = (ROOT / "THIRD_PARTY_NOTICES.md").read_text()
        packaged_notice = (
            ROOT / "plugins/ai-native-devkit/THIRD_PARTY_NOTICES.md"
        ).read_text()
        self.assertIn("references/upstream-superpowers-brainstorming.md", clarify)
        for token in (
            "obra/superpowers", "superpowers@6.3.0",
            "skills/brainstorming/SKILL.md", "Understanding the idea",
            "MIT", "Jesse Vincent",
        ):
            self.assertIn(token, clarify_provenance)
        self.assertIn("references/upstream-superpowers-brainstorming.md", design)
        for token in (
            "obra/superpowers", "superpowers@6.3.0",
            "skills/brainstorming/SKILL.md", "Exploring approaches",
            "Presenting the design", "Design for isolation and clarity",
            "Working in existing codebases", "MIT", "Jesse Vincent",
        ):
            self.assertIn(token, design_provenance)
        self.assertIn(
            "Never invoke `superpowers:brainstorming` at runtime.", clarify
        )
        self.assertNotIn(
            "REQUIRED SUB-SKILL: Use superpowers:brainstorming", clarify
        )
        self.assertIn("references/upstream-matt-to-tickets.md", plan)
        self.assertIn("references/upstream-matt-stable-execution.md", execute)
        for provenance in (
            plan_provenance,
            execute_provenance,
            diagnosing_provenance,
        ):
            for token in (
                "mattpocock/skills",
                "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76",
                "MIT",
                "Matt Pocock",
                "does not invoke or require",
            ):
                self.assertIn(token, provenance)
        self.assertIn("Invoke `$diagnosing-bugs`", debug)
        for token in (
            "skills/engineering/diagnosing-bugs/SKILL.md",
            "skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh",
            "No Matt",
        ):
            self.assertIn(token, diagnosing_provenance)
        for forbidden in ("npx skills", "github.com/mattpocock"):
            self.assertNotIn(forbidden, diagnosing)
        for token in (
            "skills/engineering/to-tickets/SKILL.md",
            "tracer-bullet",
        ):
            self.assertIn(token, plan_provenance)
        for token in (
            "skills/engineering/implement/SKILL.md",
            "skills/engineering/tdd/SKILL.md",
            "skills/engineering/code-review/SKILL.md",
            "Spec",
            "Standards",
        ):
            self.assertIn(token, execute_provenance)
        for skill in (plan, execute):
            for forbidden in ("/tdd", "/code-review", "npx skills"):
                self.assertNotIn(forbidden, skill)
        self.assertEqual(repository_notice, packaged_notice)
        for token in (
            "superpowers@6.3.0",
            "skills/brainstorming/SKILL.md",
            "Understanding the idea",
            "Exploring approaches",
            "Presenting the design",
            "Design for isolation and clarity",
            "Working in existing codebases",
            "6654f6b60cd9d5be8b54c6fafe44346dabeb3b76",
            "skills/engineering/to-tickets/SKILL.md",
            "skills/engineering/implement/SKILL.md",
            "skills/engineering/tdd/SKILL.md",
            "skills/engineering/code-review/SKILL.md",
            "skills/engineering/diagnosing-bugs/SKILL.md",
            "skills/engineering/diagnosing-bugs/scripts/hitl-loop.template.sh",
        ):
            self.assertIn(token, repository_notice)

    def test_current_docs_describe_implemented_exact_requirement_handoff(self):
        contracts = (ROOT / "docs/contracts.md").read_text(encoding="utf-8")
        workflow = (ROOT / "docs/workflow.md").read_text(encoding="utf-8")
        context = (ROOT / "docs/context-and-docs.md").read_text(encoding="utf-8")
        combined = "\n".join((contracts, workflow, context))
        for token in (
            "Current 0.4.0", "RequirementDocRef",
            "path", "commit", "blob_digest", "clarify.requirements",
            "later user-authored", "same repository", "exact subject",
            "versioned workflow records", "not canonical CurrentState",
        ):
            self.assertIn(token, combined)

        current_surfaces = {
            ROOT / "AGENTS.md": (
                "Current 0.4.0 implements",
                "checkpoint/result clarification flow is Historical",
            ),
            ROOT / "README.md": (
                "Current 0.4.0",
                "0.4.0 implemented",
            ),
            ROOT / "plugins/ai-native-devkit/README.md": (
                "Current 0.4.0",
                "## 0.4.0 版本边界",
            ),
            ROOT / "docs/README.md": (
                "Current 0.4.0 implements",
                "0.4.0 implemented",
            ),
            ROOT / "docs/product-and-scope.md": (
                "Current 0.4.0",
                "Historical clarification",
            ),
            ROOT / "docs/方案总览.md": (
                "Current 0.4.0",
                "Historical clarification",
            ),
            ROOT / "docs/architecture.md": (
                "Current 0.4.0 Clarify/Design boundary",
                "Historical clarification persistence",
            ),
            ROOT / "docs/contracts.md": (
                "Current 0.4.0 requirement handoff",
                "Historical ClarificationCheckpoint and ClarificationResult",
            ),
            ROOT / "docs/workflow.md": (
                "Current 0.4.0 Clarify handoff",
                "Historical 0.2/0.2.3 clarification flow",
            ),
            ROOT / "docs/context-and-docs.md": (
                "Current 0.4.0 requirement workflow records",
                "not canonical CurrentState",
            ),
            ROOT / "docs/roadmap-and-validation.md": (
                "Current 0.4.0 outcome",
                "0.4.0 verification evidence",
                "defined by ADR 0006",
            ),
            ROOT / "docs/skill-selection.md": (
                "Current 0.4.0. Inspect project state",
                "Current 0.4.0 input rule",
            ),
            ROOT / "docs/evaluation-evidence.md": (
                "implemented and verified in 0.4.0",
                "This does not alter the recorded measurement",
            ),
            ROOT / "docs/decisions/0002-task-artifacts-and-doc-promotion.md": (
                "Clarification supersession (2026-08-27)",
                "remaining TaskStateStore and canonical-doc promotion rules stay accepted",
            ),
            ROOT / "docs/decisions/0004-task-state-store-interface.md": (
                "Clarification supersession (2026-08-27)",
                "continues to govern the remaining persisted task contracts",
            ),
            ROOT / "docs/decisions/0005-persist-and-promote-clarification-results.md": (
                "Status: Superseded by ADR 0006",
            ),
            ROOT / "docs/decisions/0006-git-versioned-requirements-handoff.md": (
                "Status: Accepted",
                "workflow records, not CurrentState docs",
            ),
            ROOT / "docs/decisions/README.md": (
                "Superseded by ADR 0006",
                "Implemented in 0.4.0",
            ),
            ROOT / "docs/superpowers/README.md": (
                "Implemented in 0.4.0",
            ),
        }
        for path, expected_tokens in current_surfaces.items():
            with self.subTest(current_surface=path):
                text = path.read_text(encoding="utf-8")
                normalized = " ".join(text.split())
                for token in expected_tokens:
                    self.assertIn(token, normalized)

        for path in current_surfaces:
            normalized = " ".join(path.read_text(encoding="utf-8").split())
            self.assertNotIn("validation pending", normalized, path)
            self.assertNotIn("Candidate 0.4.0", normalized, path)

    def test_current_design_docs_report_drift_and_wait_for_user_direction(self):
        paths = (
            ROOT / "docs/workflow.md",
            ROOT / "docs/skill-selection.md",
            ROOT / "docs/decisions/0006-git-versioned-requirements-handoff.md",
        )
        for path in paths:
            normalized = " ".join(path.read_text(encoding="utf-8").split())
            self.assertIn("bounded read-only", normalized, path)
            self.assertIn("explicit user direction", normalized, path)
            self.assertNotIn("returns to Clarify when comparison fails", normalized, path)
            self.assertNotIn("drift to Clarify before Design starts", normalized, path)

        skill_selection = paths[1].read_text(encoding="utf-8")
        for section in (
            "Exploring approaches",
            "Presenting the design",
            "Design for isolation and clarity",
            "Working in existing codebases",
        ):
            self.assertIn(section, skill_selection)
        workflow = paths[0].read_text(encoding="utf-8")
        self.assertIn("one final `design.solution` approval", workflow)

    def test_current_plugin_readme_does_not_claim_open_question_persistence(self):
        readme = (
            ROOT / "plugins/ai-native-devkit/README.md"
        ).read_text(encoding="utf-8")
        current_boundary = readme.split("## 文档边界", 1)[1].split(
            "## 本地开发更新", 1
        )[0]
        self.assertNotIn("开放问题", current_boundary)
        self.assertNotIn(
            "私有任务状态、开放问题、证据和结果写入仓库外 TaskStateStore",
            current_boundary,
        )
        self.assertIn(
            "受支持的任务请求、状态转换、Init 报告和证据写入仓库外 TaskStateStore",
            current_boundary,
        )
        historical = (ROOT / "docs/contracts.md").read_text(encoding="utf-8").split(
            "## Historical ClarificationCheckpoint and ClarificationResult", 1
        )[1]
        self.assertIn("open_questions: []", historical)

    def test_current_docs_do_not_restore_removed_clarification_persistence(self):
        context = (ROOT / "docs/context-and-docs.md").read_text(encoding="utf-8")
        overview = (ROOT / "docs/方案总览.md").read_text(encoding="utf-8")
        architecture = (ROOT / "docs/architecture.md").read_text(encoding="utf-8")
        contracts = (ROOT / "docs/contracts.md").read_text(encoding="utf-8")
        workflow = (ROOT / "docs/workflow.md").read_text(encoding="utf-8")
        docs_index = (ROOT / "docs/README.md").read_text(encoding="utf-8")
        evaluation = (ROOT / "docs/evaluation-evidence.md").read_text(
            encoding="utf-8"
        )
        normalized_context = " ".join(context.split())
        normalized_overview = " ".join(overview.split())
        normalized_architecture = " ".join(architecture.split())
        normalized_docs_index = " ".join(docs_index.split())
        normalized_evaluation = " ".join(evaluation.split())

        for token in (
            "0.2 runtime implements task-state persistence for initialization and clarification",
            "superpowers/              # legacy/history only",
            "docs/superpowers/` may be retained for compatibility",
        ):
            self.assertNotIn(token, normalized_context)
        for token in (
            "0.2 persists only the remaining Init and generic task-state contracts",
            "docs/superpowers/` is the Current workflow-record location",
        ):
            self.assertIn(token, normalized_context)

        self.assertNotIn("并为澄清阶段提供持久化边界", normalized_overview)
        self.assertNotIn(
            "| `$sop-clarify` | 任务态事实、决策、术语增量 |",
            normalized_overview,
        )
        self.assertIn("最小 Git requirements workflow record", normalized_overview)
        self.assertIn("Trace 精确审批", normalized_overview)

        self.assertNotIn(
            "In 0.2, `$sop-init` and `$sop-clarify` adapt to their bounded runtimes directly.",
            normalized_architecture,
        )
        self.assertIn(
            "Current `$sop-clarify` adapts to the Git requirement and Trace boundary",
            normalized_architecture,
        )

        current_contracts = contracts.split(
            "## Historical clarification CLI boundary", 1
        )[0]
        self.assertNotIn(
            "the same task's clarification readiness/freshness anchor",
            current_contracts,
        )
        self.assertIn(
            "Current 0.4.0 Clarify does not consume `InitReport` or `context_ref`",
            " ".join(current_contracts.split()),
        )

        historical_contracts = contracts.split(
            "## Historical clarification CLI boundary", 1
        )[1].split("## Execution Trace", 1)[0]
        historical_results = contracts.split(
            "## Historical ClarificationCheckpoint and ClarificationResult", 1
        )[1].split("## DesignResult", 1)[0]
        self.assertIn("accepted only", historical_contracts)
        self.assertIn("was an immutable task-local", historical_results)
        for stale_present in (
            "The stage CLI accepts only",
            "Requests containing `repository` or `path` are rejected",
            "Checkpoint, approval-request, and result responses include",
            "`ClarificationCheckpoint` is an immutable task-local",
            "Its envelope carries",
            "At the current commit boundary",
            "history loading still accepts",
            "status, current lifecycle projection",
            "Current Skill/user-approval responsibility",
        ):
            self.assertNotIn(stale_present, historical_contracts + historical_results)

        historical_workflow = workflow.split(
            "### Historical 0.2/0.2.3 clarification flow", 1
        )[1].split("`$sop-debug`", 1)[0]
        for stale_present in (
            "The 0.2.3 gate submits",
            "The Current Skill presents",
            "Only a later user-authored approval permits",
            "The runtime proves",
        ):
            self.assertNotIn(stale_present, historical_workflow)

        self.assertIn("ADR 0006", normalized_docs_index)
        self.assertIn("ADR 0005（Historical）", normalized_docs_index)
        self.assertIn(
            "Historical evaluation-era decision: Matt-style clarification",
            normalized_evaluation,
        )

    def test_design_and_plan_never_create_revision_drift_for_drafts(self):
        design = (SKILLS / "sop-design/SKILL.md").read_text()
        plan = (SKILLS / "sop-plan/SKILL.md").read_text()
        self.assertIn("already ignored", design)
        self.assertIn("refuse to overwrite", design)
        self.assertIn("git check-ignore", plan)
        self.assertIn("already ignored", plan)
        self.assertIn("never changes `.gitignore`", design)
        self.assertIn("repository or its ignore rules", plan)

    def test_verify_skill_requires_fresh_acceptance_linked_evidence(self):
        text = (SKILLS / "sop-verify/SKILL.md").read_text()
        for token in ("acceptance criterion", "freshly", "candidateRevision"):
            self.assertIn(token, text)

    def test_public_docs_do_not_advertise_legacy_slash_commands(self):
        legacy = re.compile(
            r"(?<![\w.-])(?<!migration: )/(init|execute|debug|sync-docs|handoff)\b"
        )
        for path in SKILLS.glob("**/*.md"):
            self.assertIsNone(legacy.search(path.read_text()), path)
