# hrtim.py - Renode stub of HRTIM1 (0x40016800, 3 KB; RM0440 Rev 9 chapter
# 28). Not a timer model: nothing counts and no edge is produced. Registers
# read back what was written, except:
#   ISR   0x388  DLLRDY (bit 16) always set, so the DLL calibration poll
#                finishes (28.3.24); FLT1..6 (bits 0..5) set by a fault.
#   ICR   0x38C  write 1 clears the matching ISR bit.
#   OENR  0x394  write 1 sets TA1OEN/TA2OEN (bits 0, 1); reads the enables.
#   ODISR 0x398  write 1 clears an enable.  ODSR 0x39C reads the disables.
# Sim-only fault inject at 0xBF0 (unused in the block): writing n (1..6)
# asserts FLTn once. If FLTn is enabled in FLTINR1/2 (FLTnE) and on Timer A
# (TIMAFLTR 0xE8, FLTnEN bit n-1), ISR.FLTn sets and both Timer A outputs
# are disabled, as the hardware does (28.3.17). A fault the firmware did not
# enable does nothing, so a trip here proves the enables were written.
ISR, ICR, OENR, ODISR, ODSR = 0x388, 0x38C, 0x394, 0x398, 0x39C
FLTINR1, FLTINR2, TA_FLT, INJECT = 0x3D0, 0x3D4, 0xE8, 0xBF0
TA_OUTS = 0x3                                # TA1OEN | TA2OEN
if request.IsInit:
    regs = {}
    st = {"isr": 0, "oen": 0}
elif request.IsRead:
    off = request.Offset
    if off == ISR:
        v = st["isr"] | (1 << 16)
    elif off == OENR:
        v = st["oen"]
    elif off == ODSR:
        v = TA_OUTS & ~st["oen"]                   # disabled = not enabled (Timer A only)
    elif off in (ICR, ODISR, INJECT):
        v = 0
    else:
        v = regs.get(off, 0)
    request.Value = v
else:
    off, v = request.Offset, request.Value
    if off == ICR:
        st["isr"] &= ~v
    elif off == OENR:
        st["oen"] |= v & TA_OUTS
    elif off == ODISR:
        st["oen"] &= ~(v & TA_OUTS)
    elif off == INJECT and 1 <= v <= 6:
        n = v - 1
        inr = regs.get(FLTINR1, 0) if n < 4 else regs.get(FLTINR2, 0)
        input_on = (inr >> (8 * (n % 4))) & 1
        if input_on and (regs.get(TA_FLT, 0) >> n) & 1:
            st["isr"] |= 1 << n
            st["oen"] &= ~TA_OUTS
    else:
        regs[off] = v
