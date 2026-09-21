#!/usr/bin/env bash
set -e

echo "🍏 Construindo pacote .app e .dmg para macOS..."
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DIST_DIR="${ROOT_DIR}/dist"
BUILD_DIR="${ROOT_DIR}/build"

mkdir -p "${DIST_DIR}" "${BUILD_DIR}"

# 1. Empacotar via PyInstaller no macOS
pyinstaller \
    --name "MediaOptimizer" \
    --windowed \
    --noconfirm \
    --clean \
    --add-data "${ROOT_DIR}/media_optimizer:media_optimizer" \
    --hidden-import "customtkinter" \
    --hidden-import "darkdetect" \
    --hidden-import "PIL" \
    --hidden-import "pillow_heif" \
    --hidden-import "rawpy" \
    "${ROOT_DIR}/main.py"

# 2. Copiar FFmpeg para dentro do bundle macOS se existir
if [ -f "${ROOT_DIR}/bin/ffmpeg" ]; then
    mkdir -p "${DIST_DIR}/MediaOptimizer.app/Contents/MacOS/bin"
    cp "${ROOT_DIR}/bin/ffmpeg" "${DIST_DIR}/MediaOptimizer.app/Contents/MacOS/bin/"
    cp "${ROOT_DIR}/bin/ffprobe" "${DIST_DIR}/MediaOptimizer.app/Contents/MacOS/bin/"
    chmod +x "${DIST_DIR}/MediaOptimizer.app/Contents/MacOS/bin/"*
fi

# 3. Gerar arquivo .dmg
DMG_PATH="${DIST_DIR}/MediaOptimizer-macOS.dmg"
rm -f "${DMG_PATH}"

if command -v create-dmg >/dev/null 2>&1; then
    create-dmg \
        --volname "Media Optimizer" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon-size 100 \
        --icon "MediaOptimizer.app" 175 190 \
        --hide-extension "MediaOptimizer.app" \
        --app-drop-link 425 190 \
        "${DMG_PATH}" \
        "${DIST_DIR}/MediaOptimizer.app"
    echo "✅ .dmg gerado com sucesso via create-dmg em: ${DMG_PATH}"
else
    echo "ℹ️ create-dmg não disponível, utilizando hdiutil padrão do macOS..."
    hdiutil create -volname "Media Optimizer" -srcfolder "${DIST_DIR}/MediaOptimizer.app" -ov -format UDZO "${DMG_PATH}"
    echo "✅ .dmg gerado com sucesso via hdiutil em: ${DMG_PATH}"
fi
