"""Identity snapshots and controls shared by daily/crafting operations."""
def same_identity(app, client, slot):
    save = getattr(app, 'current_save', None)
    return (getattr(app, 'client', None) is client and save is not None
            and save.get('index') == slot and not save.get('unavailable') and not save.get('empty'))

def require_identity(app, client, slot):
    if not same_identity(app, client, slot):
        raise RuntimeError('账号或存档已改变，已阻止继续发送请求')

class IdentityBoundFlow:
    def __init__(self, flow, check):
        self._flow, self._check = flow, check
    def __getattr__(self, name):
        return getattr(self._flow, name)
    def request(self, *args, **kwargs):
        self._check()
        return self._flow.request(*args, **kwargs)

def identity_busy(app):
    return any(getattr(app, key, False) for key in
               ('_daily_running', '_craft_job_active', 'running', '_jiuzhuan_running', '_halloween_busy', '_feed_dog_busy'))

def lock_controls(app, locked):
    names = ('btn_login', 'combo_save', '_account_choice')
    if locked:
        saved = {}
        for name in names:
            widget = getattr(app, name, None)
            if widget is None: continue
            saved[name] = str(widget.cget('state'))
            widget.config(state='disabled')
        app._identity_control_states = saved
    else:
        for name, state in getattr(app, '_identity_control_states', {}).items():
            widget = getattr(app, name, None)
            if widget is not None: widget.config(state=state)
        app._identity_control_states = {}
