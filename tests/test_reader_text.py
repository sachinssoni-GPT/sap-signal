from sapsignal.publishing.text import footnotes, human_dates, reader, strip_markers


def test_markers_never_reach_readers_in_briefs():
    assert strip_markers("Talks resumed [C3, C4, C6]. Bloomberg reports X [PUB1].") == \
        "Talks resumed. Bloomberg reports X."
    assert strip_markers("A [C1] and B [C2; C9].") == "A and B."


def test_dates_read_like_dates_but_urls_and_ids_are_untouched():
    assert human_dates("Check me on 2027-02-15.") == "Check me on 15 Feb 2027."
    url = "https://readundercurrent.org/issues/2026-11-11/"
    assert human_dates(f"Read {url}") == f"Read {url}"
    assert human_dates("edition 2026-11-11-2") == "edition 2026-11-11-2"
    assert reader("By 2027-01-31 [C2] it ends") == "By 31 Jan 2027 it ends"


def test_editorial_markers_become_footnote_links():
    out = footnotes("Shipping fell [C3, C4].")
    assert '<a href="#src-c3">3</a>' in out and '<a href="#src-c4">4</a>' in out and "[C" not in out


def test_grouped_citations_count_for_the_evidence_gate():
    from sapsignal.editorial.quality_gate import cited_ids
    assert cited_ids("x [C3, C4] y [C9] z [C2;5]") == {"C3", "C4", "C9", "C2", "C5"}


def test_tidy_fixes_an_old_published_issue_and_is_idempotent():
    from sapsignal.publishing.text import tidy_newsletter
    old = ("---\ntitle: \"X\"\ndate: 2026-11-11\n---\n\n> **Today's call:** Y *(60% confident, check me on 2027-02-15.)*\n\n"
           "### 1. Head\n\nTalks [C3, C4, C6]. Bloomberg reports Z [PUB1].\n\n"
           '<h2 id="the-editorial">The editorial: X</h2>\n\nFact [C1].\n\n### Sources\n**[C1]** claim\n- r: <https://a.com/2026-11-10/x>\n')
    new = tidy_newsletter(old)
    assert "date: 2026-11-11" in new and "15 Feb 2027" in new
    assert "Talks. Bloomberg reports Z." in new and "[PUB1]" not in new
    assert '<a href="#src-c1">1</a>' in new and 'id="src-c1"' in new and "https://a.com/2026-11-10/x" in new
    assert tidy_newsletter(new) == new


def test_range_markers_are_stripped_footnoted_and_counted():
    from sapsignal.editorial.quality_gate import cited_ids
    from sapsignal.publishing.text import footnotes, strip_markers
    s = "Open until 3:45 pm [C5-C6]. Gala [C1–C3]."
    assert strip_markers(s) == "Open until 3:45 pm. Gala."
    assert cited_ids(s) == {"C1", "C2", "C3", "C5", "C6"}
    f = footnotes("x [C1-C3].")
    assert all(f'href="#src-c{i}"' in f for i in (1, 2, 3)) and "[C" not in f
