"""Hydra FTL Map tests. A synthetic lakes page shaped like HMDA's (made-up lakes, IDs and villages)
and a synthetic water-body survey; the portal itself is faked."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.errors import BAD_INPUT, NOT_FOUND, PORTAL_DOWN, PORTAL_TIMEOUT, PortalError
from backend.routers import hydra_ftl as hydra_router
from backend.scrapers.hydra_ftl import client

PDF = b"%PDF-1.4 synthetic lake map"
BUTTONS = ("btn_pros", "btn_plan", "btn_bufferzone")


def lake(n, name=None, lake_id=None, village="Testpally", mandal="Testmandal", district="Rangareddy",
         final="", buttons=("btn_pros", "btn_plan")):
    return {"n": n, "name": name or f"Sample Kunta {n}", "id": lake_id or str(9000 + n), "village": village,
            "mandal": mandal, "district": district, "final": final, "buttons": buttons}


LAKES = ([lake(1, "Sample Cheruvu", "9001/N/0001", final="30-09-2024", buttons=BUTTONS),
          lake(2, "Other Kunta (Big)", "9002", village="Elsewhere", mandal="Othermandal", district="Medchal-Malkajgiri")]
         + [lake(n, village=f"Village {n % 7}") for n in range(3, 125)])


def row_html(i, l):
    ctl = f"ctl{i + 2:02d}"
    cells = "".join(f"<td>{c}</td>" for c in (l["district"], l["mandal"], l["village"], l["name"].replace("&", "&amp;"),
                                              l["id"], "19-08-2016", l["final"] or "&nbsp;"))
    links = "".join(f'<td>\n<a onclick="SetTarget();" id="gv_{b}_{i}" href="javascript:__doPostBack(&#39;gv_showlakes${ctl}${b}&#39;,&#39;&#39;)">Click</a>\n</td>'
                    if b in l["buttons"] else "<td>\n</td>" for b in BUTTONS)
    return f'<tr>\n<td class="table_02" align="center">\n{i + 1}\n</td>{cells}{links}\n</tr>'


def page_html(lakes=LAKES, extra_rows=""):
    head = "<tr><th>Sno</th><th>District</th><th>Mandal</th><th>Village</th><th>Name of the lake</th><th>LakeID</th>" \
           "<th>Date of Preliminary Notification</th><th>Date of Final Notification</th><th>FTL</th><th>CADASTRAL</th><th>Synos</th></tr>"
    return ('<form method="post" action="./" id="form1">'
            '<input type="hidden" name="__EVENTTARGET" id="__EVENTTARGET" value="" />'
            '<input type="hidden" name="__VIEWSTATE" id="__VIEWSTATE" value="VS&amp;state" />'
            '<input type="hidden" name="__EVENTVALIDATION" id="__EVENTVALIDATION" value="EV" />'
            f'<table id="gv_showlakes">{head}{"".join(row_html(i, l) for i, l in enumerate(lakes))}{extra_rows}</table></form>')


def file_link(l, button):
    suffix = {"btn_pros": "FTL", "btn_plan": "CADASTRAL", "btn_bufferzone": "SyNo"}[button]
    return f"http://lakes.hmda.gov.in/hmdalake/{l['id'].replace('/', '-')}_{quote(l['name'])}_{suffix}.pdf"


def default_postback(form, lakes=LAKES):
    _, ctl, button = form["__EVENTTARGET"].split("$")
    return httpx.Response(302, headers={"location": file_link(lakes[int(ctl[3:]) - 2], button)})


class FakePortal:
    """Stands in for httpx.Client: the lakes page, the buttons' postbacks and the PDF files."""

    def __init__(self, page=None, postback=default_postback, files=None, delay=0.0):
        self.page = page or (lambda: httpx.Response(200, text=page_html()))
        self.postback, self.delay, self.calls = postback, delay, []
        self.files = files or (lambda url: httpx.Response(200, content=PDF))

    def __call__(self, timeout=90.0):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def request(self, method, url, data=None, **kw):
        self.calls.append((method, url, data))
        time.sleep(self.delay)
        r = self.page() if method == "GET" and url == client.BASE_URL else self.postback(data) if method == "POST" else self.files(url)
        if isinstance(r, Exception):
            raise r
        return r

    def count(self, method, url=None):
        return sum(1 for m, u, _ in self.calls if m == method and (url is None or u == url))


