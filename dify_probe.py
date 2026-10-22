import argparse
import configparser
import http.client
import json
import socket
import ssl
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit


MAX_BYTES = 8 * 1024 * 1024
EVENTS = {
    "ping", "workflow_started", "workflow_finished", "node_started",
    "node_finished", "text_chunk", "text_replace", "error",
    "iteration_started", "iteration_next", "iteration_completed",
    "loop_started", "loop_next", "loop_completed",
}
STATUSES = {"succeeded", "failed", "stopped", "running", "partial-succeeded"}


class ProbeError(Exception):
    pass


def load_config(path, include_gateway):
    config = configparser.ConfigParser(interpolation=None)
    try:
        with Path(path).open(encoding="utf-8-sig") as source:
            config.read_file(source)
    except FileNotFoundError:
        raise ProbeError("config_file_missing") from None
    except (OSError, UnicodeError, configparser.Error):
        raise ProbeError("config_file_unreadable_or_invalid_ini") from None
    targets = []
    for section, label in (("dify", "direct"), ("gateway", "gateway")):
        if section == "gateway" and not include_gateway:
            continue
        if not config.has_section(section):
            raise ProbeError(section + "_section_missing")
        try:
            base = normalize_url(config.get(section, "url", fallback="").strip())
        except (ValueError, ProbeError):
            raise ProbeError(section + "_url_invalid") from None
        key = config.get(section, "key", fallback="").strip()
        if not key or any(character.isspace() for character in key):
            raise ProbeError(section + "_key_invalid")
        targets.append((label, base, key))
    try:
        inputs = json.loads(config.get("dify", "inputs", fallback=""))
    except (ValueError, RecursionError):
        raise ProbeError("dify_inputs_invalid_json") from None
    if not isinstance(inputs, dict):
        raise ProbeError("dify_inputs_must_be_object")
    return targets, inputs


def normalize_url(value):
    parsed = urlsplit(value.strip())
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ProbeError("invalid_url")
    parsed.port
    path = parsed.path.rstrip("/")
    for suffix in ("/workflows/run", "/parameters"):
        if path.endswith(suffix):
            path = path[:-len(suffix)]
            break
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def error_category(error):
    if isinstance(error, ProbeError):
        return str(error)
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, ssl.SSLError):
        return "tls_error"
    if isinstance(error, socket.gaierror):
        return "dns_error"
    if isinstance(error, ConnectionRefusedError):
        return "connection_refused"
    if isinstance(error, http.client.IncompleteRead):
        return "incomplete_response"
    if isinstance(error, (json.JSONDecodeError, UnicodeError)):
        return "invalid_json_or_encoding"
    if isinstance(error, (OSError, http.client.HTTPException)):
        return "connection_error"
    return "unexpected_error"


def request(base, key, path, payload, streaming, timeout):
    parsed = urlsplit(base)
    connection_type = (http.client.HTTPSConnection if parsed.scheme == "https"
                       else http.client.HTTPConnection)
    connection = connection_type(parsed.hostname, parsed.port, timeout=min(30, timeout))
    started = time.monotonic()
    result = {"http_status": None, "content_type": "other", "bytes": 0}
    body = bytearray()
    try:
        encoded = None if payload is None else json.dumps(payload).encode("utf-8")
        connection.request(
            "GET" if payload is None else "POST", parsed.path.rstrip("/") + path,
            body=encoded,
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json",
                     "Accept": "text/event-stream" if streaming else "application/json",
                     "Accept-Encoding": "identity"},
        )
        response = connection.getresponse()
        result["http_status"] = response.status
        media_type = response.getheader("Content-Type", "").split(";", 1)[0].lower().strip()
        if media_type in {"application/json", "text/event-stream"}:
            result["content_type"] = media_type
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ProbeError("total_timeout")
            if connection.sock is not None:
                connection.sock.settimeout(min(30, remaining))
            chunk = response.read1(65536)
            if not chunk:
                break
            if "first_bytes_ms" not in result:
                result["first_bytes_ms"] = round((time.monotonic() - started) * 1000)
            body.extend(chunk)
            result["bytes"] = len(body)
            if len(body) > MAX_BYTES:
                raise ProbeError("response_size_limit")
            if streaming and media_type == "text/event-stream":
                if "first_data_ms" not in result and b"data:" in body:
                    result["first_data_ms"] = round((time.monotonic() - started) * 1000)
        if response.length not in (None, 0):
            raise ProbeError("incomplete_response")
        result["transport_complete"] = True
    except Exception as error:
        result["error"] = error_category(error)
        result["transport_complete"] = False
    finally:
        connection.close()
        result["elapsed_ms"] = round((time.monotonic() - started) * 1000)
    return result, bytes(body)


