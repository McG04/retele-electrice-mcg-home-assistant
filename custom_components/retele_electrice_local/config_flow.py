"""Config flow for Rețele Electrice (McG)."""

from __future__ import annotations

import aiohttp
import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .api import (
    ReteleElectriceApi,
    ReteleElectriceAuthError,
    ReteleElectriceError,
)
from .const import (
    BROWSER_HEADERS,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_POD,
    CONF_SCAN_INTERVAL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class ReteleElectriceLocalConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle setup from the Home Assistant UI."""

    VERSION = 1

    def __init__(self) -> None:
        self._email = ""
        self._password = ""
        self._pods: list[dict] = []

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            self._email = user_input[CONF_EMAIL].strip().lower()
            self._password = user_input[CONF_PASSWORD]

            session = aiohttp.ClientSession(
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                headers=BROWSER_HEADERS,
            )
            try:
                api = ReteleElectriceApi(
                    session,
                    email=self._email,
                    password=self._password,
                    pod="",
                )
                await api.async_login()
                self._pods = await api.async_get_pods()
            except ReteleElectriceAuthError as err:
                _LOGGER.warning("Autentificarea Rețele Electrice a eșuat: %s", err)
                errors["base"] = "invalid_auth"
            except ReteleElectriceError as err:
                _LOGGER.error("Configurarea Rețele Electrice a eșuat: %s", err)
                errors["base"] = "cannot_connect"
            finally:
                await session.close()

            if not errors:
                return await self.async_step_select_pod()

        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.PASSWORD
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_select_pod(self, user_input=None):
        """Let the user choose a POD discovered after authentication."""
        errors: dict[str, str] = {}
        pod_options = self._pod_options(self._pods)
        if user_input is not None:
            pod = user_input[CONF_POD]
            if pod not in pod_options:
                errors["base"] = "invalid_pod"
            else:
                await self.async_set_unique_id(f"{self._email}:{pod}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Rețele Electrice {pod}",
                    data={
                        CONF_EMAIL: self._email,
                        CONF_PASSWORD: self._password,
                        CONF_POD: pod,
                        CONF_SCAN_INTERVAL: DEFAULT_SCAN_INTERVAL,
                    },
                )

        return self.async_show_form(
            step_id="select_pod",
            data_schema=vol.Schema({vol.Required(CONF_POD): vol.In(pod_options)}),
            errors=errors,
        )

    @staticmethod
    def _pod_options(pods: list[dict]) -> dict[str, str]:
        options: dict[str, str] = {}
        for item in pods:
            pod = str(item.get("Name") or item.get("POD__c") or "").strip().upper()
            if not pod:
                continue
            address = str(
                item.get("POD_Address__c")
                or item.get("Address__c")
                or item.get("Service_Address__c")
                or ""
            ).strip()
            options[pod] = f"{pod} — {address}" if address else pod
        return options

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return ReteleElectriceOptionsFlow()


class ReteleElectriceOptionsFlow(config_entries.OptionsFlow):
    """Allow refresh interval changes without reinstalling."""

    async def async_step_init(self, user_input=None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL,
            self.config_entry.data.get(
                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
            ),
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL
                        ),
                    )
                }
            ),
        )
