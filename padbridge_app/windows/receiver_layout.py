# SPDX-License-Identifier: GPL-3.0-or-later
"""Remember the last decoded raster so aspect changes can rebuild legacy iOS views."""
from . import storage


class LayoutHistory:
    def __init__(self, path=None):
        self.path = path or storage.RUNTIME / 'receiver-layout.json'
        self.previous = storage.read_json(self.path)

    def needs_reset(self, receiver_id, size):
        previous = self.previous
        old = previous.get('size')
        if (not receiver_id or receiver_id != previous.get('receiver_id') or
                not isinstance(old, list) or len(old) != 2 or
                any(type(n) is not int or n < 2 for n in old)):
            return False
        # Encoder alignment can round 4:3 to e.g. 266x200; that is not a new
        # view shape. A real mirror/extend or orientation change is much larger.
        left, right = old[0]*size[1], old[1]*size[0]
        return abs(left-right) > max(left, right)*0.01

    def remember(self, receiver_id, size):
        if not receiver_id:
            return
        record = {'receiver_id': receiver_id, 'size': list(size)}
        if record != self.previous:
            storage.write_json(self.path, record)
            self.previous = record
