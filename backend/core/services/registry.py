"""Every action the dashboards can call is registered here by name (the name the page uses, for example "pay_bill")."""
RPC = {}


def rpc(name=None):
    def deco(fn):
        RPC[name or fn.__name__] = fn
        return fn
    return deco
