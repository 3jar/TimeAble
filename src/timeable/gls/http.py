"""Print an SKKU GLS timetable using HTTP login and email verification.

Requires: python -m pip install cryptography
No credentials or session data are written to disk.
"""
import base64
import getpass
import gzip
import hashlib
import json
import re
import secrets
from datetime import datetime
from html.parser import HTMLParser
from http.cookiejar import Cookie, CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlsplit
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

BASE = "https://kingoinfo.skku.edu/gaia/"
RS, CS = "\x1e", "\x1f"
STANDARD = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
SCRAMBLED = "yzYbDIrs7EJB5uH8AvSTcCKZa01fgUV63htij9wxLMFGq+/NOPdeop2nQR4klmWX"
LOGIN_DATASETS = "gdsUserInfo gdsMenu gdsUser gdsHakbun gdsHoliday gdsMsg".split()


class GLSError(Exception):
    pass


def parse_ssv(text):
    text = text.lstrip("\ufeff\r\n ")
    if not text.startswith("SSV:"):
        raise GLSError("SSV가 아닌 응답: 로그인 경로나 응답 형식 확인 필요")
    params, datasets = {}, {}
    current, columns = None, []
    for record in text.split(RS):
        record = record.strip("\r\n")
        if record.startswith("Dataset:"):
            current = record.split(":", 1)[1]
            datasets[current], columns = [], []
        elif current is None and "=" in record:
            key, value = record.split("=", 1)
            params[key.split(":", 1)[0]] = value
        elif current is not None:
            cells = record.split(CS)
            if cells[0] == "_RowType_":
                columns = [x.split(":", 1)[0] for x in cells[1:]]
            elif columns and cells[0] in {"N", "I", "U", "O"}:
                if len(cells) != len(columns) + 1:
                    raise GLSError("SSV 열 개수 불일치")
                datasets[current].append(dict(zip(columns, cells[1:])))
    if "ErrorCode" not in params:
        raise GLSError("응답에 ErrorCode가 없음")
    code = int(params["ErrorCode"])
    if code < 0:
        # 서버 메시지/응답 원문에는 인증정보가 섞일 수 있어 출력하지 않음.
        raise GLSError(f"GLS 오류 코드 {code} (자동 재시도하지 않음)")
    return datasets


def encrypt_request(text, passphrase, salt=None, iv=None):
    salt = salt if salt is not None else secrets.token_bytes(16)
    iv = iv if iv is not None else secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha1", passphrase.encode(), salt, 1, 16)
    padder = PKCS7(128).padder()
    padded = padder.update(text.encode()) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    encoded = base64.b64encode(ciphertext).decode().rstrip("=")
    payload = encoded.translate(str.maketrans(STANDARD, SCRAMBLED))[::-1]
    return f"Crypto::{payload}::{salt.hex()}::{iv.hex()}"


def decrypt_response(text, passphrase):
    if not text.startswith("Crypto::"):
        return text
    if not passphrase:
        raise GLSError("초기 응답이 암호화됨: 추가 로그인 절차 확인 필요")
    _, payload, salt, iv = text.split("::")
    key = hashlib.pbkdf2_hmac("sha1", passphrase.encode(), bytes.fromhex(salt), 1, 16)
    decryptor = Cipher(algorithms.AES(key), modes.CBC(bytes.fromhex(iv))).decryptor()
    padded = decryptor.update(base64.b64decode(payload)) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode("utf-8-sig")


class StopRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WebHTTP:
    """HTTPS requests with one in-memory cookie session and bounded redirects."""
    HOSTS = {"login.skku.edu", "portal.skku.edu", "kingoinfo.skku.edu", "auth.worksmobile.com"}

    def __init__(self):
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar), StopRedirect())
        self.mfa_context = {}

    def set_language_cookies(self):
        for domain, specified in (("login.skku.edu", False), (".skku.edu", True)):
            self.jar.set_cookie(Cookie(
                version=0, name="language", value="ko", port=None, port_specified=False,
                domain=domain, domain_specified=specified, domain_initial_dot=domain.startswith("."),
                path="/", path_specified=True, secure=False, expires=None, discard=True,
                comment=None, comment_url=None, rest={}, rfc2109=False))

    def fetch(self, url, data=None, headers=None, referer=None):
        for _ in range(10):
            parts = urlsplit(url)
            if (parts.scheme != "https" or parts.hostname not in self.HOSTS
                    or parts.port not in (None, 443) or parts.username or parts.password):
                raise GLSError("허용되지 않는 연결 대상입니다.")
            head = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/157.0.0.0 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
                "Accept-Encoding": "identity",
            }
            head.update(headers or {})
            if referer:
                head["Referer"] = referer
                if data is not None:
                    origin = urlsplit(referer)
                    head.setdefault("Origin", f"{origin.scheme}://{origin.netloc}")
            request = Request(url, data=data, headers=head)
            try:
                response = self.opener.open(request, timeout=25)
            except HTTPError as error:
                response = error
            except (URLError, TimeoutError):
                raise GLSError("서버 연결 실패 또는 시간 초과") from None
            try:
                status = response.code
                location = response.headers.get("Location")
                encoding = response.headers.get("Content-Encoding", "")
                content = response.read(16_000_001)
            finally:
                response.close()
            if len(content) > 16_000_000:
                raise GLSError("응답 크기가 허용 범위를 넘었습니다.")
            if encoding.lower() == "gzip":
                content = gzip.decompress(content)
            if status in {301, 302, 303, 307, 308} and location:
                target = urljoin(url, location)
                if status in {307, 308} and data is not None and urlsplit(target).netloc != parts.netloc:
                    raise GLSError("다른 서버로 POST 본문을 전달하는 이동은 지원하지 않습니다.")
                if status in {301, 302, 303}:
                    data, headers = None, {}
                referer, url = url, target
                continue
            if status >= 400:
                raise GLSError(f"서버 요청 실패: HTTP {status}")
            return content.decode("utf-8-sig"), url
        raise GLSError("HTTP 이동 횟수 초과")


class HTMLForms(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.forms, self.current = [], None
        self.refresh, self.scripts, self.script = None, [], None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"attrs": attrs, "inputs": []}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None:
            self.current["inputs"].append(attrs)
        elif tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
            match = re.search(r"url\s*=\s*(.+)", attrs.get("content", ""), re.I)
            if match:
                self.refresh = match.group(1).strip().strip("\"'")
        elif tag == "script" and not attrs.get("src"):
            self.script = ""

    def handle_data(self, data):
        if self.script is not None:
            self.script += data

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None
        elif tag == "script" and self.script is not None:
            self.scripts.append(self.script)
            self.script = None

    def form(self, name):
        return next((f for f in self.forms if name in (f["attrs"].get("id"), f["attrs"].get("name"))), None)

    @staticmethod
    def values(form):
        result = {}
        for field in form["inputs"]:
            name, kind = field.get("name"), field.get("type", "text").lower()
            if not name or "disabled" in field or kind in {"submit", "button", "file", "reset", "image"}:
                continue
            if kind in {"checkbox", "radio"} and "checked" not in field:
                continue
            result[name] = field.get("value", "on" if kind in {"checkbox", "radio"} else "")
        return result


