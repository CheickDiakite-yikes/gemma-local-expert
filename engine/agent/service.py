from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from engine.contracts.api import AgentRunStep, AgentStepStatus, new_id, utc_now

SUPPORTED_TEXT_EXTENSIONS = {
    ".c",
    ".cc",
    ".cfg",
    ".conf",
    ".cpp",
    ".css",
    ".csv",
    ".env",
    ".go",
    ".h",
    ".hpp",
    ".html",
    ".java",
    ".js",
    ".json",
    ".jsx",
    ".md",
    ".mjs",
    ".py",
    ".rb",
    ".rst",
    ".sh",
    ".sql",
    ".swift",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

SKIP_DIRECTORIES = {
    ".git",
    ".hg",
    ".next",
    ".pytest_cache",
    ".ruff_cache",
    ".svn",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}

STOPWORDS = {
    "a",
    "about",
    "all",
    "and",
    "brief",
    "file",
    "files",
    "folder",
    "for",
    "from",
    "in",
    "of",
    "on",
    "prepare",
    "project",
    "relevant",
    "search",
    "summarize",
    "summary",
    "the",
    "this",
    "through",
    "workspace",
}


@dataclass(slots=True)
class WorkspaceAgentPlan:
    goal: str
    scope_root: str
    steps: list[AgentRunStep]
    output_tool_name: str | None = None


@dataclass(slots=True)
class WorkspaceCandidate:
    path: Path
    relative_path: str
    score: float
    size_bytes: int
    preview: str


@dataclass(slots=True)
class WorkspaceReadDocument:
    path: Path
    relative_path: str
    score: float
    excerpt: str


@dataclass(slots=True)
class WorkspaceAgentState:
    scope_root: Path
    top_entries: list[str] = field(default_factory=list)
    candidate_files: list[WorkspaceCandidate] = field(default_factory=list)
    read_documents: list[WorkspaceReadDocument] = field(default_factory=list)
    summary_text: str | None = None


class WorkspaceAgentError(ValueError):
    pass


class WorkspaceAgentService:
    def __init__(
        self,
        *,
        workspace_root: str,
        max_steps: int,
        max_file_reads: int,
        max_context_chars: int,
    ) -> None:
        self.workspace_root = Path(workspace_root).resolve()
        self.max_steps = max_steps
        self.max_file_reads = max_file_reads
        self.max_context_chars = max_context_chars

    def plan(self, goal: str) -> WorkspaceAgentPlan:
        scope_root = self._resolve_scope_root(goal)
        output_tool_name = self._select_output_tool(goal)
        steps = [
            self._step("inspect_scope", "Inspect workspace scope"),
            self._step("search_workspace", "Search workspace files"),
            self._step("read_candidates", "Read candidate documents"),
            self._step("synthesize_workspace", "Synthesize workspace findings"),
        ]
        if output_tool_name:
            steps.append(self._step("prepare_output", "Prepare durable output"))
        return WorkspaceAgentPlan(
            goal=goal,
            scope_root=str(scope_root),
            steps=steps[: self.max_steps],
            output_tool_name=output_tool_name,
        )

    def create_state(self, plan: WorkspaceAgentPlan) -> WorkspaceAgentState:
        return WorkspaceAgentState(scope_root=Path(plan.scope_root))

    def execute_step(
        self,
        plan: WorkspaceAgentPlan,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        if step.kind == "inspect_scope":
            return self._inspect_scope(state, step)
        if step.kind == "search_workspace":
            return self._search_workspace(plan, state, step)
        if step.kind == "read_candidates":
            return self._read_candidates(state, step)
        if step.kind == "synthesize_workspace":
            return self._synthesize_workspace(plan, state, step)
        if step.kind == "prepare_output":
            return self._prepare_output(plan, state, step)
        return self._complete_step(step, "Skipped unknown workspace step.")

    def _inspect_scope(
        self,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        entries = []
        for path in sorted(state.scope_root.iterdir(), key=lambda item: (item.is_file(), item.name.lower())):
            if path.name in SKIP_DIRECTORIES:
                continue
            entries.append(path.name + ("/" if path.is_dir() else ""))
            if len(entries) == 8:
                break
        state.top_entries = entries
        detail = (
            f"Scoped the workspace agent to `{state.scope_root}` and inspected the top-level entries."
        )
        return self._complete_step(step, detail, references=entries[:4])

    def _search_workspace(
        self,
        plan: WorkspaceAgentPlan,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        tokens = self._search_tokens(plan.goal)
        candidates: list[WorkspaceCandidate] = []
        for path in self._iter_supported_files(state.scope_root):
            try:
                size_bytes = path.stat().st_size
            except OSError:
                continue
            preview = self._read_text(path, char_limit=1800)
            if preview is None:
                continue
            score = self._score_candidate(tokens, path, preview)
            if score <= 0:
                continue
            candidates.append(
                WorkspaceCandidate(
                    path=path,
                    relative_path=self._relative_path(path),
                    score=score,
                    size_bytes=size_bytes,
                    preview=preview,
                )
            )

        candidates.sort(
            key=lambda candidate: (-candidate.score, candidate.relative_path.lower())
        )
        seen_paths = {candidate.path for candidate in candidates}
        if len(candidates) < self.max_file_reads:
            for path in self._iter_supported_files(state.scope_root):
                if path in seen_paths:
                    continue
                preview = self._read_text(path, char_limit=600)
                if preview is None:
                    continue
                candidates.append(
                    WorkspaceCandidate(
                        path=path,
                        relative_path=self._relative_path(path),
                        score=0.01,
                        size_bytes=path.stat().st_size,
                        preview=preview,
                    )
                )
                seen_paths.add(path)
                if len(candidates) == self.max_file_reads:
                    break

        state.candidate_files = candidates[: max(self.max_file_reads, 1)]
        if not state.candidate_files:
            return self._blocked_step(
                step,
                "No supported text-like files were available inside the allowed workspace scope.",
            )

        detail = (
            f"Found {len(state.candidate_files)} candidate files inside the workspace scope."
        )
        return self._complete_step(
            step,
            detail,
            references=[candidate.relative_path for candidate in state.candidate_files[:4]],
        )

    def _read_candidates(
        self,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        documents: list[WorkspaceReadDocument] = []
        for candidate in state.candidate_files[: self.max_file_reads]:
            excerpt = self._read_text(candidate.path, char_limit=2200)
            if not excerpt:
                continue
            documents.append(
                WorkspaceReadDocument(
                    path=candidate.path,
                    relative_path=candidate.relative_path,
                    score=candidate.score,
                    excerpt=excerpt,
                )
            )
        state.read_documents = documents
        if not documents:
            return self._failed_step(
                step,
                "Candidate files were found, but none of them could be read as supported text content.",
            )
        return self._complete_step(
            step,
            f"Read {len(documents)} workspace files and collected structured excerpts for synthesis.",
            references=[document.relative_path for document in documents[:4]],
        )

    def _synthesize_workspace(
        self,
        plan: WorkspaceAgentPlan,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        summary = self._build_summary(plan, state)
        state.summary_text = summary
        references = [document.relative_path for document in state.read_documents[:4]]
        return self._complete_step(
            step,
            "Synthesized the workspace findings into bounded context for the assistant.",
            references=references,
        )

    def _prepare_output(
        self,
        plan: WorkspaceAgentPlan,
        state: WorkspaceAgentState,
        step: AgentRunStep,
    ) -> AgentRunStep:
        if not plan.output_tool_name:
            return self._failed_step(step, "No durable output type was selected for this goal.")
        if not state.summary_text:
            return self._failed_step(step, "Workspace findings were not ready for output planning.")
        return self._complete_step(
            step,
            f"Prepared `{plan.output_tool_name}` from the workspace findings and queued it for approval if needed.",
            references=[document.relative_path for document in state.read_documents[:3]],
        )

    def _build_summary(
        self,
        plan: WorkspaceAgentPlan,
        state: WorkspaceAgentState,
    ) -> str:
        sections = [
            f"Goal: {plan.goal}",
            f"Workspace scope: {self._display_scope(Path(plan.scope_root))}",
        ]
        if state.top_entries:
            sections.append("Top-level scope entries:\n- " + "\n- ".join(state.top_entries))
        if state.read_documents:
            document_blocks = []
            for document in state.read_documents[: self.max_file_reads]:
                cleaned_excerpt = self._compact_excerpt(document.excerpt)
                document_blocks.append(
                    f"[{document.relative_path}] score={document.score:.2f}\n{cleaned_excerpt}"
                )
            sections.append("Workspace findings:\n" + "\n\n".join(document_blocks))
        else:
            sections.append("Workspace findings:\nNo readable candidate files were available.")

        summary = "\n\n".join(sections).strip()
        if len(summary) <= self.max_context_chars:
            return summary
        return summary[: self.max_context_chars - 1].rstrip() + "…"

    def _resolve_scope_root(self, goal: str) -> Path:
        requested = self._extract_scope_hint(goal)
        if not requested:
            return self.workspace_root

        requested_path = Path(requested).expanduser()
        if not requested_path.is_absolute():
            requested_path = (self.workspace_root / requested_path).resolve()
        else:
            requested_path = requested_path.resolve()

        try:
            requested_path.relative_to(self.workspace_root)
        except ValueError as exc:
            raise WorkspaceAgentError(
                f"Requested path `{requested}` is outside the allowed workspace scope."
            ) from exc

        if not requested_path.exists():
            raise WorkspaceAgentError(
                f"Requested scope `{requested}` does not exist inside the allowed workspace."
            )

        if requested_path.is_file() and not self._is_supported_text_file(requested_path):
            raise WorkspaceAgentError(
                f"Requested file `{requested}` is not a supported text-like workspace file."
            )

        return requested_path if requested_path.is_dir() else requested_path.parent

    def _extract_scope_hint(self, goal: str) -> str | None:
        quoted = re.findall(r"[\"']([^\"']+)[\"']", goal)
        for candidate in quoted:
            if "/" in candidate or candidate.startswith("."):
                return candidate

        path_match = re.search(
            r"(?:in|under|inside|from)\s+((?:\.\.?/|/)[^\s,;:]+|[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)",
            goal,
            flags=re.I,
        )
        if path_match:
            return path_match.group(1)

        if re.search(r"(?:^|\s)(?:/|\.{1,2}/)", goal):
            token = re.search(r"((?:/|\.{1,2}/)[^\s,;:]+)", goal)
            if token:
                return token.group(1)

        return None

    def _search_tokens(self, goal: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]+", goal.lower())
        return [token for token in tokens if len(token) > 2 and token not in STOPWORDS]

    def _score_candidate(self, tokens: list[str], path: Path, preview: str) -> float:
        haystack = f"{path.as_posix()} {preview.lower()}"
        score = 0.0
        for token in tokens:
            if token in path.as_posix().lower():
                score += 2.0
            matches = haystack.count(token)
            if matches:
                score += min(3.0, matches * 0.35)
        return score

    def _iter_supported_files(self, scope_root: Path):
        if scope_root.is_file():
            if self._is_supported_text_file(scope_root):
                yield scope_root
            return

        for path in scope_root.rglob("*"):
            if any(part in SKIP_DIRECTORIES for part in path.parts):
                continue
            if not path.is_file():
                continue
            if self._is_supported_text_file(path):
                yield path

    def _is_supported_text_file(self, path: Path) -> bool:
        return path.suffix.lower() in SUPPORTED_TEXT_EXTENSIONS

    def _read_text(self, path: Path, *, char_limit: int) -> str | None:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            return None
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return None
        if "\x00" in text:
            return None
        if len(text) <= char_limit:
            return text
        return text[: char_limit - 1].rstrip() + "…"

    def _compact_excerpt(self, text: str) -> str:
        compact = re.sub(r"\n{3,}", "\n\n", text).strip()
        return compact

    def _relative_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.workspace_root))
        except ValueError:
            return str(path)

    def _display_scope(self, scope_root: Path) -> str:
        try:
            relative = scope_root.relative_to(self.workspace_root)
            return "." if str(relative) == "." else str(relative)
        except ValueError:
            return str(scope_root)

    def _select_output_tool(self, goal: str) -> str | None:
        lowered = goal.lower()
        if "checklist" in lowered:
            return "create_checklist"
        if "task" in lowered or "todo" in lowered:
            return "create_task"
        if any(keyword in lowered for keyword in {"brief", "briefing", "note", "report"}) and any(
            verb in lowered for verb in {"prepare", "create", "write", "draft", "make", "build"}
        ):
            return "create_note"
        return None

    def _step(self, kind: str, title: str) -> AgentRunStep:
        now = utc_now()
        return AgentRunStep(
            id=new_id("step"),
            kind=kind,
            title=title,
            status=AgentStepStatus.PLANNED,
            created_at=now,
            updated_at=now,
        )

    def _complete_step(
        self,
        step: AgentRunStep,
        detail: str,
        *,
        references: list[str] | None = None,
    ) -> AgentRunStep:
        now = utc_now()
        return step.model_copy(
            update={
                "status": AgentStepStatus.COMPLETED,
                "detail": detail,
                "references": references or [],
                "updated_at": now,
            }
        )

    def _blocked_step(self, step: AgentRunStep, detail: str) -> AgentRunStep:
        return step.model_copy(
            update={
                "status": AgentStepStatus.BLOCKED,
                "detail": detail,
                "updated_at": utc_now(),
            }
        )

    def _failed_step(self, step: AgentRunStep, detail: str) -> AgentRunStep:
        return step.model_copy(
            update={
                "status": AgentStepStatus.FAILED,
                "detail": detail,
                "updated_at": utc_now(),
            }
        )
