import os
from functools import partial
from unittest import mock

import pytest
from lightning_cloud.openapi import (
    AppinstancesIdBody,
    V1LightningappInstanceSpec,
    V1LightningappInstanceState,
    V1ListLightningappInstancesResponse,
)

from lightning_app import LightningApp, LightningFlow, LightningWork
from lightning_app.core.flow import _RootFlow
from lightning_app.frontend import StaticWebFrontend
from lightning_app.utilities.app_helpers import (
    _handle_is_headless,
    _is_headless,
    _MagicMockJsonSerializable,
    AppStatePlugin,
    BaseStatePlugin,
    InMemoryStateStore,
    is_overridden,
    is_static_method,
    StateStore,
)
from lightning_app.utilities.exceptions import LightningAppStateException


class Work(LightningWork):
    def run(self):
        pass


class Flow(LightningFlow):
    def run(self):
        pass


def test_is_overridden():
    # edge cases
    assert not is_overridden("whatever", None)
    with pytest.raises(ValueError, match="Expected a parent"):
        is_overridden("whatever", object())
    flow = Flow()
    assert not is_overridden("whatever", flow)
    assert not is_overridden("whatever", flow, parent=Flow)
    # normal usage
    assert is_overridden("run", flow)
    work = Work()
    assert is_overridden("run", work)


def test_simple_app_store():

    store = InMemoryStateStore()
    user_id = "1234"
    store.add(user_id)
    state = {"data": user_id}
    store.set_app_state(user_id, state)
    store.set_served_state(user_id, state)
    store.set_served_session_id(user_id, user_id)
    assert store.get_app_state(user_id) == state
    assert store.get_served_state(user_id) == state
    assert store.get_served_session_id(user_id) == user_id
    store.remove(user_id)
    assert isinstance(store, StateStore)


@mock.patch("lightning_app.core.constants.APP_STATE_MAX_SIZE_BYTES", 120)
def test_simple_app_store_warning():
    store = InMemoryStateStore()
    user_id = "1234"
    store.add(user_id)
    state = {"data": "I'm a state that's larger than 120 bytes"}
    with pytest.raises(LightningAppStateException, match="is larger than the"):
        store.set_app_state(user_id, state)


def test_base_state_plugin():
    class DummyStatePlugin(BaseStatePlugin):
        def should_update_app(self, deep_diff):
            super().should_update_app(deep_diff)

        def get_context(self):
            super().get_context()

        def render_non_authorized(self):
            super().render_non_authorized()

    plugin = DummyStatePlugin()
    plugin.should_update_app(None)
    plugin.get_context()
    plugin.render_non_authorized()

    plugin = AppStatePlugin()
    plugin.should_update_app(None)
    plugin.get_context()
    plugin.render_non_authorized()


def test_is_static_method():
    class A:
        @staticmethod
        def a(self):
            pass

        @staticmethod
        def b(a):
            pass

        def c(self):
            pass

    assert is_static_method(A, "a")
    assert is_static_method(A, "b")
    assert not is_static_method(A, "c")


class FlowWithURLLayout(Flow):
    def configure_layout(self):
        return {"name": "test", "content": "https://appurl"}


class FlowWithFrontend(Flow):
    def configure_layout(self):
        return StaticWebFrontend(".")


class FlowWithMockedFrontend(Flow):
    def configure_layout(self):
        return _MagicMockJsonSerializable()


class FlowWithMockedContent(Flow):
    def configure_layout(self):
        return [{"name": "test", "content": _MagicMockJsonSerializable()}]


class NestedFlow(Flow):
    def __init__(self):
        super().__init__()

        self.flow = Flow()


class NestedFlowWithURLLayout(Flow):
    def __init__(self):
        super().__init__()

        self.flow = FlowWithURLLayout()


class WorkWithStringLayout(Work):
    def configure_layout(self):
        return "http://appurl"


class WorkWithMockedFrontendLayout(Work):
    def configure_layout(self):
        return _MagicMockJsonSerializable()


class WorkWithFrontendLayout(Work):
    def configure_layout(self):
        return StaticWebFrontend(".")


class WorkWithNoneLayout(Work):
    def configure_layout(self):
        return None


class FlowWithWorkLayout(Flow):
    def __init__(self, work):
        super().__init__()

        self.work = work()

    def configure_layout(self):
        return {"name": "test", "content": self.work}


class WorkClassRootFlow(_RootFlow):
    """A ``_RootFlow`` which takes a work class rather than the work itself."""

    def __init__(self, work):
        super().__init__(work())


@pytest.mark.parametrize(
    "flow,expected",
    [
        (Flow, True),
        (FlowWithURLLayout, False),
        (FlowWithFrontend, False),
        (FlowWithMockedFrontend, False),
        (FlowWithMockedContent, False),
        (NestedFlow, True),
        (NestedFlowWithURLLayout, False),
        (partial(WorkClassRootFlow, WorkWithStringLayout), False),
        (partial(WorkClassRootFlow, WorkWithMockedFrontendLayout), False),
        (partial(WorkClassRootFlow, WorkWithFrontendLayout), False),
        (partial(WorkClassRootFlow, WorkWithNoneLayout), True),
        (partial(FlowWithWorkLayout, Work), False),
        (partial(FlowWithWorkLayout, WorkWithStringLayout), False),
        (partial(FlowWithWorkLayout, WorkWithMockedFrontendLayout), False),
        (partial(FlowWithWorkLayout, WorkWithFrontendLayout), False),
        (partial(FlowWithWorkLayout, WorkWithNoneLayout), True),
    ],
)
def test_is_headless(flow, expected):
    flow = flow()
    app = LightningApp(flow)
    assert _is_headless(app) == expected


@mock.patch("lightning_app.utilities.network.LightningClient")
def test_handle_is_headless(mock_client):
    project_id = "test_project_id"
    app_id = "test_app_id"
    app_name = "test_app_name"

    lightningapps = [mock.MagicMock()]
    lightningapps[0].id = app_id
    lightningapps[0].name = app_name
    lightningapps[0].status.phase = V1LightningappInstanceState.RUNNING
    lightningapps[0].spec = V1LightningappInstanceSpec(app_id=app_id)

    mock_client().lightningapp_instance_service_list_lightningapp_instances.return_value = (
        V1ListLightningappInstancesResponse(lightningapps=lightningapps)
    )

    app = mock.MagicMock()
    app.is_headless = True

    with mock.patch.dict(os.environ, {"LIGHTNING_CLOUD_APP_ID": app_id, "LIGHTNING_CLOUD_PROJECT_ID": project_id}):
        _handle_is_headless(app)

    mock_client().lightningapp_instance_service_update_lightningapp_instance.assert_called_once_with(
        project_id=project_id,
        id=app_id,
        body=AppinstancesIdBody(name="test_app_name", spec=V1LightningappInstanceSpec(app_id=app_id, is_headless=True)),
    )
