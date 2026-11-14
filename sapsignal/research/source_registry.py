"""Domain helpers, source tiers, editorial perspective labels and URL canonicalisation.

Tier describes source class; perspective describes editorial viewpoint. Neither is a
stand-alone truth score. Both are assigned from configuration, never from model claims.
"""
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from ..config import get_config
from ..schemas import SourceTier

_SECOND_LEVEL = {"co.uk", "org.uk", "gov.uk", "ac.uk", "com.au", "co.in", "co.jp", "com.br", "co.nz", "gov.in",
                 "nic.in", "org.in", "net.in", "ac.in", "com.tr", "co.za", "com.sg", "com.pk", "com.ng", "co.kr",
                 "com.cn", "com.hk", "com.tw", "co.il", "com.mx", "com.ar", "co.id", "com.my", "com.ph", "com.bd",
                 "com.np", "com.lk", "gov.cn", "gov.au"}
_TRACKING_PREFIXES = ("utm_", "fbclid", "gclid", "mc_", "ref", "cmpid")


def host_of(url: str) -> str:
    raw = url if "://" in url else "https://" + url
    try:
        host = (urlparse(raw).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def registrable_domain(url_or_host: str) -> str:
    host = host_of(url_or_host)
    if not host:
        return ""
    parts = host.split(".")
    if len(parts) <= 2:
        return host
    suffix2 = ".".join(parts[-2:])
    if suffix2 in _SECOND_LEVEL and len(parts) >= 3:
        return ".".join(parts[-3:])
    return suffix2


@lru_cache(maxsize=1)
def _tier_map() -> dict[str, SourceTier]:
    result: dict[str, SourceTier] = {}
    for tier_name, domains in get_config().get("sources", {}).items():
        tier = SourceTier(tier_name)
        for domain in domains:
            result[str(domain).lower().strip()] = tier
    return result


@lru_cache(maxsize=1)
def _perspective_map() -> dict[str, str]:
    result: dict[str, str] = {}
    for perspective, domains in get_config().get("source_perspectives", {}).items():
        for domain in domains:
            result[str(domain).lower().strip()] = perspective
    return result


@lru_cache(maxsize=1)
def _excluded() -> frozenset[str]:
    policy = get_config().get("source_policy", {}) or {}
    return frozenset(str(d).lower().strip() for d in policy.get("excluded", []) or [])


def is_excluded(url: str) -> bool:
    """True for outlets barred by source_policy.excluded (checked on host and registrable domain)."""
    host = host_of(url)
    return bool(host) and (host in _excluded() or registrable_domain(host) in _excluded())


def excluded_domains() -> list[str]:
    return sorted(_excluded())


def search_domains() -> list[str]:
    return list((get_config().get("source_policy", {}) or {}).get("search_domains", []) or [])


def classify(url: str) -> SourceTier:
    host = host_of(url)
    if not host:
        return SourceTier.UNKNOWN
    if is_excluded(url):
        return SourceTier.EXCLUDED
    tiers = _tier_map()
    return tiers.get(host) or tiers.get(registrable_domain(host)) or SourceTier.UNKNOWN


def perspective_of(url: str) -> str:
    host = host_of(url)
    if not host:
        return "unclassified"
    perspectives = _perspective_map()
    return perspectives.get(host) or perspectives.get(registrable_domain(host)) or "unclassified"


def normalize_origin(origin: str, url: str) -> str:
    """Normalize provenance label; distinct registrable domains are independently required too."""
    value = " ".join((origin or "").casefold().split()).strip(" .,:;|\\t\\n")
    return value or registrable_domain(url)


def canonical_url(url: str) -> str:
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = host_of(url)
    if not host or parsed.scheme.lower() not in ("http", "https"):
        return ""
    query = [
        (key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(_TRACKING_PREFIXES)
    ]
    return urlunparse((parsed.scheme.lower(), host, parsed.path.rstrip("/"), "", urlencode(query), ""))


def is_aggregator(url: str) -> bool:
    """True for wrapper/aggregator links (Google News, MSN, Yahoo...). These must be resolved to the
    original publisher before fetching, quoting or tier classification."""
    return classify(url) == SourceTier.AGGREGATOR


OUTLET_NAMES = {
    "reuters.com": "Reuters", "apnews.com": "AP", "afp.com": "AFP", "bloomberg.com": "Bloomberg", "ft.com": "FT",
    "wsj.com": "WSJ", "ptinews.com": "PTI", "aninews.in": "ANI", "dw.com": "DW", "france24.com": "France 24",
    "nikkei.com": "Nikkei Asia", "thediplomat.com": "The Diplomat", "livemint.com": "Mint",
    "business-standard.com": "Business Standard", "indiatimes.com": "Economic Times",
    "financialexpress.com": "Financial Express", "thehindubusinessline.com": "BusinessLine",
    "hindustantimes.com": "Hindustan Times", "thehindu.com": "The Hindu", "moneycontrol.com": "Moneycontrol",
    "cnbc.com": "CNBC", "cnbctv18.com": "CNBC-TV18", "aljazeera.com": "Al Jazeera", "scmp.com": "SCMP",
    "straitstimes.com": "Straits Times", "japantimes.co.jp": "Japan Times", "techcrunch.com": "TechCrunch",
    "theverge.com": "The Verge", "arstechnica.com": "Ars Technica", "technologyreview.com": "MIT Technology Review",
    "wired.com": "Wired", "theregister.com": "The Register", "spacenews.com": "SpaceNews", "nature.com": "Nature",
    "science.org": "Science", "newscientist.com": "New Scientist", "un.org": "UN", "nato.int": "NATO",
    "europa.eu": "EU", "pib.gov.in": "PIB", "mea.gov.in": "MEA", "rbi.org.in": "RBI", "imf.org": "IMF",
    "foreignpolicy.com": "Foreign Policy", "economist.com": "The Economist", "nytimes.com": "NYT",
    "washingtonpost.com": "Washington Post", "mod.gov.in": "Defence Ministry",
    "indiatoday.in": "India Today", "aa.com.tr": "Anadolu", "arabnews.com": "Arab News", "npr.org": "NPR",
    "abcnews.com": "ABC News", "koreajoongangdaily.com": "Korea JoongAng Daily", "taipeitimes.com": "Taipei Times",
    "kyivpost.com": "Kyiv Post", "forbes.com": "Forbes", "yahoo.com": "Yahoo Finance", "investing.com": "Investing.com",
    "deccanchronicle.com": "Deccan Chronicle", "freepressjournal.in": "Free Press Journal",
    "atlanticcouncil.org": "Atlantic Council", "cnn.com": "CNN", "axios.com": "Axios", "politico.com": "Politico",
    "focustaiwan.tw": "Focus Taiwan", "digitimes.com": "DigiTimes", "theprint.in": "ThePrint",
    "sap.com": "SAP", "diginomica.com": "diginomica", "erp.today": "ERP Today", "sapinsider.org": "SAPinsider",
    "insidesap.com": "InsideSAP", "computerweekly.com": "Computer Weekly", "computerwoche.de": "Computerwoche",
    "cio.com": "CIO", "techtarget.com": "TechTarget", "zdnet.com": "ZDNET", "itpro.com": "ITPro",
    "siliconangle.com": "SiliconANGLE", "venturebeat.com": "VentureBeat", "e3mag.com": "E3 Magazine",
    "dsag.de": "DSAG", "asug.com": "ASUG", "ukisug.co.uk": "UKISUG", "gartner.com": "Gartner",
    "forrester.com": "Forrester", "idc.com": "IDC", "riministreet.com": "Rimini Street",
    "spinnakersupport.com": "Spinnaker Support", "handelsblatt.com": "Handelsblatt", "sec.gov": "SEC",
    "prnewswire.com": "PR Newswire", "businesswire.com": "Business Wire", "constellationr.com": "Constellation Research",
}


def outlet_name(url_or_domain: str) -> str:
    """Reader-facing outlet name ('Mint', not 'livemint.com')."""
    d = registrable_domain(url_or_domain if "://" in url_or_domain else "https://" + url_or_domain)
    return OUTLET_NAMES.get(d, d)


_OPINION = ("/opinion", "/opinions/", "/commentary/", "/column", "/blogs/", "/blog/", "/editorial", "/op-ed",
            "/analysis/opinion", "/views/", "/perspective/", "/podcast", "/videos/", "/video/", "/videonews/",
            "/live/", "/liveblog", "/photos/", "/gallery/")


def is_opinion_or_media(url: str) -> bool:
    """Opinion columns, podcasts, video and photo pages: not news copy to brief from."""
    u = (url or "").lower()
    return any(m in u for m in _OPINION)
