# SPDX-License-Identifier: GPL-3.0-or-later
"""PyAV/FFmpeg H.264 encoding with a tested NVENC -> x264 fallback."""
from fractions import Fraction
import logging
from odx11.annexb import Normaliser

log = logging.getLogger(__name__)


class Encoder:
    def __init__(self, name, size, fps, bitrate, input_format=None):
        import av
        self.av = av
        self.name, self.size, self.fps = name, size, fps
        self.input_format = input_format or ('bgra' if name == 'h264_nvenc' else 'yuv420p')
        self.normalizer = Normaliser()
        self.count = 0
        self.force_keyframe = False
        ctx = av.CodecContext.create(name, 'w')
        ctx.width, ctx.height = size
        ctx.pix_fmt = self.input_format
        ctx.time_base = Fraction(1, fps)
        ctx.framerate = Fraction(fps, 1)
        ctx.bit_rate = bitrate * 1000
        ctx.gop_size = fps * 2
        ctx.max_b_frames = 0
        if name == 'h264_nvenc':
            # Periodic full IDRs with a one-frame VBV made a static native-size
            # desktop visibly blur/pulse every two seconds. Gradual refresh
            # distributes that work, while an explicit receiver kf still forces
            # a real IDR. VBV is a rate-control budget, not a queued frame buffer;
            # delay=0, no lookahead and no B-frames retain immediate output.
            ctx.options = {'preset': 'p4', 'tune': 'ull', 'zerolatency': '1',
                           'rc': 'cbr', 'forced-idr': '1', 'delay': '0', 'rc-lookahead': '0',
                           'intra-refresh': '1',
                           'profile': 'high',
                           'bufsize': str(max(1, bitrate*1000*4//fps))}
        else:
            ctx.thread_count = 2
            ctx.options = {'preset': 'ultrafast', 'tune': 'zerolatency',
                           'x264-params': 'repeat-headers=1:annexb=1:scenecut=0',
                           'profile': 'baseline'}
        ctx.open()
        self.context = ctx

    def encode(self, frame):
        # NVENC accepts the captured BGRA raster directly and converts to 4:2:0
        # on the GPU. CPU conversion is only needed for the compatibility path.
        frame = frame.reformat(width=self.size[0], height=self.size[1], format=self.input_format, threads=4)
        frame.pts, frame.time_base = self.count, Fraction(1, self.fps)
        self.count += 1
        if self.force_keyframe:
            frame.pict_type = self.av.video.frame.PictureType.I
            self.force_keyframe = False
        output = []
        for packet in self.context.encode(frame):
            au, idr = self.normalizer.access_unit(bytes(packet))
            if au:
                output.append((au, idr))
        return output

    def encode_bgra(self, pixels, width, height):
        import numpy as np
        pixels = memoryview(pixels).cast('B')
        array = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, 4)
        # PyAV keeps the array alive. Capture cannot reuse this storage until
        # synchronous, zero-delay encode returns; there is no second CPU copy.
        frame = self.av.VideoFrame.from_numpy_buffer(array, format='bgra')
        return self.encode(frame)

    def close(self):
        # Releasing the CodecContext also releases the NVENC session. Delayed
        # packets are discarded only when this entire connection/stream retires.
        self.context = None


def create_encoder(size=(1280, 720), fps=30, bitrate=8000):
    import av
    errors = []
    for name, input_format in (('h264_nvenc', 'bgra'), ('h264_nvenc', 'yuv420p'), ('libx264', 'yuv420p')):
        encoder = None
        try:
            encoder = Encoder(name, size, fps, bitrate, input_format)
            # Test real encode, not just whether FFmpeg advertises the codec.
            frame = av.VideoFrame(*size, input_format)
            for plane in frame.planes:
                plane.update(bytes(plane.buffer_size))
            packets = []
            for _ in range(3):
                packets.extend(encoder.encode(frame))
            if not any(idr for _, idr in packets):
                raise RuntimeError('编码器没有输出 H.264 关键帧')
            encoder.close()
            return Encoder(name, size, fps, bitrate, input_format)
        except Exception as exc:
            errors.append(f'{name}/{input_format}: {exc}')
            log.info('编码器不可用：%s', errors[-1])
            if encoder:
                encoder.close()
    raise RuntimeError('没有可用的 H.264 编码器：' + '; '.join(errors))


def select_encoder():
    encoder = create_encoder()
    try:
        return encoder.name
    finally:
        encoder.close()
