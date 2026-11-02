"""Dependency-free behavioral tests of the integration's auth and privacy paths."""
import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components/retele_electrice_local"


def load_nodes(filename, names, env):
    tree = ast.parse((ROOT / filename).read_text())
    nodes = [n for n in tree.body if getattr(n, "name", None) in names]
    exec(compile(ast.Module(nodes, type_ignores=[]), filename, "exec"), env)
    return env


class PortalError(Exception):
    pass


class AuthError(PortalError):
    pass


class AuthFailed(Exception):
    pass


class UpdateFailed(Exception):
    pass


class Abort(Exception):
    pass


class FlowBase:
    def __init_subclass__(cls, **kwargs):
        pass

    def _get_reauth_entry(self):
        return self.entry

    async def async_set_unique_id(self, value):
        self.unique_id = value

    def _abort_if_unique_id_mismatch(self, *, reason):
        if self.unique_id != self.entry.unique_id:
            raise Abort(reason)

    def async_update_reload_and_abort(self, entry, *, data_updates):
        entry.data = {**entry.data, **data_updates}
        return {"type": "abort", "reason": "reauth_successful", "reload": True}

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}


class Session:
    def __init__(self, **kwargs):
        self.closed = False

    async def close(self):
        self.closed = True


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.sessions = []
        self.failure = None
        self.pods = [{"Name": "POD1"}]
        owner = self

        def session(**kwargs):
            obj = Session()
            self.sessions.append(obj)
            return obj

        class Api:
            def __init__(self, session, **kwargs):
                owner.credentials = kwargs

            async def async_test_credentials(self):
                if owner.failure:
                    raise owner.failure

            async def async_get_pods(self):
                return owner.pods

        env = {
            "config_entries": SimpleNamespace(ConfigFlow=FlowBase),
            "DOMAIN": "retele_electrice_local",
            "callback": lambda fn: fn,
            "aiohttp": SimpleNamespace(ClientSession=session, CookieJar=lambda **kw: None),
            "BROWSER_HEADERS": {},
            "ReteleElectriceApi": Api,
            "ReteleElectriceAuthError": AuthError,
            "ReteleElectriceError": PortalError,
            "vol": SimpleNamespace(Schema=lambda s: s, Required=lambda k, **kw: k),
            "selector": SimpleNamespace(TextSelector=lambda c: c, TextSelectorConfig=lambda **kw: kw, TextSelectorType=SimpleNamespace(PASSWORD="password")),
            "CONF_EMAIL": "email", "CONF_PASSWORD": "password", "CONF_POD": "pod",
        }
        load_nodes("config_flow.py", {"ReteleElectriceLocalConfigFlow"}, env)
        self.flow = env["ReteleElectriceLocalConfigFlow"]()
        self.flow.entry = SimpleNamespace(
            unique_id="user@example.test:POD1",
            data={"email": "user@example.test", "password": "old", "pod": "POD1", "scan_interval": 3600},
        )

    async def submit(self, email="user@example.test"):
        return await self.flow.async_step_reauth_confirm({"email": email, "password": "new"})

    async def test_reauth_displays_form_without_network(self):
        result = await self.flow.async_step_reauth(self.flow.entry.data)
        self.assertEqual(result["step_id"], "reauth_confirm")
        self.assertEqual(self.sessions, [])

    async def test_success_keeps_entry_pod_and_settings(self):
        entry = self.flow.entry
        result = await self.submit(" USER@EXAMPLE.TEST ")
        self.assertEqual(result["reason"], "reauth_successful")
        self.assertTrue(result["reload"])
        self.assertIs(self.flow.entry, entry)
        self.assertEqual(entry.data, {"email": "user@example.test", "password": "new", "pod": "POD1", "scan_interval": 3600})
        self.assertTrue(self.sessions[-1].closed)

    async def test_invalid_auth_and_connection_keep_old_credentials(self):
        for failure, reason in [(AuthError(), "invalid_auth"), (PortalError(), "cannot_connect")]:
            self.failure = failure
            result = await self.submit()
            self.assertEqual(result["errors"], {"base": reason})
            self.assertEqual(self.flow.entry.data["password"], "old")
            self.assertTrue(self.sessions[-1].closed)

    async def test_missing_pod_keeps_old_credentials(self):
        self.pods = [{"Name": "OTHER"}]
        self.assertEqual((await self.submit())["errors"], {"base": "invalid_pod"})
        self.assertEqual(self.flow.entry.data["password"], "old")

    async def test_wrong_account_aborts(self):
        with self.assertRaisesRegex(Abort, "wrong_account"):
            await self.submit("other@example.test")
        self.assertEqual(self.flow.entry.data["password"], "old")
        self.assertTrue(self.sessions[-1].closed)


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_auth_failure_is_distinct_from_temporary_failure(self):
        class Base:
            def __class_getitem__(cls, item):
                return cls
        env = {"DataUpdateCoordinator": Base, "ReteleElectriceAuthError": AuthError,
               "ReteleElectriceError": PortalError, "ConfigEntryAuthFailed": AuthFailed,
               "UpdateFailed": UpdateFailed, "HomeAssistant": object}
        load_nodes("coordinator.py", {"ReteleElectriceCoordinator"}, env)
        coordinator = object.__new__(env["ReteleElectriceCoordinator"])
        for failure, expected in [(AuthError(), AuthFailed), (PortalError(), UpdateFailed)]:
            async def fetch():
                raise failure
            coordinator.api = SimpleNamespace(async_fetch_all=fetch)
            with self.assertRaises(expected):
                await coordinator._async_update_data()


class PrivacyTests(unittest.TestCase):
    def test_only_allowlisted_scalars_reach_both_sensors(self):
        env = {"Any": object}
        load_nodes("sensor.py", {"_public_pod_attributes"}, env)
        tree = ast.parse((ROOT / "sensor.py").read_text())
        sensors = next(n.value for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SENSORS" for t in n.targets))
        details = {"activ": "Activ", "furnizor": "Supplier", "cui": "customer-id", "CNP__c": "personal-id", "Fiscal_Code__c": "tax-id", "Address__c": "private-address", "unknown": {"secret": "value"}}
        for call, allowed in zip(sensors.elts[:2], [{"activ": "Activ"}, {"furnizor": "Supplier"}]):
            attrs = next(k.value for k in call.keywords if k.arg == "attrs_fn")
            fn = eval(compile(ast.Expression(attrs), "sensor.py", "eval"), env)
            self.assertEqual(fn({"pod_details": details}), allowed)
            self.assertEqual(fn({"pod_details": {"activ": details, "furnizor": [details]}}), {})
            self.assertEqual(fn({"pod_details": None}), {})
        value = next(k.value for k in sensors.elts[1].keywords if k.arg == "value_fn")
        fn = eval(compile(ast.Expression(value), "sensor.py", "eval"), env)
        self.assertEqual(fn({"pod_details": {"cui": "customer-id"}}), "Disponibil")


if __name__ == "__main__":
    unittest.main()
