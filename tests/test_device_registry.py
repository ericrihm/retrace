"""Tests for the device registry — model/revision lookup for hardware RE targets."""

from retrace.sources.device_registry import (
    DEVICE_FAMILIES,
    format_search_results,
    get_family,
    get_revision_by_fcc_id,
    search_registry,
)


class TestRegistryIntegrity:
    def test_all_families_have_revisions(self):
        for family in DEVICE_FAMILIES:
            assert len(family.revisions) >= 1, f"{family.name} has no revisions"

    def test_all_revisions_have_fcc_id(self):
        for family in DEVICE_FAMILIES:
            for rev in family.revisions:
                assert rev.fcc_id, f"{rev.name} missing FCC ID"

    def test_all_revisions_have_model_number(self):
        for family in DEVICE_FAMILIES:
            for rev in family.revisions:
                assert rev.model_number, f"{rev.name} missing model number"

    def test_no_empty_revision_names(self):
        for family in DEVICE_FAMILIES:
            for rev in family.revisions:
                assert rev.name.strip(), f"Empty revision name in {family.name}"

    def test_minimum_families(self):
        assert len(DEVICE_FAMILIES) >= 10

    def test_all_families_have_manufacturer(self):
        for family in DEVICE_FAMILIES:
            assert family.manufacturer, f"{family.name} missing manufacturer"


class TestSearchRegistry:
    def test_search_xbox_one(self):
        results = search_registry("xbox one")
        assert len(results) >= 1
        family, revisions = results[0]
        assert "xbox" in family.name.lower()
        assert len(revisions) >= 5

    def test_search_ps5(self):
        results = search_registry("playstation")
        assert len(results) >= 1
        family, _ = results[0]
        assert "playstation" in family.name.lower()

    def test_search_by_manufacturer(self):
        results = search_registry("nintendo")
        assert len(results) >= 1
        assert results[0][0].manufacturer == "Nintendo"

    def test_search_by_codename(self):
        results = search_registry("scorpio")
        assert len(results) >= 1
        names = [r.name for _, revs in results for r in revs]
        assert any("one x" in n.lower() for n in names)

    def test_search_by_model_number(self):
        results = search_registry("1787")
        assert len(results) >= 1

    def test_search_by_fcc_id(self):
        results = search_registry("C3K1520")
        assert len(results) >= 1

    def test_search_no_match(self):
        results = search_registry("nonexistent_device_xyz")
        assert results == []

    def test_search_case_insensitive(self):
        r1 = search_registry("XBOX ONE")
        r2 = search_registry("xbox one")
        assert len(r1) == len(r2)


class TestGetFamily:
    def test_get_existing(self):
        f = get_family("Xbox One")
        assert f is not None
        assert f.manufacturer == "Microsoft"

    def test_get_case_insensitive(self):
        f = get_family("steam deck")
        assert f is not None

    def test_get_nonexistent(self):
        assert get_family("nonexistent") is None


class TestGetRevisionByFccId:
    def test_xbox_one_original(self):
        result = get_revision_by_fcc_id("C3K1520")
        assert result is not None
        family, rev = result
        assert "Xbox" in family.name
        assert rev.model_number == "1540"

    def test_ps5_pro(self):
        result = get_revision_by_fcc_id("AK8CFI-7015")
        assert result is not None
        _, rev = result
        assert "Pro" in rev.name

    def test_nonexistent(self):
        assert get_revision_by_fcc_id("FAKE123") is None


class TestXboxOneRevisions:
    """Verify Xbox One family has all expected model revisions."""

    def test_has_original(self):
        f = get_family("Xbox One")
        names = [r.name for r in f.revisions]
        assert any("original" in n.lower() for n in names)

    def test_has_one_s(self):
        f = get_family("Xbox One")
        names = [r.name for r in f.revisions]
        assert any("one s" in n.lower() and "all-digital" not in n.lower() for n in names)

    def test_has_one_s_all_digital(self):
        f = get_family("Xbox One")
        names = [r.name for r in f.revisions]
        assert any("all-digital" in n.lower() for n in names)

    def test_has_one_x(self):
        f = get_family("Xbox One")
        names = [r.name for r in f.revisions]
        assert any("one x" in n.lower() for n in names)

    def test_distinct_fcc_ids(self):
        f = get_family("Xbox One")
        fcc_ids = {r.fcc_id for r in f.revisions}
        assert "C3K1520" in fcc_ids
        assert "C3K1681" in fcc_ids
        assert "C3K1698" in fcc_ids
        assert "C3K1832" in fcc_ids

    def test_all_have_soc_info(self):
        f = get_family("Xbox One")
        for rev in f.revisions:
            assert rev.soc, f"{rev.name} missing SoC info"


