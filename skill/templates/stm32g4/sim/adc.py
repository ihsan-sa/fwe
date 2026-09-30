# adc.py - Renode stub of ADC1/ADC2 + common (0x50000000, 0x400): registers
# read back what was written, every conversion is instantly done (ISR all
# flags set; CR's ADCAL/ADSTART/JADSTART/ADDIS self-clear) and every data
# register (DR, JDR1-4) reads mid-scale 2048. So currents read ~0 A and the
# bus ~26 V: a quiet board, no faults. It is a stub, not an ADC model.
if request.IsInit:
    regs = {}
elif request.IsRead:
    off = request.Offset & 0xFF
    v = regs.get(request.Offset, 0)
    if off == 0x00:                          # ISR
        v = 0x7FF
    elif off == 0x08:                        # CR
        v = v & ~((1 << 31) | (1 << 1) | (1 << 2) | (1 << 3))
    elif off in (0x40, 0x80, 0x84, 0x88, 0x8C) and request.Offset < 0x300:
        v = 2048                             # DR, JDR1..4
    request.Value = v
else:
    regs[request.Offset] = request.Value
