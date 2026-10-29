"""Constants for Rețele Electrice (McG)."""

from __future__ import annotations

DOMAIN = "retele_electrice_local"
NAME = "Rețele Electrice (McG)"
ATTRIBUTION = "Date furnizate de portalul Rețele Electrice România"

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_POD = "pod"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 3600
MIN_SCAN_INTERVAL = 3600
MAX_SCAN_INTERVAL = 86400

PLATFORMS = ["sensor", "button"]

BASE_URL = "https://contulmeu.reteleelectrice.ro"
LOGIN_URL = (
    f"{BASE_URL}/PEDRO_SiteLogin"
    "?startURL=%2Fs%2F"
    "&refURL=https%3A%2F%2Fcontulmeu.reteleelectrice.ro%2Fs%2F"
)
HOME_URL = f"{BASE_URL}/s/"
AURA_URL = f"{BASE_URL}/s/sfsites/aura"

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
    "Upgrade-Insecure-Requests": "1",
}

# Portal values used only when the authenticated page omits its Aura bootstrap
# metadata. The page-provided values always take precedence.
AURA_FWUID_FALLBACK = (
    "TXFWNVprQUZzQnEtNXVXYTFLQ2ppdzJEa1N5enhOU3R5QWl2VzNveFZTbGcxMy4t"
    "MjE0NzQ4MzY0OC4xMzEwNzIwMA"
)
AURA_APP_UID_FALLBACK = "1537_wmTAUxhOaM_47EClrN56Dw"

VF_CURVE = "/PED_ProxyCallWSAsync_Curve_VF"
VF_ARCHIVE = "/PED_ProxyCallWSAsynSingleSelf_VF"
VF_OUTAGES = "/PED_ProxyCallWSAsynPowerOutages_VF"
VF_SMART_HISTORY = "/PED_ProxyCallWSAsync_SmartMeter_Vf"
VF_SMART_CURRENT = "/PED_ProxyCallWSAsynSmartMeterCurrentData"
VF_SMART_INSTANT = "/PED_ProxyCallWSAsynSmartMeterIstantData"

METHOD_POD_DETAILS = "queryPOD"
METHOD_ARCHIVE = "RetriveSingleSelf"
METHOD_OUTAGES = "PowerOutages"
METHOD_SMART_METER = "FindOutMeterHistoryData"
METHOD_REQUEST_INSTANT = "ReqMeterInstantData"
METHOD_FIND_INSTANT = "FindOutMeterInstantData"