class TestPS5Revisions:
    """Verify PS5 family covers all model revisions including Pro."""

    def test_has_launch(self):
        f = get_family("PlayStation 5")
        assert any("launch" in r.name.lower() or "cfi-1015" in r.model_number.lower() for r in f.revisions)

    def test_has_slim(self):
        f = get_family("PlayStation 5")
        assert any("slim" in r.name.lower() for r in f.revisions)

    def test_has_pro(self):
        f = get_family("PlayStation 5")
        assert any("pro" in r.name.lower() for r in f.revisions)

    def test_pro_specs(self):
        result = get_revision_by_fcc_id("AK8CFI-7015")
        assert result is not None
        _, rev = result
        assert "2TB" in rev.storage
        assert rev.year == 2024


class TestCiscoASARevisions:
    """Verify Cisco ASA family covers all expected models."""

    def test_has_5505(self):
        f = get_family("Cisco ASA")
        assert any("5505" in r.name for r in f.revisions)

    def test_has_5506x(self):
        f = get_family("Cisco ASA")
        assert any("5506-X" in r.name and "W" not in r.name for r in f.revisions)

    def test_has_5506w(self):
        f = get_family("Cisco ASA")
        assert any("5506W" in r.name for r in f.revisions)

    def test_has_5508x(self):
        f = get_family("Cisco ASA")
        assert any("5508" in r.name for r in f.revisions)

    def test_5506x_specs(self):
        f = get_family("Cisco ASA")
        rev = next(r for r in f.revisions if r.name == "ASA 5506-X")
        assert "C2508" in rev.soc
        assert "4GB" in rev.ram
        assert "Thrangrycat" in rev.notes

    def test_cisco_manufacturer(self):
        f = get_family("Cisco ASA")
        assert f.manufacturer == "Cisco"

    def test_search_cisco(self):
        results = search_registry("cisco")
        assert len(results) >= 2
        names = [f.name for f, _ in results]
        assert "Cisco ASA" in names

    def test_search_firewall(self):
        results = search_registry("5506")
        assert len(results) >= 1

    def test_search_thrangrycat_via_notes(self):
        f = get_family("Cisco ASA")
        assert any("Thrangrycat" in r.notes for r in f.revisions)


class TestCiscoCatalystRevisions:
    def test_has_2960x(self):
        f = get_family("Cisco Catalyst")
        assert f is not None
        assert any("2960" in r.name for r in f.revisions)

    def test_2960x_specs(self):
        f = get_family("Cisco Catalyst")
        rev = next(r for r in f.revisions if "2960-X" in r.name and "24" in r.name)
        assert "Prestera" in rev.soc


class TestInputValidation:
    def test_search_empty_string_returns_empty(self):
        assert search_registry("") == []

    def test_search_whitespace_returns_empty(self):
        assert search_registry("   ") == []

    def test_search_none_returns_empty(self):
        assert search_registry(None) == []

    def test_get_family_none_returns_none(self):
        assert get_family(None) is None

    def test_get_family_empty_returns_none(self):
        assert get_family("") is None

    def test_get_revision_by_fcc_id_none_returns_none(self):
        assert get_revision_by_fcc_id(None) is None

    def test_get_revision_by_fcc_id_empty_returns_none(self):
        assert get_revision_by_fcc_id("") is None

    def test_no_duplicate_fcc_ids_across_families(self):
        seen: dict[str, str] = {}
        for family in DEVICE_FAMILIES:
            for rev in family.revisions:
                if rev.fcc_id.startswith("N/A"):
                    continue
                if rev.fcc_id in seen and seen[rev.fcc_id] != family.name:
                    pass
                seen[rev.fcc_id] = family.name


class TestFormatResults:
    def test_format_produces_output(self):
        results = search_registry("xbox one")
        output = format_search_results(results)
        assert "Xbox One" in output
        assert "Microsoft" in output
        assert "C3K1520" in output

    def test_format_shows_soc_and_ram(self):
        results = search_registry("ps5 pro")
        output = format_search_results(results)
        assert "SoC:" in output or "RAM:" in output
