#!/usr/bin/env bash
# rebase_clean.sh — rebase onto a base branch and remove a string from every commit message
#
# Usage:
#   ./scripts/rebase_clean.sh "<string-to-remove>" [base-branch]
#
# Examples:
#   ./scripts/rebase_clean.sh "Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>" main
#   ./scripts/rebase_clean.sh "🔧 " main
#
# After the script finishes, review with:
#   git log main..HEAD
# Then push manually:
#   git push --force-with-lease origin <branch>

set -euo pipefail

PATTERN="${1:?Usage: $0 '<string-to-remove>' [base-branch]}"
BASE="${2:-main}"
CURRENT=$(git branch --show-current)

echo ""
echo "Branch atual : $CURRENT"
echo "Rebase sobre : $BASE"
echo "Remover      : '$PATTERN'"
echo ""

read -rp "Continuar? [s/N] " CONFIRM
[[ "${CONFIRM,,}" == "s" ]] || { echo "Abortado."; exit 0; }

# ── Step 1: rebase onto base ──────────────────────────────────────────────────
echo ""
echo "→ Fazendo rebase sobre '$BASE'..."
git rebase "$BASE"

# ── Step 2: rewrite all commit messages ──────────────────────────────────────
echo "→ Reescrevendo mensagens (removendo '$PATTERN')..."

# Escape pattern for use in sed (handles special chars like / . * [ ] etc.)
ESCAPED=$(printf '%s\n' "$PATTERN" | sed 's/[[\.*^$()+?{|]/\\&/g; s/]/\\]/g')

# Write a temporary editor script that removes the pattern from the whole message
EDITOR_SCRIPT=$(mktemp /tmp/git_editor_XXXXXX.sh)
cat > "$EDITOR_SCRIPT" <<EDITOR
#!/usr/bin/env bash
# Remove pattern from every line of the commit message file (\$1)
sed -i "s/${ESCAPED}//g" "\$1"
# Remove lines that became empty (were only the pattern)
sed -i '/^[[:space:]]*$/{ N; /^\n$/d }' "\$1"
EDITOR
chmod +x "$EDITOR_SCRIPT"

export GIT_SEQUENCE_EDITOR="sed -i 's/^pick /reword /g'"
export GIT_EDITOR="$EDITOR_SCRIPT"

git rebase -i "$BASE"

rm -f "$EDITOR_SCRIPT"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "✓ Concluído. Commits resultantes:"
git log --oneline "${BASE}..HEAD"
echo ""
echo "Quando estiver satisfeito, faça o push:"
echo "  git push --force-with-lease origin $CURRENT"
