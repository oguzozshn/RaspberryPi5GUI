from __future__ import annotations

from pi_protocol import (
    ContainerInfo,
    DockerActionResultPayload,
    DockerListResultPayload,
    DockerLogsResultPayload,
    Envelope,
    MessageType,
    NetworkInfoResultPayload,
    NetworkInterface,
)

from desktop_app.app_state import AppState
from desktop_app.ui.pages.docker_page import DockerPage
from desktop_app.ui.pages.network_page import NetworkPage


def _containers() -> DockerListResultPayload:
    return DockerListResultPayload(
        containers=[
            ContainerInfo(id="c0ffe", name="grafana", image="grafana/grafana", state="running",
                          status="Up 5 minutes", ports="0.0.0.0:3000->3000/tcp"),
            ContainerInfo(id="9f1c2", name="pihole", image="pihole/pihole:latest", state="running",
                          status="Up 3 hours", ports="0.0.0.0:53->53/tcp"),
            ContainerInfo(id="3ab77", name="backup", image="alpine:3.19", state="exited",
                          status="Exited (0) 2 days ago"),
        ]
    )


def _network() -> NetworkInfoResultPayload:
    return NetworkInfoResultPayload(
        hostname="raspberrypi",
        default_gateway="192.168.2.1",
        dns_servers=["192.168.2.1", "1.1.1.1"],
        wifi_interface="wlan0",
        wifi_ssid="Ev Agi 5G",
        wifi_signal_dbm=-47,
        interfaces=[
            NetworkInterface(name="eth0", addresses=["192.168.2.20"], mac="d8:3a:dd:11:22:33",
                             is_up=True, speed_mbps=1000, bytes_sent=1024, bytes_recv=4096),
            NetworkInterface(name="lo", addresses=["127.0.0.1"], is_up=True),
        ],
    )


# --- docker -----------------------------------------------------------------


def test_container_table_populates(app_state: AppState) -> None:
    page = DockerPage(app_state)
    page._on_containers(_containers())

    assert page._table.rowCount() == 3
    assert page._table.item(0, 0).text() == "grafana"
    assert "2 calisiyor" in page._status.text()


def test_actions_follow_the_container_state(app_state: AppState) -> None:
    """Offering "Baslat" on a running container only earns an error from the
    daemon, so the buttons mirror what the container can actually do."""
    page = DockerPage(app_state)
    page._on_containers(_containers())

    page._table.selectRow(0)  # grafana, running
    assert not page._start_button.isEnabled()
    assert page._stop_button.isEnabled()
    assert page._restart_button.isEnabled()
    assert page._logs_button.isEnabled()

    page._table.selectRow(2)  # backup, exited
    assert page._start_button.isEnabled()
    assert not page._stop_button.isEnabled()


def test_no_actions_without_a_selection(app_state: AppState) -> None:
    page = DockerPage(app_state)
    page._on_containers(_containers())
    assert not any(button.isEnabled() for button in page._buttons)


def test_filter_narrows_the_table_and_keeps_selection_mapping_correct(app_state: AppState) -> None:
    """Regression risk: rows are filtered client-side, so the selected row index
    must be resolved against the *visible* list, not the full one."""
    page = DockerPage(app_state)
    page._on_containers(_containers())

    page._filter.setText("pihole")
    assert page._table.rowCount() == 1
    page._table.selectRow(0)
    assert page._selected_container().name == "pihole"


def test_filter_matches_the_image_too(app_state: AppState) -> None:
    page = DockerPage(app_state)
    page._on_containers(_containers())
    page._filter.setText("alpine")
    assert page._table.rowCount() == 1
    assert page._table.item(0, 0).text() == "backup"


def test_docker_page_explains_a_pi_without_docker(bare_app_state: AppState) -> None:
    page = DockerPage(bare_app_state)
    page.start()
    assert "Docker kullanilamiyor" in page._banner.text()
    assert "kurulu degil" in page._banner.text()
    assert not page._filter.isEnabled()


def test_container_action_failure_is_surfaced(app_state: AppState) -> None:
    page = DockerPage(app_state)
    page._on_action_done(
        DockerActionResultPayload(container="pihole", action="stop", ok=False,
                                  detail="No such container")
    )
    assert "basarisiz" in page._status.text()
    assert "e67e22" in page._status.styleSheet()


def test_container_logs_render(app_state: AppState) -> None:
    page = DockerPage(app_state)
    page._on_logs(DockerLogsResultPayload(container="pihole", lines=["satir bir", "satir iki"]))
    assert "satir iki" in page._logs.toPlainText()
    assert "2 satir log" in page._status.text()


# --- network ----------------------------------------------------------------


def test_network_summary_and_table(app_state: AppState) -> None:
    page = NetworkPage(app_state)
    page._on_info(_network())

    assert page._hostname.text() == "raspberrypi"
    assert page._gateway.text() == "192.168.2.1"
    assert "1.1.1.1" in page._dns.text()
    assert page._table.rowCount() == 2
    assert page._table.item(0, 2).text() == "192.168.2.20"
    assert page._table.item(0, 4).text() == "1000 Mb/s"


def test_wifi_line_grades_the_signal(app_state: AppState) -> None:
    page = NetworkPage(app_state)
    payload = _network()
    page._on_info(payload)
    assert "Ev Agi 5G" in page._wifi.text()
    assert "iyi" in page._wifi.text()

    weak = payload.model_copy(update={"wifi_signal_dbm": -78})
    page._on_info(weak)
    assert "cok zayif" in page._wifi.text()


def test_wifi_line_handles_a_wired_only_pi(app_state: AppState) -> None:
    page = NetworkPage(app_state)
    page._on_info(_network().model_copy(update={"wifi_interface": "", "wifi_ssid": ""}))
    assert page._wifi.text() == "kablosuz arayuz yok"


def test_missing_values_render_as_a_dash(app_state: AppState) -> None:
    page = NetworkPage(app_state)
    page._on_info(
        NetworkInfoResultPayload(
            hostname="pi", interfaces=[NetworkInterface(name="eth0", is_up=False)]
        )
    )
    assert page._gateway.text() == "—"
    assert page._table.item(0, 2).text() == "—"
    assert page._table.item(0, 4).text() == "—"


# --- app_state routing ------------------------------------------------------


def test_app_state_routes_container_list(app_state: AppState) -> None:
    received: list[DockerListResultPayload] = []
    app_state.containers_listed.connect(received.append)

    app_state._on_message(
        Envelope(type=MessageType.DOCKER_LIST_RESULT, payload=_containers()).model_dump(mode="json")
    )
    assert received[0].containers[0].name == "grafana"


def test_app_state_routes_and_caches_network_info(app_state: AppState) -> None:
    received: list[NetworkInfoResultPayload] = []
    app_state.network_info_received.connect(received.append)

    app_state._on_message(
        Envelope(type=MessageType.NETWORK_INFO_RESULT, payload=_network()).model_dump(mode="json")
    )
    assert received[0].hostname == "raspberrypi"
    assert app_state.latest_network is not None
