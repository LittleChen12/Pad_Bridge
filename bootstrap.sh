#!/bin/bash
# Download distro packages into this folder without changing installed packages.
set -euo pipefail
cd -- "$(dirname -- "$0")"
mkdir -p .cache runtime gst-plugins
packages=(python3-xlib gstreamer1.0-plugins-bad libgstreamer-plugins-bad1.0-0 gir1.2-gst-plugins-base-1.0 gir1.2-ayatanaappindicator3-0.1)
(
    cd .cache
    apt-get download "${packages[@]}"
)
for name in "${packages[@]}"; do
    for package in .cache/"${name}"_*.deb; do
        dpkg-deb -x "$package" runtime
    done
done
for plugin in nvcodec videoparsersbad; do
    ln -sf "../runtime/usr/lib/x86_64-linux-gnu/gstreamer-1.0/libgst${plugin}.so" "gst-plugins/libgst${plugin}.so"
done
printf '%s\n' 'Dependencies are ready. Run ./padbridge to open the controller.'
