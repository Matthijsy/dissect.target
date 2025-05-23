from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import mock_open, patch

import pytest

from dissect.target.plugins.apps.webserver import iis
from dissect.target.target import Target
from tests._utils import absolute_path

if TYPE_CHECKING:
    from dissect.target.filesystem import VirtualFilesystem


def test_iis_iis_format(target_win_tzinfo: Target, fs_win: VirtualFilesystem) -> None:
    config_path = absolute_path("_data/plugins/apps/webserver/iis/iis-applicationHost-iis.config")
    data_dir = absolute_path("_data/plugins/apps/webserver/iis/iis-logs-iis")

    fs_win.map_file("windows/system32/inetsrv/config/applicationHost.config", config_path)
    fs_win.map_dir("Users/John/iis-logs", data_dir)

    target_win_tzinfo.add_plugin(iis.IISLogsPlugin)

    records = list(target_win_tzinfo.iis.logs())

    assert len(records) == 10
    assert {str(r.client_ip) for r in records} == {"127.0.0.1", "::1"}
    assert {str(r.site_name) for r in records} == {"W3SVC1"}
    assert {r.service_status_code for r in records} == {"304", "404", "200"}

    # check if metadata fields are present
    assert {r.format for r in records} == {"IIS"}
    assert {str(r.source) for r in records} == {"sysvol\\Users\\John\\iis-logs\\W3SVC1\\u_in211001.log"}
    assert {r.hostname for r in records} == {target_win_tzinfo.hostname}


@pytest.mark.parametrize(
    "iis_config_path",
    [
        "_data/plugins/apps/webserver/iis/iis-applicationHost-w3c.config",
        "_data/plugins/apps/webserver/iis/iis-applicationHost-w3c-logFile-without-directory-attr.config",
    ],
)
def test_iis_w3c_format(target_win: Target, fs_win: VirtualFilesystem, iis_config_path: str) -> None:
    config_path = absolute_path(iis_config_path)
    data_dir = absolute_path("_data/plugins/apps/webserver/iis/iis-logs-w3c")

    fs_win.map_file("windows/system32/inetsrv/config/applicationHost.config", config_path)
    fs_win.map_dir("Users/John/w3c-logs", data_dir)

    target_win.add_plugin(iis.IISLogsPlugin)

    records = list(target_win.iis.logs())

    assert len(records) == 20

    # first 6 records do not have custom fields and server_name is not set
    assert {r.server_name for r in records[:6]} == {None}
    assert not any(hasattr(r, "custom_field_1") for r in records[:6])
    assert not any(hasattr(r, "custom_field_2") for r in records[:6])

    # other records have the custom fields and server_name set
    assert {r.server_name for r in records[6:]} == {"DESKTOP-PJOQLJS"}
    assert all(hasattr(r, "custom_field_1") for r in records[6:])
    assert all(hasattr(r, "custom_field_2") for r in records[6:])

    assert {str(r.client_ip) for r in records} == {"127.0.0.1", "::1"}
    assert {r.site_name for r in records} == {None, "W3SVC1"}
    assert {r.service_status_code for r in records} == {"304", "404"}

    # check if fields with normalised names are present
    assert {str(r.cs_user_agent) for r in records} == {
        (
            "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)+AppleWebKit/537.36+(KHTML,+like+Gecko)"
            "+Chrome/93.0.4577.82+Safari/537.36+Edg/93.0.961.52"
        )
    }

    # check if metadata fields are present
    assert {r.format for r in records} == {"W3C"}
    assert {str(r.source) for r in records} == {"C:\\Users\\John\\w3c-logs\\W3SVC1\\u_ex211001_x.log"}
    assert {r.hostname for r in records} == {target_win.hostname}


@pytest.mark.parametrize(
    ("stream", "method"),
    [
        (b"-, -, 10/1/2021, 00:00:00, -, \xa7, ::1, 1, 2, 3, 200, 0, GET, /, -,", "parse_iis_format_log"),
        (b"#Date: -\n#Fields: s-computername\n\xa7", "parse_w3c_format_log"),
    ],
)
def test_iis_nonutf8(target_win_tzinfo: Target, stream: bytes, method: str) -> None:
    # should not crash on invalid bytes like \xa7
    with patch("pathlib.Path.open", new_callable=mock_open, read_data=stream):
        assert next(iter(getattr(iis, method)(target_win_tzinfo, Path("/iis")))).server_name == "\\xa7"


def test_iis_access_iis_format(target_win_tzinfo: Target, fs_win: VirtualFilesystem) -> None:
    tz = timezone(timedelta(hours=-5))
    config_path = absolute_path("_data/plugins/apps/webserver/iis/iis-applicationHost-iis.config")
    data_dir = absolute_path("_data/plugins/apps/webserver/iis/iis-logs-iis")

    fs_win.map_file("windows/system32/inetsrv/config/applicationHost.config", config_path)
    fs_win.map_dir("Users/John/iis-logs", data_dir)

    target_win_tzinfo.add_plugin(iis.IISLogsPlugin)
    results = list(target_win_tzinfo.iis.access())

    assert len(results) == 10

    record = results[0]
    assert record.ts == datetime(2021, 10, 1, 7, 19, 8, tzinfo=tz)
    assert record.remote_ip == "127.0.0.1"
    assert record.remote_user is None
    assert record.method == "GET"
    assert record.uri == "/"
    assert record.protocol is None
    assert record.status_code == 304
    assert record.bytes_sent == 143
    assert record.referer is None
    assert record.useragent is None
    assert record.source == "sysvol/Users/John/iis-logs/W3SVC1/u_in211001.log"


