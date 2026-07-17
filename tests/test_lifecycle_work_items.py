from pathlib import Path

from genomes_agentic_os.lifecycle import local_project_work_items


def _write_work_item(project_root: Path, slug: str, body: str) -> Path:
    item_dir = project_root / "work-items" / "02-active" / slug
    item_dir.mkdir(parents=True)
    metadata = item_dir / "work.yml"
    metadata.write_text(body, encoding="utf-8")
    return item_dir


def test_local_project_work_items_survives_malformed_metadata(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_work_item(project_root, "good_item", "id: good_item\ntitle: Good item\nstatus: in_progress\n")
    # Backtick cannot start a YAML scalar; agent-authored files hit this in the wild.
    _write_work_item(project_root, "bad_item", "id: bad_item\nacceptance_criteria:\n- `broken` bullet\n")

    records = local_project_work_items(project_root)

    by_slug = {record.slug for record in records}
    assert "good_item" in by_slug
    broken = [record for record in records if record.metadata.get("metadata_error")]
    assert len(broken) == 1
    assert "invalid yaml" in broken[0].metadata["metadata_error"]
