#!/bin/sh
# Install sonar into ~/.local/bin/sonar (no root needed).
#
#   From a clone or an extracted ZIP:   ./install.sh            (or: sh install.sh)
#   Without git, in one line:           curl -fsSL https://raw.githubusercontent.com/tfem1/sonar/main/install.sh | sh
#   Uninstall:                          ./install.sh --uninstall   (or: ... | sh -s -- --uninstall)
set -eu

REPO="tfem1/sonar"
REF="${SONAR_REF:-main}"
BIN_DIR="${BIN_DIR:-$HOME/.local/bin}"
TARGET="$BIN_DIR/sonar"

say() { printf '%s\n' "$*"; }
die() { printf 'error: %s\n' "$*" >&2; exit 1; }

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$TARGET"
    for rc in "$HOME/.bashrc" "$HOME/.zshrc" "$HOME/.profile"; do
        if grep -qs "# added by sonar" "$rc"; then
            grep -v "# added by sonar" "$rc" > "$rc.sonar-tmp" && mv "$rc.sonar-tmp" "$rc"
        fi
    done
    say "sonar removed from $TARGET"
    exit 0
fi

command -v python3 >/dev/null 2>&1 || die "python3 is required (e.g. sudo apt install python3 / sudo dnf install python3)"
python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))' || die "python 3.9 or newer is required"

# Use the sonar.py next to this script (clone / ZIP); when piped through sh, download it.
SRC=""
case "$0" in
    */*) [ -f "${0%/*}/sonar.py" ] && SRC="${0%/*}/sonar.py" ;;
    *)   [ -f "./install.sh" ] && [ -f "./sonar.py" ] && SRC="./sonar.py" ;;
esac

TMP=""
cleanup() { if [ -n "$TMP" ]; then rm -f "$TMP"; fi; }
trap cleanup EXIT INT TERM

if [ -z "$SRC" ]; then
    URL="https://raw.githubusercontent.com/$REPO/$REF/sonar.py"
    TMP="$(mktemp)"
    say "downloading $URL"
    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$URL" -o "$TMP" || die "download failed"
    elif command -v wget >/dev/null 2>&1; then
        wget -qO "$TMP" "$URL" || die "download failed"
    else
        die "curl or wget is required to download sonar"
    fi
    SRC="$TMP"
fi

python3 "$SRC" -V >/dev/null 2>&1 || die "$SRC is not a working sonar.py"

mkdir -p "$BIN_DIR"
cp "$SRC" "$TARGET"
chmod 755 "$TARGET"
say "$(python3 "$TARGET" -V) installed to $TARGET"

case ":$PATH:" in
    *":$BIN_DIR:"*)
        say "run it with: sonar" ;;
    *)
        # put ~/.local/bin on the PATH of the user's shell (once); SONAR_NO_PATH=1 skips this
        case "${SHELL:-}" in
            */zsh)  RC="$HOME/.zshrc" ;;
            */bash) RC="$HOME/.bashrc" ;;
            */fish) RC="" ; say "fish: run  fish_add_path $BIN_DIR" ;;
            *)      RC="$HOME/.profile" ;;
        esac
        if [ -n "$RC" ] && [ -z "${SONAR_NO_PATH:-}" ]; then
            if ! grep -qs "# added by sonar" "$RC"; then
                printf '\nexport PATH="%s:$PATH"  # added by sonar\n' "$BIN_DIR" >> "$RC"
                say "added $BIN_DIR to your PATH in $RC"
            fi
            say "open a new terminal (or run: . $RC), then: sonar"
        fi
        say "or run it directly: $TARGET" ;;
esac
