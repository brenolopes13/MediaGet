#!/usr/bin/env bash
# Compila o programa ffmpeg (com MP3 via LAME) para Android e coloca em
#   out/jniLibs/<abi>/libffmpeg.so
# O nome "lib*.so" faz o Android instalar o arquivo na pasta de libs nativas do app,
# que é o único lugar de onde um app pode executar um programa (Android 10+).
#
# Uso: ANDROID_NDK_HOME=/caminho/ndk ./android/build-ffmpeg.sh [abi ...]
set -euo pipefail

FFMPEG_VERSION="${FFMPEG_VERSION:-7.1.1}"
LAME_VERSION="${LAME_VERSION:-3.100}"
API=24
ABIS=("${@:-arm64-v8a armeabi-v7a}")
ABIS=(${ABIS[@]})

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$ROOT/.ffmpeg-build"
OUT="$ROOT/out/jniLibs"
NDK="${ANDROID_NDK_HOME:?defina ANDROID_NDK_HOME}"
TC="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
JOBS="$(nproc)"

mkdir -p "$WORK" "$OUT"
cd "$WORK"

[ -f "lame-$LAME_VERSION.tar.gz" ] || curl -fsSL -o "lame-$LAME_VERSION.tar.gz" \
  "https://downloads.sourceforge.net/project/lame/lame/$LAME_VERSION/lame-$LAME_VERSION.tar.gz"
[ -f "ffmpeg-$FFMPEG_VERSION.tar.xz" ] || curl -fsSL -o "ffmpeg-$FFMPEG_VERSION.tar.xz" \
  "https://ffmpeg.org/releases/ffmpeg-$FFMPEG_VERSION.tar.xz"

for ABI in "${ABIS[@]}"; do
  case "$ABI" in
    arm64-v8a)   HOST=aarch64-linux-android;   CLANG=aarch64-linux-android$API-clang;    ARCH=aarch64; CPU=armv8-a; EXTRA="" ;;
    armeabi-v7a) HOST=arm-linux-androideabi;   CLANG=armv7a-linux-androideabi$API-clang; ARCH=arm;     CPU=armv7-a; EXTRA="--enable-neon --enable-thumb" ;;
    x86_64)      HOST=x86_64-linux-android;    CLANG=x86_64-linux-android$API-clang;     ARCH=x86_64;  CPU=x86-64;  EXTRA="--disable-asm" ;;
    *) echo "ABI desconhecida: $ABI"; exit 1 ;;
  esac
  echo "=== $ABI ==="
  PREFIX="$WORK/prefix-$ABI"
  export CC="$TC/bin/$CLANG" AR="$TC/bin/llvm-ar" RANLIB="$TC/bin/llvm-ranlib" STRIP="$TC/bin/llvm-strip" NM="$TC/bin/llvm-nm"

  # --- LAME (codificador MP3), estático
  rm -rf "lame-$LAME_VERSION" && tar -xzf "lame-$LAME_VERSION.tar.gz"
  pushd "lame-$LAME_VERSION" >/dev/null
  cp /usr/share/misc/config.sub /usr/share/misc/config.guess . 2>/dev/null || true
  ./configure --host="$HOST" --prefix="$PREFIX" --enable-static --disable-shared \
    --disable-frontend --disable-decoder --with-pic CFLAGS="-O2 -fPIC" >/dev/null
  make -j"$JOBS" >/dev/null && make install >/dev/null
  popd >/dev/null

  # --- ffmpeg (só o programa ffmpeg, bibliotecas linkadas estaticamente)
  rm -rf "ffmpeg-$FFMPEG_VERSION" && tar -xJf "ffmpeg-$FFMPEG_VERSION.tar.xz"
  pushd "ffmpeg-$FFMPEG_VERSION" >/dev/null
  ./configure \
    --prefix="$PREFIX" --target-os=android --arch="$ARCH" --cpu="$CPU" \
    --enable-cross-compile --cc="$CC" --cxx="${CC/clang/clang++}" \
    --ar="$AR" --ranlib="$RANLIB" --strip="$STRIP" --nm="$NM" \
    --sysroot="$TC/sysroot" --enable-pic --enable-static --disable-shared \
    --disable-doc --disable-debug --disable-ffplay --disable-ffprobe \
    --disable-avdevice --disable-indevs --disable-outdevs --disable-vulkan \
    --enable-small --enable-libmp3lame \
    --extra-cflags="-I$PREFIX/include -O2 -fPIC" \
    --extra-ldflags="-L$PREFIX/lib -Wl,-z,max-page-size=16384" \
    --extra-libs="-lm" $EXTRA >/dev/null
  make -j"$JOBS" ffmpeg >/dev/null
  mkdir -p "$OUT/$ABI"
  "$STRIP" -o "$OUT/$ABI/libffmpeg.so" ffmpeg
  popd >/dev/null
  ls -la "$OUT/$ABI"
done
