# Build the Snatcher English patches (PlayStation, Saturn, PC Engine CD) from source.
#
#   docker build -t snatcher-build .
#   docker run --rm \
#       -v "$PWD/discs:/src/discs" \
#       -v "$PWD/fonts:/src/fonts:ro" \
#       -v "$PWD/out/patched:/src/patched" \
#       -v "$PWD/out/release:/src/release" \
#       -v "$PWD/out/work:/src/work-cache" \
#       snatcher-build all --release
#
# discs/  your own dumps, laid out as `python build.py discs` does (see BUILDING.md)
# fonts/  arial.ttf arialbd.ttf impact.ttf times.ttf msgothic.ttc copied from a
#         Windows install: a few pictures are rendered in them and they cannot be
#         redistributed (lib/sysfont.py)
# The arguments are build.py's: doctor | ps1 | saturn | pce | all [--release] ...
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        xdelta3 default-jre-headless mame-tools ca-certificates curl unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# jPSXdec (the PS1 intro movie), fetched at image build time so a run needs no network
RUN mkdir -p lib/jpsxdec \
 && curl -fsSL -o /tmp/jpsxdec.zip https://github.com/m35/jpsxdec/releases/download/v2.0/jpsxdec_v2.0.zip \
 && unzip -q /tmp/jpsxdec.zip -d lib/jpsxdec \
 && rm /tmp/jpsxdec.zip

COPY . .
# work/ keeps the committed build inputs; scratch can persist across runs through
# a volume at /src/work-cache (docker/entrypoint.sh links the scratch dirs there)
RUN chmod +x docker/entrypoint.sh
ENV PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8 SNATCHER_FONTS=/src/fonts
ENTRYPOINT ["docker/entrypoint.sh"]
CMD ["doctor"]
