#!/bin/sh
# Install okaeri without git or uv:
#   curl -fsSL https://raw.githubusercontent.com/DBvdHeijden/okaeri/main/install.sh | sh
# Running it again reinstalls the service; update with `uv run main.py update`.
set -eu

REPO=DBvdHeijden/okaeri
DIR="${OKAERI_DIR:-$HOME/okaeri}"

if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
  PATH="$HOME/.local/bin:$PATH"  # where the uv installer puts it; new terminals pick it up from your shell profile
fi

if [ ! -e "$DIR" ]; then
  sha=$(curl -fsSL -H "Accept: application/vnd.github.sha" "https://api.github.com/repos/$REPO/commits/main")
  # Unpack next to it first, so a failed download doesn't leave a half-filled folder behind.
  rm -rf "$DIR.download" && mkdir -p "$DIR.download"
  curl -fsSL "https://github.com/$REPO/archive/$sha.tar.gz" | tar -xz -C "$DIR.download" --strip-components=1
  echo "$sha" > "$DIR.download/VERSION"
  mv "$DIR.download" "$DIR"
fi

cd "$DIR"
uv run main.py install
