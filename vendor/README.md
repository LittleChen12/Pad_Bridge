# Vendored dependencies

## OpenDisplay for X11

- Upstream: https://github.com/cray2015/opendisplay-x11
- Author: Vibhanshu Biswas
- Revision: `0301158192212c5aa7ad46d5901048251a46e936`
- License: GPL-3.0-or-later; original headers, `LICENSE`, `LICENSES/` and `REUSE.toml` are retained.

`opendisplay-x11/` contains the `odx11` runtime modules used by PadBridge and the five upstream
test modules exercised by PadBridge. The unused upstream application entry point
(`__main__.py`), GUI (`gui.py`), GUI checks (`checks.py`) and settings dialog
(`settings.py`) are omitted: PadBridge supplies its own entry point and interface.
It is an ordinary source snapshot, not a Git
submodule, so a normal clone and a source archive include the dependency. Upstream
installer scripts, development tools, CI, performance reports and Git metadata are
not included. The original sources remain available at the pinned upstream revision.

Local changes are confined to `odx11/daemon.py` and recorded in
[`opendisplay-x11.patch`](opendisplay-x11.patch):

- Allow transport-specific socket configuration.
- Calculate decoder throughput from the encoded raster, preserving source coordinates.
- Announce stream configuration before video and resynchronize cursor state after the first frame.
- Publish encoded dimensions and target frame rate.
- Inject an ordered socket writer without blocking GLib on network sends.
- Publish bounded receiver statistics and rolling pipeline/sender timings only while streaming.

Display creation, read-only mirroring, encoding, capture recovery and the controller
are implemented in `padbridge_app/`. Refresh the patch and run `./test.sh --unit-only`
when updating this snapshot. Do not run upstream installers as part of PadBridge setup.
