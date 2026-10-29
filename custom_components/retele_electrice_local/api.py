"""Independent client for the public Rețele Electrice customer portal."""

from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any
from urllib.parse import urljoin

from aiohttp import ClientResponse, ClientSession, ClientTimeout
from .const import (
    AURA_APP_UID_FALLBACK,
    AURA_FWUID_FALLBACK,
    AURA_URL,
    BASE_URL,
    HOME_URL,
    LOGIN_URL,
    METHOD_ARCHIVE,
    METHOD_FIND_INSTANT,
    METHOD_OUTAGES,
    METHOD_POD_DETAILS,
    METHOD_REQUEST_INSTANT,
    METHOD_SMART_METER,
    VF_ARCHIVE,
    VF_CURVE,
    VF_OUTAGES,
    VF_SMART_HISTORY,
    VF_SMART_INSTANT,
)

_LOGGER = logging.getLogger(__name__)
_TIMEOUT = ClientTimeout(total=45)


class ReteleElectriceError(Exception):
    """Base client error."""


class ReteleElectriceAuthError(ReteleElectriceError):
    """Authentication failed."""


class ReteleElectriceConnectionError(ReteleElectriceError):
    """Portal could not be reached."""


class ReteleElectriceProtocolError(ReteleElectriceError):
    """Portal response changed or could not be parsed."""


@dataclass(slots=True)
class _VisualforceForm:
    """Visualforce form metadata used by an A4J request."""

    action: str
    form_id: str
    submit_id: str
    hidden: dict[str, str]