SURVEY = [
    {"district": "Rangareddy", "mandal": "Testmandal", "village": "Testpalli", "name": "Sample Cheruvu", "survey_no": "77",
     "acres": 12.5, "status_2011": "Live", "status_2023": "Partly encroached by buildings", "lat": 17.4, "lon": 78.4},
    {"district": "Rangareddy", "mandal": "Testmandal", "village": "Testpalli", "name": "", "survey_no": "",
     "acres": 2.0, "status_2011": "", "status_2023": "Live", "lat": 17.41, "lon": 78.41},
    {"district": "Medchal Malkajgiri", "mandal": "Othermandal", "village": "Elsewhere", "name": "", "survey_no": "",
     "acres": 5.0, "status_2011": "", "status_2023": "Fully encroached", "lat": 17.5, "lon": 78.5},
    {"district": "Medchal Malkajgiri", "mandal": "Thirdmandal", "village": "Elsewhere", "name": "", "survey_no": "",
     "acres": 9.0, "status_2011": "", "status_2023": "Live", "lat": 17.6, "lon": 78.6},
]


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    survey = tmp_path / "water_bodies.json"
    survey.write_text(json.dumps(SURVEY))
    monkeypatch.setattr(client, "WATER_BODIES_FILE", survey)
    monkeypatch.setattr(client._throttle, "min_interval_seconds", 0)
    for fn in (client._load_page, client._document, client._survey):
        fn.cache_clear()
    yield
    for fn in (client._load_page, client._document, client._survey):
        fn.cache_clear()


def portal(monkeypatch, **kw):
    fake = FakePortal(**kw)
    monkeypatch.setattr(client, "_client", fake)
    return fake


def _raises(user_message, fn, *args, **kwargs):
    with pytest.raises(PortalError) as exc:
        fn(*args, **kwargs)
    assert exc.value.user_message == user_message


def _app():
    app = FastAPI()
    app.include_router(hydra_router.router)
    return TestClient(app)


KEY = "9001/N/0001|Sample Cheruvu"


def test_the_page_is_read_into_lakes_with_their_documents(monkeypatch):
    portal(monkeypatch)
    lakes = client._page()["lakes"]
    assert len(lakes) == len(LAKES)
    first = lakes[KEY]
    assert (first["district"], first["mandal"], first["village"], first["final"]) == ("Rangareddy", "Testmandal", "Testpally", "30-09-2024")
    assert first["documents"] == ["ftl", "cadastral", "survey"] and first["ctl"] == "ctl02"
    assert lakes["9002|Other Kunta (Big)"]["documents"] == ["ftl", "cadastral"]
    assert client._page()["form"]["__VIEWSTATE"] == "VS&state"


def test_empty_rows_are_dropped_and_a_lake_listed_twice_keeps_the_fuller_row(monkeypatch):
    junk = row_html(200, lake(200, name="", lake_id="", district="--Select District--"))
    twice = [lake(1, "Sample Cheruvu", "9001/N/0001", final="", buttons=("btn_pros",))] + LAKES
    portal(monkeypatch, page=lambda: httpx.Response(200, text=page_html(twice, junk)))
    lakes = client._page()["lakes"]
    assert len(lakes) == len(LAKES)
    assert lakes[KEY]["final"] == "30-09-2024" and lakes[KEY]["ctl"] == "ctl03"


def test_places_list_districts_mandals_and_villages(monkeypatch):
    portal(monkeypatch)
    places = client.fetch_places()
    assert [p["district"] for p in places] == ["Medchal-Malkajgiri", "Rangareddy"]
    rr = places[1]["mandals"]
    assert rr[0]["mandal"] == "Testmandal" and "Testpally" in rr[0]["villages"] and rr[0]["villages"] == sorted(rr[0]["villages"])


def test_lakes_by_village_and_by_name_or_id(monkeypatch):
    portal(monkeypatch)
    r = client.find_lakes("Rangareddy", "Testmandal", "Testpally")
    assert r["total"] == 1 and r["lakes"][0]["key"] == KEY and "ctl" not in r["lakes"][0]
    assert client.find_lakes(q="other kunta")["lakes"][0]["name"] == "Other Kunta (Big)"
    assert client.find_lakes(q="9001/n")["lakes"][0]["key"] == KEY
    many = client.find_lakes(q="Sample Kunta")
    assert many["total"] == 122 and many["shown"] == len(many["lakes"]) == client.SEARCH_SHOWN


@pytest.mark.parametrize("kwargs, message", [
    ({"q": "x"}, BAD_INPUT),
    ({"q": "<script>"}, BAD_INPUT),
    ({"q": "a" * 81}, BAD_INPUT),
    ({"q": "Nowhere Lake"}, NOT_FOUND),
    ({"district": "Rangareddy", "mandal": "Testmandal", "village": "Nowhere"}, NOT_FOUND),
    ({}, BAD_INPUT),
])
def test_bad_or_unknown_searches(monkeypatch, kwargs, message):
    portal(monkeypatch)
    _raises(message, client.find_lakes, **kwargs)


