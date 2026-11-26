"""Regression checks for quick-task dispatch; no GUI, network, or game account required."""
import ast
from pathlib import Path
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_dispatch():
    tree = ast.parse((ROOT / 'zm4_toolbox.py').read_text(encoding='utf-8-sig'))
    app = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ToolBoxApp')
    funcs = [n for n in app.body if isinstance(n, ast.FunctionDef) and n.name in ('_quick_next', '_quick_wait')]
    specs = next(n.value for n in app.body if isinstance(n, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == 'QUICK_TASKS' for t in n.targets))
    env = {}
    exec(compile(ast.Module(body=funcs, type_ignores=[]), str(ROOT / 'zm4_toolbox.py'), 'exec'), env)
    return env, ast.literal_eval(specs)


class Button:
    def __init__(self, callback=lambda: None):
        self.callback = callback
    def instate(self, states):
        return False
    def config(self, **kwargs):
        pass
    def invoke(self):
        self.callback()


class Loop:
    def __init__(self):
        self.callbacks = []
    def after(self, delay, callback):
        self.callbacks.append(callback)
    def drain(self):
        for _ in range(1000):
            if not self.callbacks:
                return
            self.callbacks.pop(0)()
        raise AssertionError('Queue did not finish')


class DispatchTests(unittest.TestCase):
    def execute(self, specs, object_task=False):
        env, _ = load_dispatch()
        app = types.SimpleNamespace(root=Loop(), _quick_stopping=False, _quick_active=True,
                                    _quick_queue=list(specs), QUICK_PREPARE={},
                                    btn_quick_run=Button(), btn_quick_stop=Button(),
                                    lbl_quick_status=Button())
        started, finished, called, reports = [], [], [], []
        app._log = lambda text: None
        app._quick_tag = lambda: '[test]'
        app._quick_begin_item = started.append
        app._quick_end_item = lambda label, *args: finished.append(label)
        app._quick_restore_msgbox = lambda: None
        app._quick_report = lambda: reports.append(True)
        app._quick_next = types.MethodType(env['_quick_next'], app)
        app._quick_wait = types.MethodType(env['_quick_wait'], app)
        for spec in specs:
            key, label, method, button = spec[:4]
            setattr(app, method, lambda k=key: called.append(k))
            setattr(app, button, Button())
        expected = [s[0] for s in specs]
        if object_task:
            button = Button(lambda: called.append('favorite'))
            app._quick_queue.append(types.SimpleNamespace(key='favorite', label='收藏按钮',
                                                          run=button.invoke, button=button))
            expected.append('favorite')
        app._quick_next()
        app.root.drain()
        self.assertEqual(called, expected)
        self.assertEqual(len(started), len(expected))
        self.assertEqual(finished, started)
        self.assertFalse(app._quick_active)
        self.assertEqual(reports, [True])

    def test_four_field_task(self):
        self.execute([('old', '原有任务', 'run_old', 'button_old')])

    def test_five_field_task_keeps_description(self):
        spec = ('new', '新任务', 'run_new', 'button_new', '补充说明')
        self.execute([spec])
        self.assertEqual(spec[4], '补充说明')

    def test_all_production_tasks(self):
        _, specs = load_dispatch()
        self.assertTrue(any(s[0] == 'fuguolai' and len(s) == 5 for s in specs))
        self.execute(specs)

    def test_mixed_tasks_and_daily_favorite_button(self):
        self.execute([('old', '原有任务', 'run_old', 'button_old'),
                      ('new', '新任务', 'run_new', 'button_new', '说明')], object_task=True)


if __name__ == '__main__':
    unittest.main()
