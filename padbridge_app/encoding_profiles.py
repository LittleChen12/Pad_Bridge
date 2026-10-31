# SPDX-License-Identifier: GPL-3.0-or-later
"""GStreamer 1.24 profiles, kept separate from capture and session lifecycle."""
import math


ENCODERS = ('nvcudah264enc', 'nvh264enc', 'x264enc')


def conversion_fragment(encoder, size=None):
    cuda = encoder == 'nvcudah264enc'
    caps = 'video/x-raw(memory:CUDAMemory)' if cuda else 'video/x-raw'
    caps += ',format=NV12'
    if size:
        caps += f',width={size[0]},height={size[1]},pixel-aspect-ratio=1/1'
    if cuda:
        # Upload the native BGRx capture once; convert and scale in device memory.
        return 'cudaupload name=conv ! cudaconvertscale ! ' + caps
    return 'videoconvert name=conv n-threads=2 ! ' + ('videoscale ! ' if size else '') + caps


def encoder_fragment(name, fps, bitrate=24000, wifi=False):
    gop = fps * (10 if wifi else 2)
    vbv = max(1, math.ceil(bitrate * 4 / fps))  # Four frames, as in the Windows backend.
    if name == 'nvcudah264enc':
        return (f'{name} name=enc preset=p4 tune=ultra-low-latency rate-control=cbr '
                f'bitrate={bitrate} b-frames=0 rc-lookahead=0 zero-reorder-delay=true '
                f'gop-size={gop} strict-gop=true vbv-buffer-size={vbv} repeat-sequence-header=true')
    if name == 'nvh264enc':
        return (f'{name} name=enc preset=low-latency-hp rc-mode=cbr bitrate={bitrate} '
                f'zerolatency=true bframes=0 rc-lookahead=0 gop-size={gop} '
                f'strict-gop=true vbv-buffer-size={vbv}')
    if name == 'x264enc':
        return (f'{name} name=enc tune=zerolatency speed-preset=ultrafast bitrate={bitrate} '
                f'bframes=0 key-int-max={gop} byte-stream=true vbv-buf-capacity={math.ceil(4000/fps)}')
    raise ValueError(name)
