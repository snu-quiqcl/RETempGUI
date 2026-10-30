from labremote.runtime.io import Context


def all_off(p):
    ctx=Context()
    ctx.assign(p.ch1.output,False)
    ctx.assign(p.ch2.output,False)
    ctx.assign(p.ch3.output,False)
