"""Unit-test the LLMAgent tool-use loop with an injected fake client — no API key, deterministic.

Validates that the loop wires tool_use blocks to env actions, feeds results back, and terminates on
`finish` — the control flow that a real Anthropic run exercises against a live model."""

from arena.llm import LLMAgent
from arena.registry import load_tasks
from arena.runner import run_episode


class _Block:
    def __init__(self, type, id=None, name=None, input=None):
        self.type, self.id, self.name, self.input = type, id, name, input


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeMessages:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


class _FakeClient:
    def __init__(self, responses):
        self.messages = _FakeMessages(responses)


def _tu(tid, name, **inp):
    return _Block("tool_use", id=tid, name=name, input=inp)


def _task(task_id):
    return next(t for t in load_tasks() if t.id == task_id)


def test_llm_loop_solves_signup_via_fake_client():
    # inspect -> batch the field sets + submit -> finish
    responses = [
        _Resp([_tu("1", "list_widgets")]),
        _Resp([
            _tu("2", "set_widget", identifier="Name", value="Ada"),
            _tu("3", "set_widget", identifier="Plan", value="Pro"),
            _tu("4", "set_widget", identifier="Years of experience", value=10),
            _tu("5", "set_widget", identifier="Subscribe to newsletter", value=True),
            _tu("6", "click", identifier="Create account"),
        ]),
        _Resp([_tu("7", "finish")]),
    ]
    agent = LLMAgent(client=_FakeClient(responses))
    result = run_episode(_task("signup_flow"), agent)
    assert result.solved and not result.crashed


def test_llm_loop_stops_when_model_ends_turn_without_tools():
    # a text-only response (no tool_use) ends the episode gracefully — not a crash
    agent = LLMAgent(client=_FakeClient([_Resp([_Block("text")])]))
    result = run_episode(_task("signup_flow"), agent)
    assert not result.solved and not result.crashed  # gave up, but the harness stays clean