class _PortalHtmlParser(HTMLParser):
    """Collect the small subset of form metadata used by the portal."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: dict[str, str] = {}
        self.hidden: dict[str, str] = {}
        self.inputs: dict[str, str] = {}
        self.scripts: list[str] = []
        self._script_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if tag == "form" and values.get("id"):
            self.forms[str(values["id"])] = str(values.get("action") or "")
        elif tag == "input" and values.get("name"):
            name = str(values["name"])
            input_type = str(values.get("type") or "text").lower()
            self.inputs[name] = input_type
            if input_type == "hidden":
                self.hidden[name] = str(values.get("value") or "")
        elif tag == "script":
            self._script_parts = []

    def handle_data(self, data: str) -> None:
        if self._script_parts is not None:
            self._script_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script_parts is not None:
            self.scripts.append("".join(self._script_parts))
            self._script_parts = None


class ReteleElectriceApi:
    """Small asynchronous client for Salesforce Experience Cloud."""

    def __init__(
        self,
        session: ClientSession,
        *,
        email: str,
        password: str,
        pod: str,
    ) -> None:
        self._session = session
        self._email = email.strip()
        self._password = password
        self.pod = pod.strip().upper()
        self._logged_in = False
        self._aura_token: str | None = None
        self._aura_fwuid: str | None = None
        self._aura_app_uid: str | None = None
        self._account_info: dict[str, Any] = {}
        self._pod_record: dict[str, Any] = {}

    async def async_login(self) -> None:
        """Authenticate through the portal's Visualforce login form."""
        try:
            self._logged_in = False
            self._aura_token = None
            self._session.cookie_jar.clear()
            response = await self._session.get(LOGIN_URL, timeout=_TIMEOUT)
            text = await self._read_response(response)
            parsed = self._parse_html(text)
            form_action = parsed.forms.get("loginPage:loginForm")
            if form_action is None:
                raise ReteleElectriceProtocolError("Formularul de autentificare lipsește")

            username_field = self._find_input(parsed, "username", "email")
            password_field = self._find_input(parsed, "password", "passwd", "pw")
            login_submit = self._find_submit_id(text)
            payload = dict(parsed.hidden)
            payload.update(
                {
                    "loginPage:loginForm": "loginPage:loginForm",
                    username_field: self._email,
                    password_field: self._password,
                    login_submit: login_submit,
                }
            )
            action = urljoin(BASE_URL, form_action or LOGIN_URL)
            response = await self._session.post(
                action,
                data=payload,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Origin": BASE_URL,
                    "Referer": str(response.url),
                    "Cache-Control": "max-age=0",
                },
                allow_redirects=False,
                timeout=_TIMEOUT,
            )
            body = await self._read_response(response)

            redirect_url = response.headers.get("Location")
            if not redirect_url:
                redirect_url = self._extract_frontdoor_url(body)
            if not redirect_url:
                if "loginPage:loginForm" in body:
                    raise ReteleElectriceAuthError("Email sau parolă incorectă")
                raise ReteleElectriceProtocolError(
                    "Portalul nu a returnat redirectul de autentificare"
                )

            response = await self._session.get(
                urljoin(BASE_URL, redirect_url),
                allow_redirects=True,
                timeout=_TIMEOUT,
            )
            await self._read_response(response)
            response = await self._session.get(
                HOME_URL, allow_redirects=True, timeout=_TIMEOUT
            )
            home_page = await self._read_response(response)
        except ReteleElectriceError:
            raise
        except Exception as err:
            raise ReteleElectriceConnectionError(str(err)) from err

        final_url = str(response.url)
        if "PEDRO_SiteLogin" in final_url or "loginPage:loginForm" in home_page:
            raise ReteleElectriceAuthError("Email sau parolă incorectă")
        if "/s/" not in final_url:
            raise ReteleElectriceAuthError("Portalul nu a confirmat autentificarea")

        self._aura_token = self._extract_aura_token(home_page)
        page_fwuid, page_app_uid = self._extract_aura_context(home_page)
        self._aura_fwuid = page_fwuid or AURA_FWUID_FALLBACK
        self._aura_app_uid = page_app_uid or AURA_APP_UID_FALLBACK
        self._logged_in = True

    async def async_test_credentials(self) -> None:
        """Validate credentials without exposing account data."""
        await self.async_login()

    async def async_get_pods(self) -> list[dict[str, Any]]:
        """Return the PODs visible in the authenticated customer account."""
        if not self._logged_in:
            await self.async_login()
        result = await self._aura_call(
            descriptor="apex://PED_Utility/ACTION$getPODs",
            calling_descriptor="markup://c:PED_HomePage",
        )
        if not isinstance(result, list):
            raise ReteleElectriceProtocolError(
                "Portalul nu a returnat lista punctelor de consum"
            )
        pods = [item for item in result if isinstance(item, dict)]
        if not pods:
            raise ReteleElectriceProtocolError(
                "Nu există niciun POD disponibil în acest cont"
            )
        return pods

    async def _aura_call(
        self,
        *,
        descriptor: str,
        calling_descriptor: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Call one Salesforce Aura action using parameters exposed by the portal."""
        if not self._aura_token or not self._aura_fwuid or not self._aura_app_uid:
            raise ReteleElectriceProtocolError(
                "Portalul nu a furnizat parametrii Aura necesari"
            )
        action = {
            "id": "1;a",
            "descriptor": descriptor,
            "callingDescriptor": calling_descriptor,
            "params": params or {},
            "version": None,
        }
        context = {
            "mode": "PROD",
            "fwuid": self._aura_fwuid,
            "app": "siteforce:communityApp",
            "loaded": {
                "APPLICATION@markup://siteforce:communityApp": self._aura_app_uid
            },
            "dn": [],
            "globals": {},
            "uad": True,
        }
        response = await self._session.post(
            AURA_URL,
            data={
                "message": json.dumps({"actions": [action]}, separators=(",", ":")),
                "aura.context": json.dumps(context, separators=(",", ":")),
                "aura.pageURI": "/s/",
                "aura.token": self._aura_token,
            },
            headers={
                "Accept": "*/*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": HOME_URL,
                "sec-fetch-dest": "empty",
                "sec-fetch-mode": "cors",
                "sec-fetch-site": "same-origin",
            },
            timeout=_TIMEOUT,
        )
        body = await self._read_response(response)
        try:
            data = json.loads(body)
        except json.JSONDecodeError as err:
            raise ReteleElectriceProtocolError(
                "Răspunsul Aura nu este JSON"
            ) from err
        actions = data.get("actions") if isinstance(data, dict) else None
        if not actions or not isinstance(actions[0], dict):
            raise ReteleElectriceProtocolError("Răspunsul Aura este incomplet")
        action_result = actions[0]
        if action_result.get("state") != "SUCCESS":
            error = action_result.get("error")
            raise ReteleElectriceProtocolError(
                f"Cererea Aura a fost respinsă: {error}"
            )
        return action_result.get("returnValue")

    async def async_fetch_all(self) -> dict[str, Any]:
        """Fetch every data family supported by the account."""
        if not self._logged_in:
            await self.async_login()

        data: dict[str, Any] = {"pod": self.pod}
        failures: dict[str, str] = {}

        # Aura is the portal's primary data source and remains useful even when
        # one of the external Visualforce web services is temporarily absent.
        try:
            pods = await self.async_get_pods()
            self._pod_record = next(
                (
                    item
                    for item in pods
                    if str(item.get("Name") or item.get("POD__c") or "").upper()
                    == self.pod
                ),
                {},
            )
            if self._pod_record:
                data["pod_details"] = dict(self._pod_record)
        except ReteleElectriceError as err:
            failures["pod_list"] = str(err)

        try:
            account = await self._aura_call(
                descriptor="apex://PED_Utility/ACTION$getAccountInfo",
                calling_descriptor="markup://c:PED_CustomProfileHeader",
            )
            if isinstance(account, dict):
                self._account_info = account
                data["account_info"] = account
        except ReteleElectriceError as err:
            failures["account_info"] = str(err)

        try:
            details = await self._aura_call(
                descriptor=(
                    "apex://PED_POD_Details_Controller/"
                    "ACTION$getUserDetailsPodInformation"
                ),
                calling_descriptor="markup://c:PED_POD_Details",
                params={"PodName": self.pod},
            )
            if isinstance(details, dict):
                merged = dict(data.get("pod_details") or {})
                merged.update(details)
                data["pod_details"] = merged
        except ReteleElectriceError as err:
            failures["pod_aura_details"] = str(err)

        calls = (
            ("supplier", self.async_fetch_pod_details),
            ("archive", self.async_fetch_archive),
            ("outages", self.async_fetch_outages),
        )
        for key, call in calls:
            try:
                value = await call()
                if value:
                    if key == "supplier":
                        merged = dict(data.get("pod_details") or {})
                        merged.update(value)
                        data["pod_details"] = merged
                    else:
                        data[key] = value
            except ReteleElectriceAuthError:
                self._logged_in = False
                await self.async_login()
                value = await call()
                if value:
                    if key == "supplier":
                        merged = dict(data.get("pod_details") or {})
                        merged.update(value)
                        data["pod_details"] = merged
                    else:
                        data[key] = value
            except ReteleElectriceError as err:
                failures[key] = str(err)
                _LOGGER.debug("Setul %s nu este disponibil: %s", key, err)

        if self._has_smart_meter_access():
            try:
                smart_meter = await self.async_fetch_smart_meter()
                if smart_meter:
                    data["smart_meter"] = smart_meter
            except ReteleElectriceError as err:
                failures["smart_meter"] = str(err)
                _LOGGER.debug("Smart Meter nu este disponibil: %s", err)

        if failures:
            data["unavailable_data"] = failures
        if not any(key in data for key in ("pod_details", "account_info", "archive", "outages")):
            raise ReteleElectriceProtocolError(
                "Portalul nu a returnat niciun set de date utilizabil"
            )
        return data

    async def async_fetch_pod_details(self) -> dict[str, Any]:
        """Fetch supplier, meter and POD details."""
        return await self._vf_call(
            VF_CURVE, METHOD_POD_DETAILS, [self.pod, "Client_Company"]
        )

    async def async_fetch_archive(self) -> dict[str, Any]:
        """Fetch recent meter readings."""
        today = date.today()
        start = (today - timedelta(days=365)).strftime("%d/%m/%Y 00:00:00")
        end = today.strftime("%d/%m/%Y 23:59:59")
        cnp, cui = self._customer_identifiers()
        params = ["", cui, cnp, self.pod, start, end]
        return await self._vf_call(VF_ARCHIVE, METHOD_ARCHIVE, params)

    async def async_fetch_outages(self) -> dict[str, Any]:
        """Fetch current outage information."""
        return await self._vf_call(VF_OUTAGES, METHOD_OUTAGES, [self.pod, "RO"])

    async def async_fetch_smart_meter(self) -> dict[str, Any]:
        """Fetch load-profile totals when the distributor exposes them."""
        today = date.today()
        start = today.replace(day=1).strftime("%d/%m/%Y 00:00:00")
        end = today.strftime("%d/%m/%Y 23:59:59")
        cnp, _cui = self._customer_identifiers()
        params = [cnp, "", self.pod, start, end]
        result = await self._vf_call(
            VF_SMART_HISTORY, METHOD_SMART_METER, params
        )
        if result.get("errorCode"):
            return {}
        return result

    async def async_refresh_instant(self) -> dict[str, Any]:
        """Request and then retrieve instant smart-meter values."""
        cnp, _cui = self._customer_identifiers()
        params = [cnp, "", self.pod]
        await self._vf_call(VF_SMART_INSTANT, METHOD_REQUEST_INSTANT, params)
        return await self._vf_call(
            VF_SMART_INSTANT, METHOD_FIND_INSTANT, params
        )

    def _customer_identifiers(self) -> tuple[str, str]:
        """Return the CNP/fiscal code and CUI exposed by Aura."""
        sources = (self._account_info, self._pod_record)
        cnp = ""
        cui = ""
        for source in sources:
            cnp = cnp or str(
                source.get("CNP__c")
                or source.get("Fiscal_Code__c")
                or source.get("cnp")
                or ""
            )
            cui = cui or str(
                source.get("Univocal_Code__c")
                or source.get("CUI__c")
                or source.get("cui")
                or ""
            )
        return cnp, cui

    def _has_smart_meter_access(self) -> bool:
        """Use the Smart Meter services only when the account advertises them."""
        for key in (
            "Smart_meter__c",
            "IsSmartMeter__c",
            "SmartMeter__c",
            "smartMeter",
        ):
            value = self._pod_record.get(key)
            if value is True or str(value).strip().lower() in ("true", "1", "yes"):
                return True
        return False

    async def _vf_call(
        self, endpoint: str, method_name: str, method_params: list[Any] | str
    ) -> dict[str, Any]:
        """Execute one Visualforce A4J proxy call."""
        url = urljoin(BASE_URL, endpoint)
        try:
            response = await self._session.get(
                url, headers={"Referer": HOME_URL}, timeout=_TIMEOUT
            )
            page = await self._read_response(response)
            if "PEDRO_SiteLogin" in str(response.url):
                raise ReteleElectriceAuthError("Sesiunea portalului a expirat")
            form = self._parse_vf_form(page, url)

            params_string = (
                ",".join("" if value is None else str(value) for value in method_params)
                if isinstance(method_params, list)
                else method_params
            )
            payload = dict(form.hidden)
            payload.update(
                {
                    "AJAXREQUEST": "_viewRoot",
                    form.form_id: form.form_id,
                    "methodN": method_name,
                    "params": params_string,
                    "uniqueId": f"script_{uuid.uuid4().hex}",
                    form.submit_id: form.submit_id,
                }
            )
            response = await self._session.post(
                form.action,
                data=payload,
                headers={
                    "Accept": "*/*",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": BASE_URL,
                    "Referer": url,
                    "Faces-Request": "partial/ajax",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=_TIMEOUT,
            )
            body = await self._read_response(response)
            return self._extract_json(body)
        except ReteleElectriceError:
            raise
        except Exception as err:
            raise ReteleElectriceConnectionError(str(err)) from err

    @staticmethod
    async def _read_response(response: ClientResponse) -> str:
        if response.status in (401, 403):
            raise ReteleElectriceAuthError(f"HTTP {response.status}")
        if response.status >= 400:
            raise ReteleElectriceConnectionError(f"HTTP {response.status}")
        return await response.text(errors="replace")

    @staticmethod
    def _parse_html(page: str) -> _PortalHtmlParser:
        parser = _PortalHtmlParser()
        parser.feed(page)
        return parser

    @staticmethod
    def _find_input(parsed: _PortalHtmlParser, *terms: str) -> str:
        for name, input_type in parsed.inputs.items():
            lowered = name.lower()
            if input_type != "hidden" and any(term in lowered for term in terms):
                return name
        raise ReteleElectriceProtocolError("Câmpul de autentificare lipsește")

    @staticmethod
    def _find_submit_id(page: str) -> str:
        match = re.search(
            r"loginPage:loginForm:j_id\d+\s*,\s*loginPage:loginForm:j_id\d+",
            page,
        )
        if match:
            return match.group(0).split(",", 1)[0]
        match = re.search(r"loginPage:loginForm:j_id\d+", page)
        if match:
            return match.group(0)
        raise ReteleElectriceProtocolError("Butonul de autentificare lipsește")

    @staticmethod
    def _extract_frontdoor_url(page: str) -> str | None:
        decoded = html.unescape(page)
        patterns = (
            r"window\.location\.(?:replace|assign)\s*\(\s*['\"]([^'\"]*frontdoor\.jsp[^'\"]*)",
            r"window\.location\.href\s*=\s*['\"]([^'\"]*frontdoor\.jsp[^'\"]*)",
            r"handleRedirect\s*\(\s*['\"]([^'\"]*frontdoor\.jsp[^'\"]*)",
        )
        for pattern in patterns:
            match = re.search(pattern, decoded)
            if match:
                return match.group(1)
        return None

    def _extract_aura_token(self, page: str) -> str | None:
        for cookie in self._session.cookie_jar:
            if cookie.key.startswith("__Host-ERIC-PROD") or cookie.key.startswith(
                "__Host-ERIC_PROD"
            ):
                return cookie.value
        decoded = html.unescape(page)
        cookie_name_match = re.search(
            r'["\']eikoocnekot["\']\s*:\s*["\']([^"\']+)', decoded
        )
        if cookie_name_match:
            expected_name = cookie_name_match.group(1)
            for cookie in self._session.cookie_jar:
                if cookie.key == expected_name:
                    return cookie.value
        match = re.search(r"jwt=(eyJ[A-Za-z0-9_-]+\.\.[A-Za-z0-9_-]+)", decoded)
        return match.group(1) if match else None

    @staticmethod
    def _extract_aura_context(page: str) -> tuple[str | None, str | None]:
        decoded = html.unescape(page).replace(r'\"', '"')
        fwuid_match = re.search(r'["\']fwuid["\']\s*:\s*["\']([^"\']+)', decoded)
        app_match = re.search(
            r'["\']APPLICATION@markup://siteforce:communityApp["\']\s*:\s*["\']([^"\']+)',
            decoded,
        )
        return (
            fwuid_match.group(1) if fwuid_match else None,
            app_match.group(1) if app_match else None,
        )

    @classmethod
    def _parse_vf_form(cls, page: str, fallback_url: str) -> _VisualforceForm:
        parsed = cls._parse_html(page)
        if not parsed.forms:
            raise ReteleElectriceProtocolError("Formular Visualforce lipsă")
        form_id, form_action = next(iter(parsed.forms.items()))
        submit_id = ""
        for script in parsed.scripts:
            match = re.search(r"similarityGroupingId['\"]\s*:\s*['\"]([^'\"]+)", script)
            if match:
                submit_id = match.group(1)
                break
        if not submit_id:
            raise ReteleElectriceProtocolError("Identificatorul A4J lipsește")
        action = urljoin(BASE_URL, form_action or fallback_url)
        return _VisualforceForm(action, form_id, submit_id, parsed.hidden)

    @staticmethod
    def _extract_json(body: str) -> dict[str, Any]:
        decoded = html.unescape(body).replace("&quot;", '"')
        candidates = [
            decoded,
            decoded.replace(r'\"', '"'),
            decoded.replace(r"\'", "'"),
        ]
        candidates.append(re.sub(r"<[^>]+>", " ", decoded))

        decoder = json.JSONDecoder()
        for text in candidates:
            for match in re.finditer(r"[\{\[]", text):
                try:
                    value, _ = decoder.raw_decode(text[match.start() :])
                except (json.JSONDecodeError, TypeError):
                    continue
                if isinstance(value, dict):
                    return value
                if isinstance(value, list):
                    return {"items": value}
        raise ReteleElectriceProtocolError("Răspunsul serviciului nu conține JSON")
