from pathlib import Path


skill = Path(__file__).resolve().parents[1] / "SKILL.md"
text = skill.read_text(encoding="utf-8")

assert "Compatibility Alias" in text
assert "canonical `pr-review`" in text
assert "Do not execute a second review policy" in text
