from cartographer import tf_space
from cartographer.diagram_model import Box, Diagram, Edge, Legend, Title
from cartographer.tf_space import Widening, fit, widenings


def _diagram(nodes: tuple[Box, ...], edges: tuple[Edge, ...]) -> Diagram:
    return Diagram(Title(0, 0, 0, 0, ""), nodes, edges, Legend(0, 0, 0, 0, "", (), ""))


def _run(label: str, at: float = 0) -> Edge:
    return Edge("a", "b", label, points=((330, 94), (330, 386)), out=(0.5, 1), into=(0.5, 0), exact=True, at=at)


def test_a_caption_on_a_vertical_run_gets_room_across_it() -> None:
    nodes = (Box("a", "", 300, 20, 60, 60), Box("b", "", 300, 400, 60, 60), Box("c", "", 370, 200, 60, 60),
             Box("d", "", 240, 200, 60, 60))
    cuts = widenings(_diagram(nodes, (_run("a long caption text"),)))
    assert [(c.axis, c.between) for c in cuts] == [(0, (300, 370))]


def test_a_caption_beside_another_gets_room_along_its_run_for_both() -> None:
    nodes = (Box("a", "", 20, 300, 60, 60), Box("b", "", 300, 300, 60, 60))
    edges = (Edge("a", "b", "a caption here", points=((94, 330), (286, 330)), out=(1, 0.5), into=(0, 0.5), exact=True),
             Edge("b", "a", "the other caption", points=((286, 318), (94, 318)), out=(0, 0.5), into=(1, 0.5),
                  out_off=(0, -12), into_off=(0, -12), exact=True))
    cuts = widenings(_diagram(nodes, edges))
    assert any(c.axis == 0 and c.extra > 0 for c in cuts)


def test_fit_keeps_the_round_with_the_fewest_defects(monkeypatch) -> None:
    good, bad = (_diagram((Box(n, "", 0, 0),), ()) for n in ("good", "bad"))
    routed = iter([good, bad, bad, bad])
    monkeypatch.setattr(tf_space, "route", lambda d: next(routed))
    monkeypatch.setattr(tf_space, "widenings", lambda d: [Widening(0, 1, 1, (0, 2))])
    monkeypatch.setattr(tf_space, "stats", lambda d: type("S", (), {"violations": 1})())
    monkeypatch.setattr(tf_space, "defects", lambda d: (0, 0) if d is good else (1, 0))
    assert fit(good)[0] is good