def test_a_lake_comes_with_its_documents_and_its_villages_water_bodies(monkeypatch):
    portal(monkeypatch)
    r = client.fetch_lake(KEY)
    assert (r["id"], r["name"], r["preliminary"], r["final"]) == ("9001/N/0001", "Sample Cheruvu", "19-08-2016", "30-09-2024")
    assert [d["kind"] for d in r["documents"]] == ["ftl", "cadastral", "survey"]
    # "Testpally" on HMDA's list is "Testpalli" in the survey; biggest first
    assert [w["acres"] for w in r["water_bodies"]] == [12.5, 2.0]
    assert r["water_bodies"][0]["status_2023"] == "Partly encroached by buildings" and "district" not in r["water_bodies"][0]
    _raises(NOT_FOUND, client.fetch_lake, "9999|No Such Lake")


def test_water_bodies_need_the_same_mandal_when_two_villages_share_a_name():
    assert [w["acres"] for w in client.water_bodies("Medchal-Malkajgiri", "Othermandal", "Elsewhere")] == [5.0]
    assert client.water_bodies("Medchal-Malkajgiri", "Fourthmandal", "Elsewhere") == []
    assert client.water_bodies("Rangareddy", "Renamed mandal", "Testpally") != []  # one village of that name: mandal can differ
    assert client.water_bodies("Siddipet", "Any", "Testpally") == []


def test_a_document_is_found_by_the_rows_button_and_downloaded_over_https(monkeypatch):
    fake = portal(monkeypatch)
    pdf, name = client.fetch_document(KEY, "survey")
    assert pdf == PDF and name == "Hydra FTL Map - Sample Cheruvu - Lake ID 9001-N-0001 - Survey numbers in the FTL and buffer zone.pdf"
    form = next(d for m, _, d in fake.calls if m == "POST")
    assert form["__EVENTTARGET"] == "gv_showlakes$ctl02$btn_bufferzone" and form["__VIEWSTATE"] == "VS&state"
    assert fake.calls[-1][:2] == ("GET", "https://lakes.hmda.gov.in/hmdalake/9001-N-0001_Sample%20Cheruvu_SyNo.pdf")
    client.fetch_document(KEY, "survey")
    assert fake.count("POST") == 1 and fake.count("GET", client.BASE_URL) == 1  # cached


def test_identical_requests_share_one_page_read_and_one_download(monkeypatch):
    fake = portal(monkeypatch, delay=0.2)
    with ThreadPoolExecutor(5) as pool:
        results = list(pool.map(lambda _: client.fetch_document(KEY, "ftl"), range(5)))
    assert all(r == results[0] for r in results)
    assert fake.count("GET", client.BASE_URL) == 1 and fake.count("POST") == 1


def test_a_stale_page_is_read_again_once(monkeypatch):
    answers = iter([httpx.Response(200, text="<html>error</html>")])
    fake = portal(monkeypatch, postback=lambda form: next(answers, None) or default_postback(form))
    assert client.fetch_document(KEY, "ftl")[0] == PDF
    assert fake.count("GET", client.BASE_URL) == 2 and fake.count("POST") == 2


@pytest.mark.parametrize("location", [
    "http://lakes.hmda.gov.in/hmdalake/9002_Other%20Kunta%20(Big)_FTL.pdf",  # another lake's map
    "http://lakes.hmda.gov.in/hmdalake/9001-N-00011_Other%20Kunta_FTL.pdf",  # an ID that only begins the same
    "https://evil.example.com/hmdalake/9001-N-0001_Sample%20Cheruvu_FTL.pdf",
    "http://lakes.hmda.gov.in/other/9001-N-0001_Sample%20Cheruvu_FTL.pdf",
])
def test_a_redirect_to_the_wrong_file_is_never_followed(monkeypatch, location):
    fake = portal(monkeypatch, postback=lambda form: httpx.Response(302, headers={"location": location}))
    _raises(PORTAL_DOWN, client.fetch_document, KEY, "ftl")
    assert fake.count("GET") == 2  # the page twice, never the file


@pytest.mark.parametrize("kind, location", [
    ("ftl", "http://lakes.hmda.gov.in/hmdalake/9001-N-0001_FTL_final.pdf"),  # HMDA's names for some Hyderabad lakes
    ("cadastral", "http://lakes.hmda.gov.in/hmdalake/9001-N-0001_cadastral_final.pdf"),
    ("survey", "http://lakes.hmda.gov.in/hmdalake/9001-N-0001Sample%20Cheruvu_SyNo.pdf"),
])
def test_the_files_other_naming_styles_are_accepted(monkeypatch, kind, location):
    portal(monkeypatch, postback=lambda form: httpx.Response(302, headers={"location": location}))
    assert client.fetch_document(KEY, kind)[0] == PDF


