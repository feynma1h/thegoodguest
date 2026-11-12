"""Reading a needs file: the vocabulary is closed and every piece must be covered."""
import pytest

from needs_fixtures import bedroom_needs
from rooms import bedroom
from thegoodguest_room_guide.model import room_from_scene
from thegoodguest_room_guide.needs import (
    Need, NeedsError, default_needs, entrances, parse_needs, with_change, zones,
)


def room():
    return room_from_scene(bedroom().scene())


def test_reads_a_well_formed_file():
    needs = parse_needs(room(), bedroom_needs())
    assert needs.moves("bed") == "heavy"
    assert needs.fixed_ids() == {"door", "window"}
    assert sorted(needs.followers("bed")) == ["bedside", "bedside_2"]
    assert entrances(room(), needs) == ["door"]


def test_every_piece_must_be_covered():
    data = bedroom_needs()
    del data["pieces"]["dresser"]
    with pytest.raises(NeedsError) as err:
        parse_needs(room(), data)
    assert "no entry for dresser" in str(err.value)


def test_the_vocabulary_is_closed():
    data = bedroom_needs()
    data["pieces"]["bed"]["needs"].append({"need": "feng_shui", "strength": "hard", "why": "x"})
    data["pieces"]["dresser"]["needs"][1]["posture"] = "kneeling"
    with pytest.raises(NeedsError) as err:
        parse_needs(room(), data)
    text = str(err.value)
    assert "'feng_shui' is not one of" in text and "'kneeling' is not one of" in text


def test_shell_pieces_cannot_be_declared_movable():
    data = bedroom_needs()
    data["pieces"]["door"]["moves"] = "yes"
    with pytest.raises(NeedsError):
        parse_needs(room(), data)


def test_rehang_needs_something_to_hang_over():
    b = bedroom()
    b.on_wall("mirror", "mirror", "wall_+z", 1.0, 1.0, (0.6, 0.8, 0.03))
    r = room_from_scene(b.scene())
    data = bedroom_needs()
    data["pieces"]["mirror"] = {"moves": "rehang", "why": "it hangs over the dresser"}
    with pytest.raises(NeedsError):
        parse_needs(r, data)
    data["pieces"]["mirror"]["with"] = [{"piece": "dresser", "how": "over", "strength": "soft",
                                         "why": "a mirror over the dresser is where you dress"}]
    assert parse_needs(r, data).moves("mirror") == "rehang"


def test_other_carries_its_own_estimate_and_nothing_else_does():
    data = bedroom_needs()
    data["pieces"]["bed"]["needs"].append(
        {"need": "other", "side": "back", "depth_estimate_m": 0.2, "strength": "soft",
         "what": "headboard cushions", "why": "the cushions lean back"})
    needs = parse_needs(room(), data)
    other = [z for z in zones(room(), needs) if z.need == "other"]
    assert len(other) == 1 and other[0].estimate and other[0].hard == pytest.approx(0.2)
    assert not any(z.estimate for z in zones(room(), needs) if z.need != "other")


def test_zone_depths_come_from_the_piece_or_the_rulebook():
    needs = parse_needs(room(), bedroom_needs())
    by = {(z.piece, z.need, z.side): z for z in zones(room(), needs)}
    assert by[("door", "open", "front")].hard == pytest.approx(0.9)        # the leaf's width
    assert by[("dresser", "open", "front")].hard == pytest.approx(0.45)    # the drawer's depth
    assert by[("dresser", "use", "front")].comfortable == pytest.approx(0.9)
    assert {s for (p, n, s) in by if p == "bed"} == {"left", "right"}


def test_bonded_pieces_may_stand_in_each_others_zones():
    needs = parse_needs(room(), bedroom_needs())
    bed_zone = next(z for z in zones(room(), needs) if z.piece == "bed")
    assert {"bedside", "bedside_2", "lamp"} <= bed_zone.exempt


def test_no_bond_excuses_what_stands_in_heat_air_or_a_doorway():
    """A heater 'near' a sofa warms it; the sofa still mustn't stand in its heat."""
    data = bedroom_needs()
    data["pieces"]["dresser"]["needs"].append({"need": "heat", "side": "front", "strength": "hard", "why": "a radiator"})
    data["pieces"]["bed"]["with"] = [{"piece": "dresser", "how": "near", "strength": "soft", "why": "warmth"}]
    data["pieces"]["dresser"]["with"] = [{"piece": "bed", "how": "beside", "strength": "soft", "why": "close by"}]
    zs = {(z.piece, z.need): z for z in zones(room(), parse_needs(room(), data))}
    assert "bed" not in zs["dresser", "heat"].exempt
    assert "bed" not in zs["dresser", "open"].exempt, "only a seat at a piece is pulled away to open it"
    assert "dresser" in zs["bed", "get_in"].exempt


def test_bonds_that_cannot_be_true_are_set_aside_and_listed():
    from thegoodguest_room_guide.rules_pass import needs_to_json, settle_bonds
    data = bedroom_needs()
    data["pieces"]["lamp"]["with"] = [{"piece": "bedside", "how": "at", "strength": "hard", "why": "stands on it"}]
    data["pieces"]["dresser"]["with"] = [{"piece": "bed", "how": "over", "strength": "soft", "why": "faces it"}]
    data["pieces"]["bedside_2"]["with"][0]["how"] = "at"         # not where it stands, but it could be
    needs = settle_bonds(room(), parse_needs(room(), data))
    assert needs.pieces["lamp"].bonds == () and needs.pieces["dresser"].bonds == ()
    assert [b.how for b in needs.pieces["bedside_2"].bonds] == ["at"]
    assert len(needs.ignored) == 2 and needs_to_json(needs)["ignored"] == list(needs.ignored)


def test_defaults_fix_the_shell_and_let_everything_else_move():
    needs = default_needs(room())
    assert needs.fixed_ids() == {"door", "window"}
    assert needs.moves("bed") == "yes"
    assert entrances(room(), needs) == ["door"]


def test_relaxing_one_side_keeps_the_other():
    needs = parse_needs(room(), bedroom_needs())
    one = with_change(needs, "bed", drop="get_in", side="right")
    assert [(n.need, n.side) for n in one.needs_of("bed")] == [("get_in", "left")]
    assert not with_change(needs, "bed", drop="get_in").needs_of("bed")


def test_a_person_can_relax_a_need():
    needs = parse_needs(room(), bedroom_needs())
    relaxed = with_change(needs, "door", drop="open")
    assert not relaxed.needs_of("door", "open") and relaxed.needs_of("door", "pass")
    added = with_change(relaxed, "door", add=Need("open", "front", "soft", "it opens out", "", "hinged"))
    assert added.needs_of("door", "open")[0].strength == "soft"
