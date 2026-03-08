#!/bin/bash
# Reset test workspace — simulates a fresh user experience
# Usage: bash scripts/reset-test.sh
#
# Tests 3 install methods: uvx, pip, from-source

set -e

TEST_DIR="/tmp/test-workspace/paper-distill-mcp"
TEST_DATA="$HOME/.paper-distill-test"
REPO="https://github.com/Eclipse-Cj/paper-distill-mcp.git"

echo "=== Resetting test workspace ==="

# 1. Clean up
echo "[1/6] Cleaning ..."
rm -rf "$TEST_DIR" "$TEST_DATA"

# 2. Clone
echo "[2/6] Cloning from GitHub ..."
git clone "$REPO" "$TEST_DIR"
cd "$TEST_DIR"

# 3. Install (from source, since not on PyPI yet)
echo "[3/6] Installing from source ..."
python3.13 -m venv .venv
.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -e . -q
.venv/bin/pip install openai python-dateutil -q

# 4. Verify CLI
echo "[4/6] Verifying CLI ..."
.venv/bin/paper-distill-mcp --help > /dev/null

# 5. Smoke tests (uses test data dir, not real data)
echo "[5/6] Running smoke tests ..."
PAPER_DISTILL_DATA_DIR="$TEST_DATA" .venv/bin/python tests/test_mcp_smoke.py

# 6. Next steps
echo ""
echo "[6/6] Ready! Your test workspace:"
echo ""
echo "  Project:  $TEST_DIR"
echo "  Data:     $TEST_DATA"
echo ""
echo "  --- Quick test ---"
echo "  cd $TEST_DIR && source .venv/bin/activate"
echo "  paper-distill-mcp --help"
echo ""
echo "  --- Claude Code (one command) ---"
echo "  claude mcp add paper-distill -- $TEST_DIR/.venv/bin/paper-distill-mcp"
echo ""
echo "  --- OpenClaw ---"
echo "  paper-distill-mcp --transport http --port 8765"
echo ""
echo "  --- When published to PyPI ---"
echo "  claude mcp add paper-distill -- uvx paper-distill-mcp"
echo ""