def test_a_typo_in_the_file_name_still_counts_if_the_lake_name_matches(monkeypatch):
    typo = "http://lakes.hmda.gov.in/hmdalake/9001-N-oo01Sample%20Cheruvu_FTL.pdf"
    portal(monkeypatch, postback=lambda form: httpx.Response(302, headers={"location": typo}))
    assert client.fetch_document(KEY, "ftl")[0] == PDF


@pytest.mark.parametrize("file, message", [
    (httpx.Response(404, text="Not Found"), NOT_FOUND),
    (httpx.Response(200, content=b"<html>error</html>"), PORTAL_DOWN),
    (httpx.Response(500), PORTAL_DOWN),
    (httpx.ReadTimeout("slow"), PORTAL_TIMEOUT),
])
def test_file_trouble_is_friendly(monkeypatch, file, message):
    portal(monkeypatch, files=lambda url: file)
    _raises(message, client.fetch_document, KEY, "ftl")


def test_documents_a_lake_doesnt_have_and_bad_kinds(monkeypatch):
    fake = portal(monkeypatch)
    _raises(NOT_FOUND, client.fetch_document, "9002|Other Kunta (Big)", "survey")
    _raises(BAD_INPUT, client.fetch_document, KEY, "../../etc/passwd")
    _raises(NOT_FOUND, client.fetch_document, "9999|No Such Lake", "ftl")
    assert fake.count("POST") == 0


@pytest.mark.parametrize("answer, message", [
    (httpx.ReadTimeout("slow"), PORTAL_TIMEOUT),
    (httpx.ConnectError("down"), PORTAL_DOWN),
    (httpx.Response(500, text="Server Error"), PORTAL_DOWN),
    (httpx.Response(200, text="<html>maintenance</html>"), PORTAL_DOWN),
    (httpx.Response(200, text=page_html(LAKES[:5])), PORTAL_DOWN),  # a cut-off table
])
def test_portal_trouble_is_friendly(monkeypatch, answer, message):
    portal(monkeypatch, page=lambda: answer)
    _raises(message, client.fetch_places)


@pytest.mark.parametrize("message, status", [(NOT_FOUND, 404), (BAD_INPUT, 400), (PORTAL_DOWN, 502), (PORTAL_TIMEOUT, 502)])
def test_routes_map_errors_to_friendly_messages(monkeypatch, message, status):
    def fail(*_a, **_k):
        raise PortalError(message)
    for name in ("fetch_places", "find_lakes", "fetch_lake", "fetch_document"):
        monkeypatch.setattr(client, name, fail)
    app = _app()
    for r in (app.get("/api/hydra-ftl/places"), app.get("/api/hydra-ftl/lakes", params={"q": "sample"}),
              app.get("/api/hydra-ftl/lake", params={"key": KEY}),
              app.get("/api/hydra-ftl/document", params={"key": KEY, "kind": "ftl"})):
        assert r.status_code == status and r.json() == {"detail": message}


def test_routes_serve_places_lakes_a_lake_and_the_pdf_inline(monkeypatch):
    portal(monkeypatch)
    app = _app()
    assert app.get("/api/hydra-ftl/places").json()[1]["district"] == "Rangareddy"
    place = {"district": "Rangareddy", "mandal": "Testmandal", "village": "Testpally"}
    assert app.get("/api/hydra-ftl/lakes", params=place).json()["lakes"][0]["key"] == KEY
    assert app.get("/api/hydra-ftl/lake", params={"key": KEY}).json()["water_bodies"][0]["survey_no"] == "77"
    r = app.get("/api/hydra-ftl/document", params={"key": KEY, "kind": "ftl"})
    assert r.status_code == 200 and r.content == PDF and r.headers["content-type"] == "application/pdf"
    assert r.headers["content-disposition"] == 'inline; filename="Hydra FTL Map - Sample Cheruvu - Lake ID 9001-N-0001 - FTL and buffer zone map.pdf"'


def test_the_bundled_survey_file_is_sound(monkeypatch):
    monkeypatch.undo()  # the real file
    client._survey.cache_clear()
    rows = json.loads(client.WATER_BODIES_FILE.read_text(encoding="utf-8"))
    labels = {"", "Live", "Dead (no water)", "Partly encroached", "Partly encroached by buildings", "Partly encroached by farming",
              "Fully encroached", "Fully encroached by buildings", "Fully encroached by farming"}
    assert len(rows) > 3000
    assert all(r["status_2011"] in labels and r["status_2023"] in labels - {""} for r in rows)
    assert all(15 < r["lat"] < 20 and 76 < r["lon"] < 82 for r in rows)
    assert client.water_bodies("Hyderabad", "Amberpet", "Amberpet")  # the survey's first village