def test_iis_access_w3c_format(target_win: Target, fs_win: VirtualFilesystem) -> None:
    config_path = absolute_path("_data/plugins/apps/webserver/iis/iis-applicationHost-w3c.config")
    data_dir = absolute_path("_data/plugins/apps/webserver/iis/iis-logs-w3c")

    fs_win.map_file("windows/system32/inetsrv/config/applicationHost.config", config_path)
    fs_win.map_dir("Users/John/w3c-logs", data_dir)

    target_win.add_plugin(iis.IISLogsPlugin)

    results = list(target_win.iis.access())
    assert len(results) == 20

    # W3C format type 1: does not have HTTP version or bytes_sent.
    w3c_record_1 = results[0]
    assert w3c_record_1.ts == datetime(2021, 10, 1, 17, 12, 0, tzinfo=timezone.utc)
    assert w3c_record_1.remote_ip == "127.0.0.1"
    assert w3c_record_1.remote_user is None
    assert w3c_record_1.method == "GET"
    assert w3c_record_1.uri == "/"
    assert w3c_record_1.protocol is None
    assert w3c_record_1.status_code == 304
    assert w3c_record_1.bytes_sent is None
    assert w3c_record_1.referer is None
    assert (
        w3c_record_1.useragent
        == "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)+AppleWebKit/537.36+(KHTML,+like+Gecko)+Chrome/93.0.4577.82+Safari/537.36+Edg/93.0.961.52"  # noqa: E501
    )
    assert w3c_record_1.source == "C:/Users/John/w3c-logs/W3SVC1/u_ex211001_x.log"

    # W3C format type 2: contains HTTP version
    w3c_record_2 = results[6]
    assert w3c_record_2.ts == datetime(2021, 10, 1, 17, 34, 48, tzinfo=timezone.utc)
    assert w3c_record_2.remote_ip == "::1"
    assert w3c_record_2.remote_user is None
    assert w3c_record_2.method == "GET"
    assert w3c_record_2.uri == "/"
    assert w3c_record_2.protocol == "HTTP/1.1"
    assert w3c_record_2.status_code == 304
    assert w3c_record_2.bytes_sent == 143
    assert w3c_record_2.referer is None
    assert (
        w3c_record_2.useragent
        == "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)+AppleWebKit/537.36+(KHTML,+like+Gecko)+Chrome/93.0.4577.82+Safari/537.36+Edg/93.0.961.52"  # noqa: E501
    )
    assert w3c_record_2.source == "C:/Users/John/w3c-logs/W3SVC1/u_ex211001_x.log"

    # W3C format type 3
    w3c_record_3 = results[11]
    assert w3c_record_3.ts == datetime(2021, 10, 1, 18, 2, 47, tzinfo=timezone.utc)
    assert w3c_record_3.remote_ip == "::1"
    assert w3c_record_3.remote_user is None
    assert w3c_record_3.method == "GET"
    assert w3c_record_3.uri == "/another/path+path2"
    assert w3c_record_3.protocol == "HTTP/1.1"
    assert w3c_record_3.status_code == 404
    assert w3c_record_3.bytes_sent == 5125
    assert w3c_record_3.referer is None
    assert (
        w3c_record_3.useragent
        == "Mozilla/5.0+(Windows+NT+10.0;+Win64;+x64)+AppleWebKit/537.36+(KHTML,+like+Gecko)+Chrome/93.0.4577.82+Safari/537.36+Edg/93.0.961.52"  # noqa: E501
    )
    assert w3c_record_3.source == "C:/Users/John/w3c-logs/W3SVC1/u_ex211001_x.log"


@pytest.mark.parametrize(
    "map_dir",
    [
        ("inetpub/logs/LogFiles/W3SVC1"),
        ("inetpub/logs/LogFiles"),
        ("Windows/System32/LogFiles/W3SVC1"),
        ("Windows.old/Windows/System32/LogFiles/W3SVC2"),
        ("Resources/Directory/aaa/LogFiles/Web/W3SVC1"),
    ],
)
@pytest.mark.parametrize(
    "log_format",
    [
        ("iis"),
        ("w3c"),
    ],
)
def test_iis_access_noconfig(
    target_win_tzinfo: Target, fs_win: VirtualFilesystem, map_dir: str, log_format: str
) -> None:
    data_dir = absolute_path(f"_data/plugins/apps/webserver/iis/iis-logs-{log_format}/W3SVC1")
    fs_win.map_dir(map_dir, data_dir)
    target_win_tzinfo.add_plugin(iis.IISLogsPlugin)
    results = list(target_win_tzinfo.iis.access())
    assert len(results) > 0


def test_iis_direct_mode() -> None:
    data_path = absolute_path("_data/plugins/apps/webserver/iis/iis-logs-iis/W3SVC1/u_in211001.log")

    target = Target.open_direct([data_path])
    records = list(target.iis.logs())

    assert len(records) == 10
