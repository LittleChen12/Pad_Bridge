#!/bin/bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
case "${1:-}" in
    ""|--unit-only) ;;
    *) printf '%s\n' 'Usage: ./test.sh [--unit-only]' >&2; exit 2 ;;
esac
export PYTHONPATH="$PWD:$PWD/vendor/opendisplay-x11:$PWD/runtime/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"
/usr/bin/python3 -m unittest discover -s tests -v
(
    cd vendor/opendisplay-x11
    export PYTHONPATH="$PWD:$PWD/../../runtime/usr/lib/python3/dist-packages"
    /usr/bin/python3 -m pytest -q --log-level=INFO tests/test_protocol.py tests/test_annexb.py tests/test_session.py tests/test_usbmux.py tests/test_daemon_loop.py
)
if [[ "${1:-}" != --unit-only ]]; then
    ./padbridge encoder-test
fi