def parse_sse(body):
    counts = {}
    names = []
    started = False
    finished = False
    failed = False
    malformed = 0
    final_data = {}
    data_lines = []
    event_name = ""
    pending = False
    text = body.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    for line in lines:
        if line:
            if line.startswith(":"):
                continue
            pending = True
            field, _, value = line.partition(":")
            value = value[1:] if value.startswith(" ") else value
            if field == "data":
                data_lines.append(value)
            elif field == "event":
                event_name = value
            continue
        if not pending:
            continue
        pending = False
        if data_lines:
            try:
                event = json.loads("\n".join(data_lines))
                if not isinstance(event, dict):
                    raise ValueError()
                name = event.get("event", event_name)
                data = event.get("data", {})
                if not isinstance(data, dict):
                    data = {}
                if name == "workflow_started":
                    started = True
                if name == "workflow_finished":
                    finished = True
                    final_data = dict(data)
                    final_data["workflow_run_id"] = event.get("workflow_run_id", data.get("id"))
                if name == "error" or data.get("status") in {"failed", "stopped", "partial-succeeded"}:
                    failed = True
            except (ValueError, TypeError):
                malformed += 1
                name = "malformed"
        else:
            name = event_name
        safe_name = name if isinstance(name, str) and name in EVENTS else "other"
        counts[safe_name] = counts.get(safe_name, 0) + 1
        if len(names) < 100:
            names.append(safe_name)
        data_lines = []
        event_name = ""
    return {
        "event_counts": counts, "event_order_first_100": names,
        "workflow_started": started, "workflow_finished": finished,
        "failure_event": failed, "malformed_events": malformed,
        "incomplete_frame": pending,
    }, final_data


def shape(value, depth=0):
    if depth > 10:
        return "depth_limit"
    if isinstance(value, dict):
        return {"type": "object", "values": sorted(
            [shape(item, depth + 1) for item in value.values()], key=lambda item: json.dumps(item))}
    if isinstance(value, list):
        return {"type": "array", "items": [shape(item, depth + 1) for item in value[:20]]}
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "string"


