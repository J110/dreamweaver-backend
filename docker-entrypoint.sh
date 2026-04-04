#!/bin/bash
# Auto-recover funny-shorts covers from persistent store on container startup.
# This prevents covers from going missing after Docker rebuilds.

COVER_STORE="/opt/cover-store"
FUNNY_COVERS="/app/public/covers/funny-shorts"
SILLY_COVERS="/app/public/covers/silly-songs"

mkdir -p "$FUNNY_COVERS" "$SILLY_COVERS"

# Recover funny-shorts covers (svg + webp)
recovered=0
if [ -d "$COVER_STORE" ]; then
    for f in "$COVER_STORE"/funny-shorts--*; do
        [ -f "$f" ] || continue
        name="${f##*/}"
        original="${name#funny-shorts--}"
        if [ ! -f "$FUNNY_COVERS/$original" ]; then
            cp "$f" "$FUNNY_COVERS/$original"
            recovered=$((recovered + 1))
        fi
    done
    if [ "$recovered" -gt 0 ]; then
        echo "Recovered $recovered funny-shorts cover(s) from persistent store"
    fi

    # Recover silly-songs covers (svg + webp)
    silly_recovered=0
    for f in "$COVER_STORE"/silly-songs--*; do
        [ -f "$f" ] || continue
        name="${f##*/}"
        original="${name#silly-songs--}"
        if [ ! -f "$SILLY_COVERS/$original" ]; then
            cp "$f" "$SILLY_COVERS/$original"
            silly_recovered=$((silly_recovered + 1))
        fi
    done
    if [ "$silly_recovered" -gt 0 ]; then
        echo "Recovered $silly_recovered silly-songs cover(s) from persistent store"
    fi
fi

# Start the application
exec "$@"
