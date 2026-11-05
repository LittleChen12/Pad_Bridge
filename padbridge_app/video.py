# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, saved stream controls shared by the controller and worker."""
from dataclasses import asdict, dataclass
import math
import re


def mirror_size(width, height, limits=None, bound=None, fps=60):
    """Fit the encoded raster; leave desktop geometry and input coordinates intact."""
    max_w = limits.max_w if limits and limits.max_w else width
    max_h = limits.max_h if limits and limits.max_h else height
    scale = min(1.0, max_w / width, max_h / height)
    if bound:
        scale = min(scale, bound[0] / width, bound[1] / height)
    if limits and limits.max_pps:
        scale = min(scale, math.sqrt(limits.max_pps / (fps * width * height)))
    w, h = int(width * scale) // 2 * 2, int(height * scale) // 2 * 2
    if min(w, h) < 2:
        raise ValueError('接收端的解码尺寸限制过小。')
    return w, h


@dataclass(frozen=True)
class VideoOptions:
    resolution: str = 'native'
    fps: int = 60
    bitrate_mbps: int = 0  # 0 selects the tested transport default.
    force_fps: bool = False

    def __post_init__(self):
        if self.resolution != 'native':
            match = re.fullmatch(r'(\d{3,4})x(\d{3,4})', str(self.resolution))
            if not match:
                raise ValueError('分辨率请填写 native 或宽x高，例如 1920x1440。')
            w, h = map(int, match.groups())
            if not (320 <= h <= w <= 3840 and w % 8 == 0 and h % 2 == 0):
                raise ValueError('分辨率按横屏填写：320 ≤ 高 ≤ 宽 ≤ 3840；宽须为 8 的倍数，高须为偶数。')
        if type(self.fps) is not int or not 15 <= self.fps <= 120:
            raise ValueError('目标帧率须为 15～120 的整数。')
        if type(self.force_fps) is not bool:
            raise ValueError('强制目标帧率须为布尔值。')
        if type(self.bitrate_mbps) is not int or not 0 <= self.bitrate_mbps <= 50:
            raise ValueError('码率须为 1～50 Mbps 的整数，或 0（自动）。')

    @property
    def size(self):
        return None if self.resolution == 'native' else tuple(map(int, self.resolution.split('x')))

    def bitrate(self, transport):
        return (self.bitrate_mbps or (10 if transport == 'wifi' else 24)) * 1000

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data=None):
        if data is None:
            return cls()
        if not isinstance(data, dict):
            raise ValueError('画面参数格式无效。')
        return cls(**{key: data[key] for key in ('resolution', 'fps', 'bitrate_mbps', 'force_fps') if key in data})
