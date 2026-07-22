from datetime import datetime, timezone
from pathlib import Path

import yaml

from genomes_agentic_os.development_delivery import find_delivery_work_item
from genomes_agentic_os.lifecycle import local_work_item_candidates
from genomes_agentic_os.work_item_archive import archive_retained_work_items


def _project(root: Path) -> Path:
    project = root / "domains" / "acme" / "02-projects" / "app"
    (project / "config").mkdir(parents=True)
    (project / "project.yml").write_text("id: app\ndomain: acme\n", encoding="utf-8")
    (project / "config" / "work-lifecycle.yml").write_text(
        yaml.safe_dump(
            {
                "work_lifecycle": {
                    "layout": "single_canonical_root",
                    "work_items_root": "work-items",
                    "archive": {
                        "enabled": True,
                        "directory": "99-archived",
                        "retention_days": 7,
                        "terminal_states": ["finished", "documented", "archived"],
                    },
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return project


def _packet(project: Path, name: str, *, reopen: bool = False) -> Path:
    packet = project / "work-items" / name
    packet.mkdir(parents=True)
    (packet / "work.yml").write_text(
        yaml.safe_dump(
            {
                "id": name.split("-", 1)[-1],
                "title": name,
                "status": "finished",
                "updated_at": "2026-07-01T00:00:00Z",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    if reopen:
        (packet / "REOPEN.md").write_text("# Reopen\n", encoding="utf-8")
    return packet


def test_archive_moves_retained_terminal_packet_and_preserves_reopen(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    project = _project(root)
    terminal = _packet(project, "070126-001_terminal")
    retained = _packet(project, "070126-002_returned", reopen=True)

    plan = archive_retained_work_items(
        root,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    assert plan["candidate_count"] == 1
    assert terminal.exists()
    assert Path(plan["receipt"]).is_file()

    result = archive_retained_work_items(
        root,
        apply=True,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )
    archived = project / "work-items" / "99-archived" / terminal.name
    assert result["archived"] == ["001_terminal"]
    assert archived.is_dir()
    assert not terminal.exists()
    assert retained.is_dir()
    assert Path(result["receipt"]).is_file()


def test_auto_dev_lookup_and_lifecycle_scan_include_archive(tmp_path: Path) -> None:
    project = _project(tmp_path / "agentic_os")
    archived = _packet(project, "070126-cc_347_returned")
    archive_root = project / "work-items" / "99-archived"
    archive_root.mkdir(parents=True)
    archived.rename(archive_root / archived.name)
    archived = archive_root / archived.name

    assert find_delivery_work_item(project, "cc_347_returned") == archived
    assert archived in local_work_item_candidates(project / "work-items")


def test_archive_supports_week_retention_units(tmp_path: Path) -> None:
    root = tmp_path / "agentic_os"
    project = _project(root)
    config_path = project / "config" / "work-lifecycle.yml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    archive = config["work_lifecycle"]["archive"]
    archive["retention"] = {"value": 2, "unit": "weeks"}
    archive.pop("retention_days")
    config_path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    _packet(project, "070126-001_terminal")

    before_cutoff = archive_retained_work_items(
        root,
        now=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    after_cutoff = archive_retained_work_items(
        root,
        now=datetime(2026, 7, 21, tzinfo=timezone.utc),
    )

    assert before_cutoff["candidate_count"] == 0
    assert after_cutoff["candidate_count"] == 1
    assert after_cutoff["candidates"][0]["retention"] == "2 weeks"
