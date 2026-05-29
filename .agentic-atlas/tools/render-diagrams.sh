#!/usr/bin/env bash
# Render every Mermaid .mmd source under docs/diagrams/ (and .agentic-atlas/diagrams/)
# to PNG, using the local Chrome via puppeteer (no Chromium download).
#
# Diagrams are authored as checked-in .mmd text (diffable) and rendered to .png.
# Re-run after editing any .mmd:  bash .agentic-atlas/tools/render-diagrams.sh
#
# Requires: node + npx (uses npx @mermaid-js/mermaid-cli on demand).
set -euo pipefail

REPO="/Users/genome/projects/genomes_agentic_os"
PCFG="$REPO/.agentic-atlas/tools/puppeteer.json"
THEME="${MMD_THEME:-neutral}"
BG="${MMD_BG:-white}"

# Directories that may contain .mmd sources.
SEARCH_DIRS=("$REPO/docs" "$REPO/.agentic-atlas/diagrams")

count=0
for dir in "${SEARCH_DIRS[@]}"; do
  [ -d "$dir" ] || continue
  while IFS= read -r -d '' mmd; do
    out="${mmd%.mmd}.png"
    echo "render: ${mmd#$REPO/} -> ${out#$REPO/}"
    npx -y @mermaid-js/mermaid-cli -i "$mmd" -o "$out" \
      -p "$PCFG" -t "$THEME" -b "$BG" --scale 2 >/dev/null 2>&1 \
      && count=$((count+1)) \
      || echo "  !! FAILED: $mmd"
  done < <(find "$dir" -name '*.mmd' -print0)
done
echo "rendered $count diagram(s)"
