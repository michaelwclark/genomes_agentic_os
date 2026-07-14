"""Filesystem source/mirror adapter for canonical Specs."""

from __future__ import annotations

from pathlib import Path
import re
import shutil
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

import yaml

from ..scaffold import domain_path, expand_path, normalize_domain, validate_name
from ..spec_engine import AdapterReceipt, Spec, lane_for_status, utc_now


def _slug(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "spec"


class FilesystemSpecAdapter:
    name = "filesystem"

    def __init__(self, root: str | Path, domain: str, project: str, policy: Mapping[str, Any] | None = None):
        self.root = expand_path(root)
        self.domain = normalize_domain(domain)
        self.project = validate_name(project, "project")
        self.policy = dict(policy or {})
        self.project_root = domain_path(self.root, self.domain) / "02-projects" / self.project
        configured = str(self.policy.get("work_items_root") or "work-items")
        self.work_items_root = self.project_root / configured

    def _ensure_project(self) -> None:
        if not self.project_root.is_dir():
            raise ValueError(f"project not found: {self.domain}/{self.project}")

    def _iter_roots(self):
        for lane in ("01-intake", "02-active", "03-complete"):
            lane_root = self.work_items_root / lane
            if not lane_root.is_dir():
                continue
            for path in sorted(lane_root.iterdir()):
                if path.is_dir() and ((path / "work.yml").is_file() or (path / "spec.yml").is_file()):
                    yield path
                elif path.is_file() and path.suffix == ".md":
                    yield path

    def _metadata_path(self, path: Path) -> Path:
        if path.is_file():
            return path
        return path / ("spec.yml" if (path / "spec.yml").is_file() else "work.yml")

    def _load_path(self, path: Path) -> Spec:
        metadata_path = self._metadata_path(path)
        if metadata_path.suffix == ".md":
            text = metadata_path.read_text(encoding="utf-8", errors="replace")
            data = yaml.safe_load(text.split("---", 2)[1]) if text.startswith("---") and text.count("---") >= 2 else {}
        else:
            data = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        spec = Spec.from_mapping(data if isinstance(data, Mapping) else {})
        if not spec.id:
            spec.id = path.stem
        if not spec.domain:
            spec.domain = self.domain
        if not spec.project:
            spec.project = self.project
        return spec

    def _path_for(self, spec: Spec) -> Path:
        return self.work_items_root / lane_for_status(spec.status) / spec.id

    def _find_path(self, spec_id: str) -> Path | None:
        for path in self._iter_roots():
            if path.stem == spec_id or path.name == spec_id:
                return path
            try:
                if self._load_path(path).id == spec_id:
                    return path
            except Exception:
                continue
        return None

    def _duplicate(self, spec: Spec) -> Spec | None:
        title = spec.title.strip().casefold()
        for item in self.list():
            if item.id != spec.id and item.title.strip().casefold() == title:
                return item
        return None

    def _write(self, path: Path, spec: Spec) -> None:
        path.mkdir(parents=True, exist_ok=True)
        for child in ("artifacts", "logs", "logs/conversations"):
            (path / child).mkdir(parents=True, exist_ok=True)
        payload = spec.to_mapping()
        payload["lifecycle"]["required_files"] = ["SPEC.md", "WORKLOG.md", "NEXT.md"]
        (path / "work.yml").write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        if not (path / "SPEC.md").exists():
            (path / "SPEC.md").write_text(
                f"# Spec: {spec.title}\n\n## Original Intent\n\n{spec.summary}\n\n## Acceptance Criteria\n\n"
                + ("\n".join(f"- {item}" for item in spec.acceptance_criteria) if spec.acceptance_criteria else "- To be groomed.")
                + "\n",
                encoding="utf-8",
            )
        if not (path / "WORKLOG.md").exists():
            (path / "WORKLOG.md").write_text(f"# Worklog: {spec.title}\n\n- {utc_now()}: Spec recorded as `{spec.status}`.\n", encoding="utf-8")
        if not (path / "NEXT.md").exists():
            (path / "NEXT.md").write_text(f"# Next: {spec.title}\n\n- Advance from `{spec.status}` according to project policy.\n", encoding="utf-8")

    def create(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt:
        self._ensure_project()
        key = f"spec:{self.domain}:{self.project}:{spec.id}"
        target = self._path_for(spec)
        existing_path = self._find_path(spec.id)
        duplicate = self._duplicate(spec)
        plan = {"path": str(target), "idempotency_key": key}
        if existing_path:
            return AdapterReceipt(self.name, "create", True, status="exists", spec_id=spec.id, idempotency_key=key, readback_verified=True, detail=f"spec already exists at {existing_path}", plan=plan)
        if duplicate:
            return AdapterReceipt(self.name, "create", True, status="duplicate", spec_id=spec.id, provider_id=duplicate.id, idempotency_key=key, readback_verified=True, detail=f"matching spec already exists: {duplicate.id}", plan=plan)
        if not apply:
            return AdapterReceipt(self.name, "create", True, status="planned", spec_id=spec.id, idempotency_key=key, detail="dry-run filesystem plan", plan=plan)
        self._write(target, spec)
        readback = self.get(spec.id)
        ok = readback is not None and readback.status == spec.status and readback.type == spec.type
        return AdapterReceipt(self.name, "create", ok, applied=True, status="applied" if ok else "failed", spec_id=spec.id, provider_id=spec.id, idempotency_key=key, verified_target=True, readback_verified=ok, detail=f"filesystem spec written to {target}", error=None if ok else "readback mismatch", plan=plan)

    def get(self, spec_id: str) -> Spec | None:
        path = self._find_path(spec_id)
        return self._load_path(path) if path else None

    def list(self, **filters: Any) -> list[Spec]:
        result: list[Spec] = []
        for path in self._iter_roots():
            try:
                spec = self._load_path(path)
            except Exception:
                continue
            if filters.get("status") and spec.status != filters["status"]:
                continue
            if filters.get("type") and spec.type != filters["type"]:
                continue
            result.append(spec)
        return result

    def transition(self, spec: Spec, *, previous_status: str, apply: bool = False) -> AdapterReceipt:
        self._ensure_project()
        source = self._find_path(spec.id)
        target = self._path_for(spec)
        key = f"spec:{self.domain}:{self.project}:{spec.id}:transition:{spec.status}"
        plan = {"from": str(source) if source else None, "to": str(target), "previous_status": previous_status, "status": spec.status}
        if not source:
            return AdapterReceipt(self.name, "transition", False, status="blocked", spec_id=spec.id, idempotency_key=key, error="spec not found", plan=plan)
        if not apply:
            return AdapterReceipt(self.name, "transition", True, status="planned", spec_id=spec.id, idempotency_key=key, detail="dry-run filesystem transition", plan=plan)
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            if target.exists():
                return AdapterReceipt(self.name, "transition", False, status="blocked", spec_id=spec.id, idempotency_key=key, error=f"target exists: {target}", plan=plan)
            shutil.move(str(source), str(target))
        self._write(target, spec)
        readback = self.get(spec.id)
        ok = readback is not None and readback.status == spec.status and readback.blocked_from == spec.blocked_from
        return AdapterReceipt(self.name, "transition", ok, applied=True, status="applied" if ok else "failed", spec_id=spec.id, provider_id=spec.id, idempotency_key=key, verified_target=True, readback_verified=ok, detail=f"filesystem spec transitioned to {spec.status}", error=None if ok else "readback mismatch", plan=plan)

    def sync(self, spec: Spec, *, apply: bool = False) -> AdapterReceipt:
        existing = self.get(spec.id)
        if existing:
            previous = existing.status
            return self.transition(spec, previous_status=previous, apply=apply)
        return self.create(spec, apply=apply)

    def record_receipts(self, spec_id: str, operation: str, receipts: Iterable[AdapterReceipt]) -> Path | None:
        """Persist provider receipts beside the local identity and link provider refs."""
        path = self._find_path(spec_id)
        if path is None or path.is_file():
            return None
        receipt_list = list(receipts)
        if not receipt_list:
            return None
        spec = self._load_path(path)
        for receipt in receipt_list:
            if receipt.adapter == "filesystem" or not receipt.provider_id:
                continue
            ref = {
                "adapter": receipt.adapter,
                "provider_id": receipt.provider_id,
                "url": receipt.url,
            }
            spec.external_refs = [
                item
                for item in spec.external_refs
                if not (
                    item.get("adapter") == receipt.adapter
                    and item.get("provider_id") == receipt.provider_id
                )
            ]
            spec.external_refs.append(ref)
        self._write(path, spec)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        receipt_dir = path / "artifacts" / "spec-receipts"
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path = receipt_dir / f"{timestamp}-{_slug(operation)}.yml"
        receipt_path.write_text(
            yaml.safe_dump(
                {
                    "schema_version": 1,
                    "spec_id": spec_id,
                    "operation": operation,
                    "recorded_at": utc_now(),
                    "receipts": [receipt.to_mapping() for receipt in receipt_list],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        with (path / "WORKLOG.md").open("a", encoding="utf-8") as stream:
            stream.write(f"- {utc_now()}: `{operation}` receipts recorded in `artifacts/spec-receipts/{receipt_path.name}`.\n")
        return receipt_path

    def doctor(self) -> AdapterReceipt:
        ok = self.project_root.is_dir()
        return AdapterReceipt(self.name, "doctor", ok, status="verified" if ok else "blocked", verified_target=ok, detail=f"filesystem project {'found' if ok else 'missing'}: {self.project_root}", error=None if ok else "project not found")
