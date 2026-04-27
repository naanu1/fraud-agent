from langgraph.graph import StateGraph, END
from state import State
from agents import researcher, analyst, evaluator
from utils import write_reports
import logging

log = logging.getLogger("graph")
_NOOP = lambda **kw: None


def _wrap(fn, emit=_NOOP):
    def node(d: dict) -> dict:
        s = State.model_validate(d)
        s = fn(s, emit=emit)
        return s.model_dump()
    return node


def _route(d: dict) -> str:
    return "conclude" if d.get("concluded") else "researcher"


def _conclude(d: dict) -> dict:
    s = State.model_validate(d)
    write_reports(s)
    return d


def build(emit=_NOOP):
    g = StateGraph(dict)
    g.add_node("researcher", _wrap(researcher, emit))
    g.add_node("analyst",    _wrap(analyst, emit))
    g.add_node("evaluator",  _wrap(evaluator, emit))
    g.add_node("conclude",   _conclude)
    g.set_entry_point("researcher")
    g.add_edge("researcher", "analyst")
    g.add_edge("analyst",    "evaluator")
    g.add_conditional_edges("evaluator", _route,
                            {"researcher": "researcher", "conclude": "conclude"})
    g.add_edge("conclude", END)
    return g.compile()


def run(state: State, emit=_NOOP) -> State:
    result = build(emit).invoke(state.model_dump())
    return State.model_validate(result)
