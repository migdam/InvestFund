#!/bin/bash
# Script to create main branch from current work
# Run this locally (not in Claude Code)

set -e

echo "Creating main branch from current work..."

# Ensure we're on the right branch
git checkout claude/enhance-funds-analysis-017gvWUhpDKdUP1bNAL1w9vV

# Create main branch from current commit
git branch -f main HEAD

# Push main branch
git push origin main

echo "✅ Done! Your repository is now viewable at:"
echo "   https://github.com/migdam/InvestFund"

# Optionally set main as default branch
echo ""
echo "To set main as default branch:"
echo "1. Go to https://github.com/migdam/InvestFund/settings/branches"
echo "2. Click 'Switch to another branch' next to Default branch"
echo "3. Select 'main'"
echo "4. Click 'Update'"
