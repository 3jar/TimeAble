"""Fetch an SKKU GLS course syllabus (강의계획서) via the public E_ endpoints.

The syllabus screen (nxui/outdex.html) is an external, pre-login Nexacro view.
Its data calls carry an empty _SESSION_ID and a plaintext SSV body, so no SSO
login and no AES layer are needed — we only prime an anonymous session.

The content is split across several transactions under E_NHSSU900011P. The one
non-obvious catch: each transaction binds parameters by its OWN column names
(GAESUL_YEAR / GYOYUKGWAJUNG_YEAR, not YEAR), so we send every alias at once.

Reuses the transport/SSV helpers from timeable.gls.http.
"""
import sys

from timeable.gls.http import BASE, RS, GLSError, WebHTTP, decrypt_response, parse_ssv

LOGIN_PATH = "E_NCommon/sessionLogin.do"
MODULE = "E_NHSSU900011P"
FRAME = "nxui/outdex.html"
HEADERS = {"Content-Type": "text/xml", "X-NX-Content-Type": "2",
           "X-Requested-With": "XMLHttpRequest",
           "Accept": "application/xml, text/xml, */*"}

# (transaction, output dataset name, human label)
QUERIES = [
    ("select01", "dsHeader", "헤더(과목·학기·교강사)"),
    ("select02", "dsSummary", "목표·교재·평가비율"),
    ("selectMain3", "dsPlan", "주차별 계획"),
    ("selectMain4", "dsCapa", "학생성공역량"),
    ("selectMain5", "dsFeature", "교육과정 특성"),
    ("selectMain6", "dsStyle", "수업형태"),
]


def build_body(params):
    return "SSV:utf-8" + RS + "".join(f"{k}={v}{RS}" for k, v in params.items())


def open_session():
    """Prime cookies + anonymous sessionLogin → JSESSIONID/WMONID."""
    http = WebHTTP()
    http.set_language_cookies()
    http.fetch(f"{BASE}{FRAME}", referer=f"{BASE}{FRAME}")
    http.fetch(f"{BASE}{LOGIN_PATH}", build_body({
        "_FIRST_OUT_DS_NM": "gdsUserInfo", "_TRANSACTION_ID": "sessionLogin",
        "_ALL_OUT_DS_NM": "gdsUserInfo=gdsUserInfo",
        "_MENU_ID": "", "_PGM_ID": "", "_SESSION_ID": "",
    }).encode("utf-8"), headers=HEADERS, referer=f"{BASE}{FRAME}")
    return http


def filter_params(year, term, haksu_no, bunban, gyogangsa_id=""):
    # Every alias each transaction might bind to. Harmless extras are ignored.
    return {
        "YEAR": str(year), "TERM": str(term),
        "GAESUL_YEAR": str(year), "GAESUL_TERM": str(term),
        "GYOYUKGWAJUNG_YEAR": str(year),
        "HAKSU_NO": haksu_no, "BUNBAN": str(bunban),
        "GYOGANGSA_ID": str(gyogangsa_id), "PER_ID": str(gyogangsa_id),
        "TONGHAP_JUNGONG_CD": "SKK", "TONGHAP_JUNGONG_CD_1": "SKK",
    }


def query(http, transaction, output, filt):
    params = dict(filt)
    params.update({
        "_FIRST_IN_DS_NM": "", "_ALL_IN_DS_NM": "",
        "_FIRST_OUT_DS_NM": output, "_ALL_OUT_DS_NM": f"{output}={output}",
        "_TRANSACTION_ID": transaction,
        "_MENU_ID": "11", "_PGM_ID": "NHSSU900011P", "_SESSION_ID": "",
    })
    text, _ = http.fetch(f"{BASE}{MODULE}/{transaction}.do",
                         build_body(params).encode("utf-8"),
                         headers=HEADERS, referer=f"{BASE}{FRAME}")
    # Public response is plaintext SSV (no session passphrase).
    return parse_ssv(decrypt_response(text, "")).get(output, [])


def fetch_syllabus(year, term, haksu_no, bunban, gyogangsa_id="", http=None):
    """Return {label: rows} for every syllabus section of one section.

    Pass an existing anonymous session via `http` to reuse it across courses.
    """
    http = http or open_session()
    filt = filter_params(year, term, haksu_no, bunban, gyogangsa_id)
    return {label: query(http, tx, out, filt) for tx, out, label in QUERIES}


def main():
    args = sys.argv[1:]
    if len(args) not in (4, 5):
        print("사용법: python -m timeable.gls.syllabus YEAR TERM HAKSU_NO BUNBAN [GYOGANGSA_ID]")
        print("예:     python -m timeable.gls.syllabus 2026 20 DASF003 46 235965")
        return 1
    year, term, haksu_no, bunban = args[:4]
    gyogangsa_id = args[4] if len(args) == 5 else ""
    print(f"강의계획서 조회: {year}년 {term} {haksu_no}-{bunban}\n")
    try:
        sections = fetch_syllabus(year, term, haksu_no, bunban, gyogangsa_id)
    except GLSError as error:
        print("실패:", error)
        return 1
    for label, rows in sections.items():
        print(f"[{label}] {len(rows)}행")
        for row in rows[:3]:
            filled = {k: v for k, v in row.items()
                      if v and not k.startswith("_") and len(v) <= 120}
            print("   ", filled)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
