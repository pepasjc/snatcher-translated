#!/bin/sh
# Container entry: run build.py with the given arguments.
# A volume at /src/work-cache keeps the build's scratch (extractions, the
# repainted movie frames, references) between runs: the image's committed
# build inputs are copied into it fresh each time, then work/ points there.
set -e
cd /src
if [ -d /src/work-cache ]; then
    find /src/work -maxdepth 1 -type f -exec cp -f {} /src/work-cache/ \;
    rm -rf /src/work
    ln -s /src/work-cache /src/work
fi
exec python build.py "$@"
