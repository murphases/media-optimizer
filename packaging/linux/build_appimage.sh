#!/usr/bin/env bash
set -e

echo "🐧 Construindo AppImage para Media Optimizer..."
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APPDIR="${ROOT_DIR}/build/AppDir"

rm -rf "${APPDIR}"
mkdir -p "${APPDIR}/usr/bin"
mkdir -p "${APPDIR}/usr/share/media-optimizer"
mkdir -p "${APPDIR}/usr/share/applications"
mkdir -p "${APPDIR}/usr/share/icons/hicolor/256x256/apps"
mkdir -p "${APPDIR}/bin"

# 1. Copiar código fonte
cp -r "${ROOT_DIR}/media_optimizer" "${APPDIR}/usr/share/media-optimizer/"
cp "${ROOT_DIR}/main.py" "${APPDIR}/usr/share/media-optimizer/"

# 2. Copiar AppRun e Desktop
cp "${ROOT_DIR}/packaging/linux/AppRun" "${APPDIR}/AppRun"
chmod +x "${APPDIR}/AppRun"

cp "${ROOT_DIR}/packaging/linux/media-optimizer.desktop" "${APPDIR}/media-optimizer.desktop"
cp "${ROOT_DIR}/packaging/linux/media-optimizer.desktop" "${APPDIR}/usr/share/applications/"

# 3. Baixar/Copiar FFmpeg estático
python3 "${ROOT_DIR}/scripts/bundle_ffmpeg.py" linux
if [ -f "${ROOT_DIR}/bin/ffmpeg" ]; then
    cp "${ROOT_DIR}/bin/ffmpeg" "${APPDIR}/bin/"
    cp "${ROOT_DIR}/bin/ffprobe" "${APPDIR}/bin/"
    chmod +x "${APPDIR}/bin/ffmpeg" "${APPDIR}/bin/ffprobe"
fi

# 4. Gerar AppImage via appimagetool se disponível
if command -v appimagetool >/dev/null 2>&1; then
    mkdir -p "${ROOT_DIR}/dist"
    appimagetool "${APPDIR}" "${ROOT_DIR}/dist/MediaOptimizer-x86_64.AppImage"
    echo "✅ AppImage criado com sucesso em dist/MediaOptimizer-x86_64.AppImage"
else
    echo "⚠️ appimagetool não encontrado localmente. O AppDir foi preparado em: ${APPDIR}"
fi
