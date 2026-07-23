from pathlib import Path


skill = Path(__file__).resolve().parents[1] / "SKILL.md"
text = skill.read_text(encoding="utf-8")

assert "review+merge" in text
assert "another author's" in text
assert "$auto-dev-finalize" in text
assert "Never treat the user's current checkout as PR evidence" in text
