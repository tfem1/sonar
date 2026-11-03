#!/bin/sh
# Install sonar into ~/.local/bin/sonar (no root needed).
#   ./install.sh            install / update
#   ./install.sh --uninstall
set -eu

BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
TARGET="$BIN_DIR/sonar"
SRC="$(cd "$(dirname "$0")" && pwd)/sonar.py"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$TARGET"
    echo "sonar removed from $TARGET"
    exit 0
fi

command -v python3 >/dev/null 2>&1 || { echo "error: python3 is required" >&2; exit 1; }
python3 -c 'import sys; sys.exit(sys.version_info < (3, 6))' || { echo "error: python 3.6+ is required" >&2; exit 1; }
[ -f "$SRC" ] || { echo "error: sonar.py not found next to install.sh" >&2; exit 1; }

mkdir -p "$BIN_DIR"
install -m 755 "$SRC" "$TARGET"
echo "sonar $(python3 "$TARGET" -V | cut -d' ' -f2) installed to $TARGET"

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) echo "note: $BIN_DIR is not in your PATH; add this to your shell profile:"
       echo "      export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
