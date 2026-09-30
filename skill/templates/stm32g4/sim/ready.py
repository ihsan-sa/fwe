# ready.py - a status register whose every read has all bits set, for the
# "ready" flags the firmware polls (DAC3 SR). Writes are dropped.
if request.IsRead:
    request.Value = 0xFFFFFFFF