class StaticJSString:
    """Parse strings, +, parentheses and URI encoders only. Never run JS."""
    def __init__(self, expression):
        self.text, self.pos = expression, 0

    def space(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("//", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            elif self.text.startswith("/*", self.pos):
                end = self.text.find("*/", self.pos + 2)
                if end < 0:
                    raise ValueError("unterminated_comment")
                self.pos = end + 2
            else:
                break

    def string(self):
        quote_char = self.text[self.pos]
        self.pos += 1
        result = []
        escapes = {"b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote_char:
                # JavaScript strings may spell supplementary characters as a
                # UTF-16 surrogate pair. Reject isolated surrogates.
                return "".join(result).encode("utf-16-le", "surrogatepass").decode("utf-16-le")
            if char in "\r\n":
                raise ValueError("newline_in_string")
            if char != "\\":
                result.append(char)
                continue
            if self.pos >= len(self.text):
                raise ValueError("unfinished_escape")
            esc = self.text[self.pos]
            self.pos += 1
            if esc in escapes:
                result.append(escapes[esc])
            elif esc in "\r\n":
                if esc == "\r" and self.text[self.pos:self.pos + 1] == "\n":
                    self.pos += 1
            elif esc in {"x", "u"}:
                count = 2 if esc == "x" else 4
                if esc == "u" and self.text[self.pos:self.pos + 1] == "{":
                    end = self.text.find("}", self.pos + 1)
                    if end < 0:
                        raise ValueError("unfinished_unicode")
                    digits = self.text[self.pos + 1:end]
                    self.pos = end + 1
                else:
                    digits = self.text[self.pos:self.pos + count]
                    if len(digits) != count:
                        raise ValueError("unfinished_unicode")
                    self.pos += count
                if not re.fullmatch(r"[0-9A-Fa-f]{1,6}", digits):
                    raise ValueError("invalid_unicode")
                result.append(chr(int(digits, 16)))
            elif esc == "0":
                if self.text[self.pos:self.pos + 1].isdigit():
                    raise ValueError("legacy_octal_not_supported")
                result.append("\0")
            elif esc.isdigit():
                raise ValueError("legacy_octal_not_supported")
            else:
                result.append(esc)
        raise ValueError("unterminated_string")

    def term(self):
        self.space()
        if self.pos >= len(self.text):
            raise ValueError("missing_term")
        if self.text[self.pos] in "\"'":
            return self.string()
        if self.text[self.pos] == "(":
            self.pos += 1
            value = self.expression()
            self.space()
            if self.text[self.pos:self.pos + 1] != ")":
                raise ValueError("missing_parenthesis")
            self.pos += 1
            return value
        name = re.match(r"(?:encodeURIComponent|encodeURI)\b", self.text[self.pos:])
        if not name:
            raise ValueError("nonliteral_expression")
        name = name.group()
        self.pos += len(name)
        self.space()
        if self.text[self.pos:self.pos + 1] != "(":
            raise ValueError("missing_parenthesis")
        self.pos += 1
        value = self.expression()
        self.space()
        if self.text[self.pos:self.pos + 1] != ")":
            raise ValueError("missing_parenthesis")
        self.pos += 1
        safe = "-_.!~*'()" if name == "encodeURIComponent" else ";/?:@&=+$,#-_.!~*'()"
        return quote(value, safe=safe)

    def expression(self):
        value = self.term()
        while True:
            self.space()
            if self.text[self.pos:self.pos + 1] != "+":
                return value
            self.pos += 1
            value += self.term()


def static_navigation(block):
    """Read a literal location assignment/call without executing JavaScript."""
    parser = StaticJSString(block)
    try:
        parser.space()
        prefix = re.match(r"(?:(?:window|top|self|document)\.)?location(?:\.href)?\s*=\s*", block[parser.pos:])
        closing_call = False
        if not prefix:
            prefix = re.match(r"(?:(?:window|top|self|document)\.)?location\.(?:replace|assign)\s*\(\s*", block[parser.pos:])
            closing_call = True
        if not prefix:
            return None
        parser.pos += prefix.end()
        value = parser.expression()
        parser.space()
        if closing_call:
            if block[parser.pos:parser.pos + 1] != ")":
                return None
            parser.pos += 1
            parser.space()
        if block[parser.pos:parser.pos + 1] == ";":
            parser.pos += 1
        parser.space()
        if parser.pos != len(block) or any(ord(char) < 32 for char in value):
            return None
        return value
    except (ValueError, UnicodeError):
        return None


def works_refresh_target(current_url, page):
    """Recognize the provider's own one-time refresh, retaining all OAuth values."""
    current = urlsplit(current_url)
    if current.hostname != "auth.worksmobile.com" or current.path != "/oauth2/v2.0/authorize":
        return None
    original = parse_qsl(current.query, keep_blank_values=True)
    if any(key == "isRefreshed" for key, _ in original):
        return None
    for block in page.scripts:
        value = static_navigation(block)
        if value is None:
            continue
        candidate = urljoin(current_url, value)
        parts = urlsplit(candidate)
        if (parts.scheme, parts.netloc, parts.path, parts.fragment) != (current.scheme, current.netloc, current.path, current.fragment):
            continue
        pairs = parse_qsl(parts.query, keep_blank_values=True)
        if ([(key, value) for key, value in pairs if key == "isRefreshed"] == [("isRefreshed", "true")]
                and sorted((key, value) for key, value in pairs if key != "isRefreshed") == sorted(original)):
            return candidate
    return None


def works_sso_fallback(page):
    """Use auth_service.js's explicit redirect on fingerprint failure.

    HTTP-only clients cannot collect browser device information. Do not invent
    a fingerprint or call the device-registration endpoint with fabricated data.
    The provider itself redirects to the same SSO URL on success or failure;
    subsequent login and two-step requirements remain server-controlled.
    """
    for block in page.scripts:
        match = re.match(r"\s*new\s+SsoFingerPrint\s*\(\s*", block)
        if not match:
            continue
        parser = StaticJSString(block)
        parser.pos = match.end()
        try:
            values = []
            for index in range(3):
                values.append(parser.expression())
                parser.space()
                if index < 2:
                    if block[parser.pos:parser.pos + 1] != ",":
                        raise ValueError("missing_comma")
                    parser.pos += 1
            if not re.fullmatch(r"\)\s*;?\s*", block[parser.pos:]):
                raise ValueError("extra_statements")
        except (ValueError, UnicodeError):
            continue
        target, key, sso_type = values
        parts = urlsplit(target)
        if (parts.scheme != "https" or parts.netloc != "portal.skku.edu"
                or parts.path != "/nw/oAuth/auth.do" or sso_type != "OAUTH"
                or any(ord(c) < 32 for c in target)):
            continue
        return target
    return None


def has_provider_message(page, text):
    if len(text) >= 12000:
        return False
    pattern = r'\b(?:var|let|const)\s+(?:message|errorMessage|errMsg)\s*=\s*("(?:\\.|[^"\\])*")\s*;'
    for script in page.scripts:
        for match in re.finditer(pattern, script):
            try:
                message = json.loads(match.group(1))
            except ValueError:
                continue
            if isinstance(message, str) and message.strip():
                return True
    return False


def follow_html(http, text, url, expected_form=None):
    """Follow the verified provider transitions, retaining subsequent MFA."""
    reloaded = set()
    for _ in range(8):
        page = HTMLForms(text)
        if expected_form and page.form(expected_form):
            return text, url, page
        parts = urlsplit(url)
        if parts.hostname == "auth.worksmobile.com" and parts.path.startswith("/view/oauth/sso/authorization/"):
            handoff = page.form("frm1")
            if handoff:
                action = urljoin(url, handoff["attrs"].get("action", ""))
                fields = HTMLForms.values(handoff)
                if (action == "https://auth.worksmobile.com/2step-login/view"
                        and handoff["attrs"].get("method", "get").lower() == "post"
                        and fields.get("userIdNo") and fields.get("sessionKey")):
                    http.mfa_context = fields.copy()
                    text, url = http.fetch(action, data=urlencode(fields).encode(),
                        headers={"Content-Type": "application/x-www-form-urlencoded"}, referer=url)
                    continue
        if parts.hostname == "auth.worksmobile.com":
            if has_provider_message(page, text):
                refresh = works_refresh_target(url, page)
                if refresh:
                    text, url = http.fetch(refresh, referer=url)
                    continue
                return text, url, page
            if url not in reloaded and any(re.fullmatch(
                    r"\s*(?:(?:document|window|self|top)\.)?location\.reload\(\s*\)\s*;?\s*", block)
                    for block in page.scripts):
                reloaded.add(url)
                text, url = http.fetch(url, referer=url)
                continue
            fallback = works_sso_fallback(page)
            if fallback:
                text, url = http.fetch(fallback, referer=url)
                continue
        target = page.refresh
        if not target and len(text) < 12000:
            target = next((value for block in page.scripts
                if (value := static_navigation(block)) is not None), None)
        if not target:
            return text, url, page
        text, url = http.fetch(urljoin(url, target), referer=url)
    raise GLSError("HTML 이동 횟수 초과")


class JSData(StaticJSString):
    """Read literal JS data and JSON.parse only; never execute page scripts."""
    def __init__(self, text, values=None):
        super().__init__(text)
        self.values = values or {}

    def value(self, depth=0):
        if depth > 20:
            raise ValueError("data_too_deep")
        self.space()
        char = self.text[self.pos:self.pos + 1]
        if not char:
            raise ValueError("missing_value")
        if char in "\"'":
            return self.string()
        if char == "(":
            self.pos += 1
            result = self.value(depth + 1)
            self.take(")")
            return result
        if char in "[{":
            self.pos += 1
            result = [] if char == "[" else {}
            end = "]" if char == "[" else "}"
            self.space()
            while self.text[self.pos:self.pos + 1] != end:
                if len(result) > 1000:
                    raise ValueError("data_too_large")
                if char == "{":
                    self.space()
                    if self.text[self.pos:self.pos + 1] in "\"'":
                        key = self.string()
                    else:
                        key = self.identifier()
                    self.take(":")
                    result[key] = self.value(depth + 1)
                else:
                    result.append(self.value(depth + 1))
                self.space()
                if self.text[self.pos:self.pos + 1] == end:
                    break
                self.take(",")
                self.space()
            self.take(end)
            return result
        if self.text.startswith("JSON.parse", self.pos):
            self.pos += len("JSON.parse")
            self.take("(")
            data = self.value(depth + 1)
            self.take(")")
            if not isinstance(data, str):
                raise ValueError("json_parse_requires_string")
            return json.loads(data)
        number = re.match(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?", self.text[self.pos:])
        if number:
            self.pos += number.end()
            return json.loads(number.group())
        name = self.identifier()
        if name in {"true", "false", "null", "undefined"}:
            return {"true": True, "false": False, "null": None, "undefined": None}[name]
        if name in self.values:
            return self.values[name]
        raise ValueError("nonliteral_value")

    def identifier(self):
        self.space()
        name = re.match(r"[A-Za-z_$][\w$]*", self.text[self.pos:])
        if not name:
            raise ValueError("missing_identifier")
        self.pos += name.end()
        return name.group()

    def take(self, symbol):
        self.space()
        if self.text[self.pos:self.pos + 1] != symbol:
            raise ValueError("unexpected_data_syntax")
        self.pos += 1


def works_email_configuration(page):
    """Read the observed TwoStepLogin constructor's literal arguments, not JS."""
    for script in page.scripts:
        objects = {}
        for match in re.finditer(r"\b(?:var|let|const)\s+(\w+)\s*=\s*", script):
            try:
                parser = JSData(script, objects)
                parser.pos = match.end()
                value = parser.value()
                parser.space()
                if script[parser.pos:parser.pos + 1] in {";", ","}:
                    objects[match.group(1)] = value
            except (ValueError, UnicodeError, IndexError):
                pass
        match = re.search(r"\bnew\s+TwoStepLogin\s*\(\s*", script)
        if not match:
            continue
        parser = JSData(script, objects)
        parser.pos = match.end()
        args = []
        try:
            while len(args) < 9:
                parser.space()
                if script[parser.pos:parser.pos + 1] == ")":
                    break
                args.append(parser.value())
                parser.space()
                if script[parser.pos:parser.pos + 1] == ")":
                    break
                parser.take(",")
            parser.take(")")
            if len(args) == 7:
                args.append(None)  # Omitted last parameter is undefined in JS.
            if len(args) != 8:
                continue
            data = args[0]
            if (isinstance(data, dict) and data.get("userIdNo") and data.get("sessionKey")
                    and all(args[i] is None or type(args[i]) is bool for i in (1, 4, 5, 6, 7))):
                for i in (1, 4, 5, 6, 7):
                    args[i] = bool(args[i])
                return data, args
        except (ValueError, UnicodeError, IndexError):
            pass
    return None


def works_response_code(result):
    """The service can encode its numeric result code as a JSON string."""
    code = result.get("code") if isinstance(result, dict) else None
    if type(code) is int:
        return code
    if isinstance(code, str) and re.fullmatch(r"-?[0-9]{1,6}", code.strip()):
        return int(code.strip())
    return None


def finish_works_email(http, text, url, page, ask=None):
    if urlsplit(url).hostname != "auth.worksmobile.com" or urlsplit(url).path != "/2step-login/view":
        return text, url, page
    config = works_email_configuration(page)
    if not config:
        return text, url, page
    data, args = config
    if args[5] or args[6] or not args[2]:
        raise GLSError("이메일 인증이 차단되었거나 이메일 등록이 필요한 화면")
    context = getattr(http, "mfa_context", {})
    if context and any(str(context.get(k)) != str(data.get(k)) for k in ("userIdNo", "sessionKey")):
        raise GLSError("2단계 인증 세션 정보가 일치하지 않음")
    if data.get("twoStepLoginUsage") != "web_login":
        raise GLSError("지원하지 않는 2단계 인증 용도")
    auth_form = page.form("twoStepLoginAuth")
    if not auth_form:
        return text, url, page
    base = "https://auth.worksmobile.com"
    identity = {k: str(data[k]) for k in ("userIdNo", "sessionKey")}
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest"}
    print("\n등록된 이메일로 인증번호를 요청합니다.")
    sent, _ = http.fetch(base + "/2step-login/auth/send/email", data=urlencode(identity).encode(), headers=headers, referer=url)
    result = json.loads(sent)
    code = works_response_code(result)
    if code != 0:
        raise GLSError("이메일 인증번호 발송 실패 — 응답 코드 " + (str(code) if code is not None else "unknown"))
    auth_key = result.get("authKey")
    if not isinstance(auth_key, str) or not auth_key:
        raise GLSError("이메일 발송은 성공했지만 응답에서 인증 키를 찾지 못함")
    fields = HTMLForms.values(auth_form)
    fields.update(identity)
    fields.update({"redirectUrl": data.get("redirectUrl", ""), "authKey": auth_key,
        "twoStepLoginUsage": data["twoStepLoginUsage"], "displayEmail": args[2],
        "displayPhoneNumber": args[3] or "", "isPhoneLogin": str(args[1]).lower()})
    text, url = http.fetch(base + "/2step-login/auth/email", data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, referer=url)
    if urlsplit(url).hostname != "auth.worksmobile.com" or urlsplit(url).path != "/2step-login/auth/email":
        return follow_html(http, text, url, "frmMenu")
    if not any(re.search(r"\bnew\s+TwoStepLoginAuth\s*\(", s) for s in HTMLForms(text).scripts):
        return text, url, HTMLForms(text)
    print("이메일로 받은 새 인증번호를 이 터미널에 입력하세요. 빈 입력은 취소합니다.")
    read_code = ask or input
    for _ in range(3):
        otp = read_code("이메일 인증번호: ").strip()
        if not otp:
            raise GLSError("이메일 인증 취소")
        if not re.fullmatch(r"[0-9]{4}", otp):
            print("인증번호는 숫자 4자리입니다.")
            continue
        payload = dict(identity, authNo=otp, authKey=auth_key,
            redirectUrl=data.get("redirectUrl", ""), isPhoneLogin=str(args[1]).lower())
        reply, _ = http.fetch(base + "/2step-login/login/process/email", data=urlencode(payload).encode(), headers=headers, referer=url)
        result = json.loads(reply)
        code = works_response_code(result)
        if code in (36, 38):
            print("인증번호가 일치하지 않습니다. 같은 이메일의 번호를 다시 확인하세요.")
            continue
        if code != 0:
            raise GLSError("이메일 인증 실패 — 응답 코드 " + (str(code) if code is not None else "unknown"))
        if result.get("twoStepLoginUsage") != "web_login" or not result.get("redirectUrl"):
            raise GLSError("이메일 인증 후 추가 절차가 필요한 응답")
        target = urljoin(base, result["redirectUrl"])
        # WebHTTP checks scheme/host before sending any request.
        text, url = http.fetch(target, referer=url)
        print("이메일 인증 완료")
        return follow_html(http, text, url, "frmMenu")
    raise GLSError("이메일 인증 입력 횟수 종료")


def submit_school_works_login(http, text, url, page, login_id, password):
    """Submit the school's observed mail SSO login form once, if presented."""
    current = urlsplit(url)
    form = page.form("loginForm")
    if (current.hostname != "portal.skku.edu" or current.path != "/nw/oAuth/auth.do" or not form):
        return text, url, page
    action = urljoin(url, form["attrs"].get("action", ""))
    if (action != "https://portal.skku.edu/login/loginProc.do"
            or form["attrs"].get("method", "get").lower() != "post"):
        raise GLSError("학교 메일 SSO 로그인 폼의 전송 경로가 달라짐")
    fields = HTMLForms.values(form)
    if "user_id" not in fields or "user_pass" not in fields:
        raise GLSError("학교 메일 SSO 로그인 입력 항목이 달라짐")
    fields.update({"user_id": login_id, "user_pass": password})
    text, url = http.fetch(action, data=urlencode(fields).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, referer=url)
    return follow_html(http, text, url, "frmMenu")


def kingo_sso(http, login_id, password, ask=None):
    text, url = http.fetch("https://portal.skku.edu/index.do")
    text, url, page = follow_html(http, text, url, "LoginForm")
    if urlsplit(url).hostname != "login.skku.edu" or not page.form("LoginForm"):
        raise GLSError("킹고 로그인 화면을 확인하지 못함")
    login_page, login_url = page, url
    http.set_language_cookies()

    try:
        encoded_password = base64.b64encode(password.encode("latin-1")).decode("ascii")
    except UnicodeEncodeError:
        raise GLSError("학교 로그인 화면의 btoa 처리와 호환되지 않는 문자") from None
    payload = {"langSelect": "ko", "saveid": True, "userid": login_id, "userpwd": encoded_password}
    text, _ = http.fetch("https://login.skku.edu/loginAction",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}, referer=login_url)
    data = json.loads(text)
    if data.get("returnCode") != "success" or not data.get("pToken") or not data.get("returnUrl"):
        code = str(data.get("ERROR_KEY", data.get("ssoReturnCode", "unknown")))
        code = code if re.fullmatch(r"[\w.:-]{1,60}", code) else "unknown"
        raise GLSError(f"킹고 로그인 미완료: {code}")
    callback = data["returnUrl"]
    if urlsplit(callback).hostname != "portal.skku.edu":
        raise GLSError("예상과 다른 킹고 로그인 복귀 서버")

    form = login_page.form("testForm1")
    if not form:
        raise GLSError("로그인 결과 전달 폼 testForm1이 없음")
    fields = HTMLForms.values(form)
    fields.update({"pToken": data["pToken"], "tmpToken": data["pToken"], "lang": "ko"})
    text, url = http.fetch(callback, data=urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"}, referer=login_url)
    text, url, page = follow_html(http, text, url, "frmMenu")
    text, url, page = submit_school_works_login(http, text, url, page, login_id, password)
    text, url, page = finish_works_email(http, text, url, page, ask=ask)
    form = page.form("frmMenu")
    if not form or urlsplit(url).hostname != "portal.skku.edu":
        raise GLSError("지원하지 않는 추가 인증 화면으로 연결되었습니다.")

    fields = HTMLForms.values(form)
    system_field = next((f.get("name") for f in form["inputs"] if f.get("id") == "sys_gb" or f.get("name") == "sys_gb"), None)
    if not system_field:
        raise GLSError("frmMenu에서 sys_gb 입력 항목을 찾지 못함")
    fields[system_field] = "GLS"
    action = "https://kingoinfo.skku.edu/gaia/security/sso.do"
    method = form["attrs"].get("method", "get").upper()
    if method == "POST":
        text, gls_url = http.fetch(action, data=urlencode(fields).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"}, referer=url)
    elif method == "GET":
        text, gls_url = http.fetch(action + "?" + urlencode(fields), referer=url)
    else:
        raise GLSError("예상과 다른 frmMenu 전송 방식")
    _, gls_url, _ = follow_html(http, text, gls_url)
    if urlsplit(gls_url).hostname != "kingoinfo.skku.edu":
        raise GLSError("GLS로 연결되지 않음")
    return gls_url


def find_timetable_menu(rows):
    """Match the actual form path, as the school's menu code does."""
    path_matches, id_matches = [], []
    for row in rows:
        path = str(row.get("PGM_PATH_VAL", "")).strip().replace("\\", "/")
        path = re.split(r"[?#]", path, maxsplit=1)[0]
        if re.search(r"(?:^|[/\:])NHSSU040260M\.xfdl(?:\.js)?$", path, re.I):
            if row.get("MENU_ID"):
                path_matches.append(row)
        elif str(row.get("PGM_ID", "")).strip() == "NHSSU040260M" and row.get("MENU_ID"):
            id_matches.append(row)
    # The browser selects the first matching menu entry.
    return next(iter(path_matches or id_matches), None)


class GLSClient:
    def __init__(self):
        self.http = WebHTTP()
        self.passphrase = ""
        self.session_id = ""
        self.menu_id = ""
        self.program_id = ""
        self.active_hakbun = ""
        self.gls_url = BASE + "nxui/index.html"

    def request(self, path, body=None):
        headers = {"Content-Type": "text/xml", "X-NX-Content-Type": "2",
                   "X-Requested-With": "XMLHttpRequest", "Accept": "application/xml, text/xml, */*"}
        text, _ = self.http.fetch(BASE + path, None if body is None else body.encode("utf-8"),
                                  headers=headers, referer=self.gls_url)
        return text

    def call(self, path, service, params=None, outputs=(), program="", input_name="", input_ssv=""):
        args = dict(params or {})
        args.update({
            "_FIRST_IN_DS_NM": input_name, "_ALL_IN_DS_NM": f"{input_name}={input_name}" if input_name else "",
            "_FIRST_OUT_DS_NM": outputs[0] if outputs else "",
            "_ALL_OUT_DS_NM": " ".join(f"{x}={x}" for x in outputs),
            "_TRANSACTION_ID": service,
            "_MENU_ID": self.menu_id, "_PGM_ID": program,
            "_SESSION_ID": self.session_id,
        })
        if any(RS in str(v) or CS in str(v) for v in args.values()):
            raise GLSError("입력에 SSV 제어문자가 포함됨")
        body = "SSV:utf-8" + RS + "".join(f"{k}={v}{RS}" for k, v in args.items())
        body += input_ssv
        if self.passphrase:
            body = encrypt_request(body, self.passphrase)
        text = self.request(path, body)
        return parse_ssv(decrypt_response(text, self.passphrase))

    def login(self, login_id, password, ask=None):
        self.gls_url = kingo_sso(self.http, login_id, password, ask=ask)
        data = self.call("system/login/sessionLogin.do", "sessionLogin", outputs=LOGIN_DATASETS)
        info = first(data, "gdsUserInfo")
        self.passphrase = info.get("passphrase", "")
        self.session_id = info.get("sessionId", "")
        if not self.passphrase or not self.session_id:
            raise GLSError("GLS 인증 세션 정보가 없음")
        self.initialize_menu(data)
        menu = find_timetable_menu(data.get("gdsMenu", []))
        if menu is None:
            raise GLSError("주간테이블 메뉴를 찾지 못함")
        self.menu_id = str(menu["MENU_ID"])
        self.program_id = str(menu.get("PGM_ID") or "NHSSU040260M")
        return data

    def initialize_menu(self, data):
        # TOP_MENU.onload -> fnLoadNCreateTopMenu(0): the first gdsHakbun row.
        student = first(data, "gdsHakbun")
        names = ("INFO_MNU_TYPE", "HAKBUN", "PER_ID", "REG_NO", "USER_GB", "SEQ")
        if any(name not in student for name in names) or not student.get("INFO_MNU_TYPE") or not student.get("HAKBUN"):
            raise GLSError("학번별 메뉴 세션을 선택할 정보가 없음")
        params = {name: student[name] for name in names}
        self.active_hakbun = str(student["HAKBUN"])
        switched = self.call("security/switchSession.do", "switchUserSession", params,
            outputs=("gdsUserInfo",))
        updated = first(switched, "gdsUserInfo")
        data["gdsUserInfo"] = switched["gdsUserInfo"]
        self.passphrase = updated.get("passphrase") or self.passphrase
        self.session_id = updated.get("sessionId") or self.session_id
        menus = self.call("system/systemCommon/getMenuInfoList.do", "selectTreeviewInfoMenu",
            {"UP_MNU_ID": student["INFO_MNU_TYPE"]}, outputs=("gdsMenu",))
        data["gdsMenu"] = menus.get("gdsMenu", [])

    def timetable(self, hakbun, year, semester):
        """Return every course with original time, room and teaching-mode fields.

        Recorded lectures remain regular timetable entries in this version.
        """
        def query(path, service, params, output):
            return self.call(path, service, params, (output,), self.program_id)
        prefix = "NHSSU040260M/"
        student = first(query(prefix + "selectStd.do", "selectStd",
                              {"CAL_HAKBUN": hakbun}, "dsHakSangJungBo"), "dsHakSangJungBo")
        status = first(query("SKKUHS/selectHSSUUserGbInfo.do", "selectHSSUUserGbInfo",
                             {"HAKBUN": hakbun}, "dsHSSUUserGbInfo"), "dsHSSUUserGbInfo")
        input_ssv = (
            f"Dataset:dsHakJibJogun{RS}_Const_"
            f"{CS}GRP_CD:STRING(20)=HAK_JIBJUNG_S_JOGUN"
            f"{CS}USE_YN:STRING(1)=Y{CS}USR_DEF_CD1:STRING(1)=Y{RS}"
            f"_RowType_{CS}COM_CD:STRING(256){CS}CD_NM:STRING(256){RS}"
        )
        options = first(self.call(prefix + "selectHakJibJogun.do", "selectHakJibJogun",
            outputs=("dsHakJibJogun",), program=self.program_id,
            input_name="dsHakJibJogun", input_ssv=input_ssv), "dsHakJibJogun")
        if not student.get("HAKWIGWAJUNG_GB") or not status.get("STATUS_GB") or "COM_CD" not in options:
            raise GLSError("조회 조건에 필요한 학사 정보가 없음")
        term = {"1": "10", "2": "20"}[semester]
        data = query(prefix + "executeSelect_2016.do", "executeSelect_2016", {
            "YEAR": year, "TERM": term + options["COM_CD"],
            "HAKBUN": hakbun, "USER_STATUS": status["STATUS_GB"],
            "HAKWI_STATUS": student["HAKWIGWAJUNG_GB"],
            "YEARTERM": f"{year}학년도 {semester} 학기", "MODULE_CD": "%",
            "KOR_NAME": student.get("KOR_NAME", ""),
            "ENG_NAME": student.get("ENG_NAME", ""),
            "HAKGWA_NAME": student.get("HAKGWAJUNGONG_NM", ""),
        }, "dsGrdMain")
        if "dsGrdMain" not in data:
            raise GLSError("과목 목록 dsGrdMain이 응답에 없음")
        return data["dsGrdMain"]


def first(data, name):
    if not data.get(name):
        raise GLSError(f"필요한 데이터가 없음: {name}")
    return data[name][0]


def main():
    print("TimeAble GLS 시간표 조회")
    login_id = input("킹고 아이디: ").strip()
    try:
        password = getpass.getpass("비밀번호: ", echo_char="*")
    except TypeError:
        password = getpass.getpass("비밀번호: ")
    year = input(f"학년도 [{datetime.now().year}]: ").strip() or str(datetime.now().year)
    semester = input("학기 1/2 [2]: ").strip() or "2"
    if not login_id or not password or not year.isdigit() or semester not in {"1", "2"}:
        raise GLSError("입력값을 확인해 주세요")
    client = GLSClient()
    print("로그인 중...")
    try:
        client.login(login_id, password)
    finally:
        password = ""
    print("시간표 조회 중...")
    rows = client.timetable(client.active_hakbun, year, semester)
    print(f"\n과목 {len(rows)}개")
    for row in rows:
        print(f"\n{row.get('GYOGWAMOK_NM', '')} ({row.get('HAKSU_NO', '')}-{row.get('BUNBAN', '')})")
        print("  시간:", row.get("SUUP_YOIL_GYOSI", ""))
        print("  형태:", row.get("SUUP_HYUNGTAE_CD", ""))
    if not rows:
        print("해당 학기에 조회된 과목이 없습니다. 학년도와 학기를 확인해 주세요.")


if __name__ == "__main__":
    try:
        main()
    except GLSError as error:
        print("중단:", error)
    except KeyboardInterrupt:
        print("\n종료")
    except Exception as error:
        print("중단: 예상하지 못한 응답 형식 —", type(error).__name__)
