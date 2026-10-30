# SPDX-License-Identifier: GPL-3.0-or-later
"""Validated, saved stream controls shared by the controller and worker."""
from dataclasses import asdict, dataclass
import re


@dataclass(frozen=True)
class VideoOptions:
    resolution: str = 'native'
    fps: int = 60
    bitrate_mbps: int = 0  # 0 selects the tested transport default.

    def __post_init__(self):
        if self.resolution != 'native':
            match = re.fullmatch(r'(\d{3,4})x(\d{3,4})', str(self.resolution))
            if not match:
                raise ValueError('分辨率请填写 native 或宽x高，例如 1920x1440。')
            w, h = map(int, match.groups())
            if not (320 <= h <= w <= 3840 and w % 8 == 0 and h % 2 == 0):
                raise ValueError('分辨率按横屏填写：320 ≤ 高 ≤ 宽 ≤ 3840；宽须为 8 的倍数，高须为偶数。')
        if type(self.fps) is not int or not 15 <= self.fps <= 60:
            raise ValueError('目标帧率须为 15～60 的整数。')
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
        return cls(**{key: data[key] for key in ('resolution', 'fps', 'bitrate_mbps') if key in data})
