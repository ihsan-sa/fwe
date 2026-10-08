# rcc.py - Renode stub of the STM32G4 RCC: registers read back what was
# written, with the ready flags following their enables, so clock.c's polls
# finish. Not a clock model: frequencies are fixed in g474.repl.
if request.IsInit:
    regs = {0x00: 0x00000500}  # CR: HSION | HSIRDY after reset
elif request.IsRead:
    v = regs.get(request.Offset, 0)
    if request.Offset == 0x00:    # CR: HSIRDY(10) = HSION(8), HSERDY(17) = HSEON(16), PLLRDY(25) = PLLON(24)
        v = (v & ~((1 << 10) | (1 << 17) | (1 << 25))) | (((v >> 8) & 1) << 10) \
            | (((v >> 16) & 1) << 17) | (((v >> 24) & 1) << 25)
    elif request.Offset == 0x08:  # CFGR: SWS(3:2) = SW(1:0)
        v = (v & ~0xC) | ((v & 0x3) << 2)
    elif request.Offset == 0x94:  # CSR: reset cause reads as a pin reset (PINRSTF)
        v = v | (1 << 26)
    request.Value = v
else:
    regs[request.Offset] = request.Value