def run_target(base, key, inputs, timeout):
    cases = []
    private_outputs = {}
    for mode in ("blocking", "streaming"):
        metadata, body = request(base, key, "/workflows/run", {
            "inputs": inputs, "response_mode": mode, "user": "gateway-compatibility-probe",
        }, mode == "streaming", timeout)
        case = {"case": mode, **metadata}
        data = {}
        try:
            if mode == "streaming" and metadata["content_type"] == "text/event-stream":
                summary, data = parse_sse(body)
                case.update(summary)
            else:
                document = json.loads(body)
                if not isinstance(document, dict):
                    raise ValueError()
                data = document.get("data", {})
                if not isinstance(data, dict):
                    raise ValueError()
                data = dict(data)
                data["workflow_run_id"] = document.get("workflow_run_id", data.get("id"))
            status = data.get("status")
            case["workflow_status"] = status if isinstance(status, str) and status in STATUSES else "unknown"
            outputs = data.get("outputs")
            case["outputs_present"] = isinstance(outputs, dict)
            case["output_shape"] = shape(outputs)
            private_outputs[mode] = outputs
            case["passed"] = (
                metadata["transport_complete"] and metadata["http_status"] == 200
                and status == "succeeded" and isinstance(outputs, dict)
                and (mode == "blocking" or (
                    case.get("workflow_started", False) and case.get("workflow_finished", False)
                    and not case.get("failure_event", True)
                    and case.get("malformed_events") == 0 and not case.get("incomplete_frame", True)))
            )
        except Exception as error:
            case["parse_error"] = error_category(error)
            case["passed"] = False
        cases.append(case)
        run_id = data.get("workflow_run_id")
        if isinstance(run_id, str) and run_id and metadata["transport_complete"]:
            detail_meta, detail_body = request(
                base, key, "/workflows/run/" + quote(run_id, safe=""), None, False, timeout)
            detail_case = {"case": mode + "_run_detail", **detail_meta, "passed": False}
            try:
                detail = json.loads(detail_body)
                if isinstance(detail, dict):
                    detail_case["passed"] = (
                        detail_meta["transport_complete"] and detail_meta["http_status"] == 200
                        and detail.get("id") == run_id and detail.get("status") == "succeeded"
                    )
            except Exception as error:
                detail_case["parse_error"] = error_category(error)
            cases.append(detail_case)
        else:
            cases.append({"case": mode + "_run_detail", "skipped": True,
                          "reason": "run_id_unavailable_or_transport_incomplete", "passed": False})
    return cases, private_outputs


def main():
    parser = argparse.ArgumentParser(description="Dify 内网工作流测试，从 INI 读取配置，报告采用固定字段。")
    parser.add_argument("--config", default=Path(__file__).resolve().with_suffix(".ini"),
                        help="INI 文件路径，默认读取脚本同目录 dify_probe.ini")
    parser.add_argument("--gateway", action="store_true", help="同时测试网关")
    parser.add_argument("--timeout", type=int, default=180, help="每次请求总时限，默认 180 秒")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 3600:
        raise ProbeError("invalid_timeout")
    targets, inputs = load_config(args.config, args.gateway)
    print("已读取 INI 配置。")
    print("每个目标执行工作流 2 次（可能产生模型费用），另查询运行结果最多 2 次。")
    report = {"report_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
              "scope": "minimal_workflow_only", "timeout_seconds": args.timeout,
              "privacy": "fixed_fields_only_no_addresses_keys_bodies_ids_or_exception_text",
              "targets": {}}
    private = {}
    for label, target_base, target_key in targets:
        print("正在测试：" + label)
        cases, outputs = run_target(target_base, target_key, inputs, args.timeout)
        report["targets"][label] = cases
        private[label] = outputs
    if args.gateway:
        report["comparison"] = {}
        for mode in ("blocking", "streaming"):
            direct_case = report["targets"]["direct"][0 if mode == "blocking" else 2]
            gateway_case = report["targets"]["gateway"][0 if mode == "blocking" else 2]
            comparable = direct_case["passed"] and gateway_case["passed"]
            report["comparison"][mode] = {
                "both_passed": comparable,
                "output_shape_equal": (direct_case["output_shape"] == gateway_case["output_shape"]
                                       if comparable else None),
                "output_value_equal": (private["direct"].get(mode) == private["gateway"].get(mode)
                                       if comparable else None),
            }
    report["all_cases_passed"] = all(
        case["passed"] for cases in report["targets"].values() for case in cases)
    report_path = Path(__file__).resolve().parent / (
        "dify-report-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f") + ".json")
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("测试完成，报告已写入脚本同目录的 dify-report-*.json。")
    print("结果：" + ("全部通过" if report["all_cases_passed"] else "有失败项，请返回报告"))
    return 0 if report["all_cases_passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("已取消。")
        raise SystemExit(130)
    except Exception as error:
        print("测试中止，诊断类别：" + error_category(error))
        raise SystemExit(2)
