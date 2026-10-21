#!/usr/bin/env bash
# Builds TokenToken-Setup-x.y.z.exe on Linux.
# Needs: nsis, mingw-w64, curl.  (apt-get install nsis mingw-w64)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"; B="$HERE/build"
PBS="https://github.com/astral-sh/python-build-standalone/releases/download/20250612/cpython-3.12.11%2B20250612-x86_64-pc-windows-msvc-install_only.tar.gz"
rm -rf "$B"; mkdir -p "$B/app"
curl -sSL "$PBS" | tar xz -C "$B"; mv "$B/python" "$B/runtime"
( cd "$B/runtime"; find . -name '*.pdb' -delete
  rm -rf include libs Scripts Lib/test Lib/idlelib Lib/ensurepip Lib/lib2to3 Lib/turtledemo Lib/site-packages/pip* \
         tcl/tix8.4.3 tcl/nmake tcl/*.lib tcl/*.sh DLLs/_test*.pyd DLLs/_ctypes_test.pyd DLLs/xxlimited*.pyd Lib/unittest Lib/pydoc_data
  find . -name __pycache__ -prune -exec rm -rf {} + )
cp "$ROOT"/{tokenmon.pyw,usage_core.py,tokentoken_mcp.py,tokentoken_agent.py,install_mcp.py,README.md} "$HERE/tokentoken.ico" "$B/app/"
cp "$HERE/tokentoken.ico" "$HERE/installer.nsi" "$B/"
( cd "$HERE"; x86_64-w64-mingw32-windres launcher.rc -O coff -o "$B/launcher.res"
  x86_64-w64-mingw32-gcc -O2 -s -municode -mwindows launcher.c "$B/launcher.res" -o "$B/TokenToken.exe" )
( cd "$B"; makensis -V2 installer.nsi )
cp "$B"/TokenToken-Setup-*.exe "$ROOT/"; echo "done: $(ls "$ROOT"/TokenToken-Setup-*.exe)"
