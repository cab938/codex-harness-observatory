"""Build a versioned inventory of declared and observed collection opportunities."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


SCHEMA_GROUPS = (
    "ClientRequest",
    "ClientNotification",
    "ServerRequest",
    "ServerNotification",
)


def _methods(schema):
    return sorted(
        {
            method
            for variant in schema.get("oneOf", [schema])
            for method in variant.get("properties", {})
            .get("method", {})
            .get("enum", [])
        }
    )


def _variants(source):
    body = source.split("pub enum RawTraceEventPayload", 1)[1].split("\n}\n", 1)[0]
    return sorted(set(re.findall(r"^    ([A-Z][A-Za-z0-9_]+)\s*\{", body, re.M)))


def build_inventory(
    schema_dir, stable_schema_dir, upstream_source, instrumented_source, release
):
    """Keep declarations separate from runtime observations and exercise evidence."""
    groups = {}
    digest = hashlib.sha256()
    stable_digest = hashlib.sha256()
    for name in SCHEMA_GROUPS:
        data = (schema_dir / f"{name}.json").read_bytes()
        digest.update(name.encode() + b"\0" + data + b"\0")
        methods = _methods(json.loads(data))
        stable_bytes = (stable_schema_dir / f"{name}.json").read_bytes()
        stable_digest.update(name.encode() + b"\0" + stable_bytes + b"\0")
        stable = json.loads(stable_bytes)
        stable_methods = set(_methods(stable))
        if not stable_methods <= set(methods):
            raise ValueError(
                f"Stable {name} methods are absent from the experimental schema"
            )
        experimental_fields = []
        for definition, shape in json.loads(data).get("definitions", {}).items():
            stable_shape = stable.get("definitions", {}).get(definition)
            if stable_shape is not None:
                experimental_fields.extend(
                    f"{definition}.{field}"
                    for field in shape.get("properties", {})
                    if field not in stable_shape.get("properties", {})
                )
        groups[name] = {
            "count": len(methods),
            "methods": methods,
            "experimental_only_methods": sorted(set(methods) - stable_methods),
            "experimental_only_fields_on_shared_definitions": sorted(
                experimental_fields
            ),
            "gate_evidence": "difference between generated experimental and stable schemas",
        }
    protocol = upstream_source / "codex-rs/app-server-protocol/src"
    declared = set(
        re.findall(
            r'^\s*\w+\s*=>\s*"([^"\n]+)"',
            (protocol / "protocol/common.rs").read_text(),
            re.M,
        )
    )
    exported = {m for group in groups.values() for m in group["methods"]}
    excluded = sorted(declared - exported)
    upstream_raw = (
        upstream_source / "codex-rs/rollout-trace/src/raw_event.rs"
    ).read_text()
    raw = (instrumented_source / "codex-rs/rollout-trace/src/raw_event.rs").read_text()
    native_variants = set(_variants(upstream_raw))
    added_variants = set(_variants(raw)) - native_variants

    def variant_entries(variants):
        return [
            {
                "rust_variant": variant,
                "wire_type": re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", variant).lower(),
            }
            for variant in sorted(variants)
        ]

    literal_sites = {}
    for directory in ("core/src", "rollout-trace/src"):
        for source_path in (instrumented_source / "codex-rs" / directory).rglob("*.rs"):
            if "test" in source_path.name:
                continue
            source = source_path.read_text()
            for match in re.finditer(
                r'HarnessTraceEvent::new\(\s*[^,]+,\s*"([^"\n]+)"', source
            ):
                name = match.group(1)
                literal_sites.setdefault(name, []).append(
                    source_path.relative_to(instrumented_source).as_posix()
                )
    return {
        "inventory_version": 1,
        "collection_capabilities": release["capabilities"],
        "identity": {
            "observatory": release["observatory"]["version"],
            "core": release["core"],
            "desktop_version": release["desktop"]["version"],
        },
        "api": {
            "experimental_schema": True,
            "experimental_gate": "initialize.capabilities.experimentalApi; some methods also require source-specific feature/configuration gates",
            "raw_event_gate": "thread.experimentalRawEvents plus subscription/inheritance and per-connection notification filters",
            "schema_sha256": digest.hexdigest(),
            "stable_schema_sha256": stable_digest.hexdigest(),
            "groups": groups,
            "source_declared_not_exported": [
                {
                    "method": name,
                    "availability": "internal_or_schema_excluded",
                    "observation": "requires_runtime_evidence",
                    "gate": "thread raw-event setting, subscription, and connection filtering"
                    if name in {"rawResponseItem/completed", "rawResponse/completed"}
                    else "consult exact-version source declaration",
                }
                for name in excluded
            ],
        },
        "native_trace_events": variant_entries(native_variants),
        "observatory_raw_extensions": variant_entries(added_variants),
        "harness_literal_event_sites": {
            "scope": "literal constructor names in instrumented production source; dynamic names and test exercise are not inferred",
            "events": {
                name: sorted(set(paths))
                for name, paths in sorted(literal_sites.items())
            },
        },
        "collection_layers": [
            {
                "id": "native",
                "available": True,
                "boundary": "Core-owned request, output, history, tool, terminal, code-cell, compaction, and child observations",
                "limit": "not every provider stream event or every Core transition",
            },
            {
                "id": "app_server",
                "available": True,
                "boundary": "stdio/WebSocket parsed incoming JSON and connection-filtered prepared outgoing JSON; in-process/remote-control typed messages; transport status",
                "limit": "prepared output does not prove client delivery; typed boundaries cannot recover already-discarded unknown JSON members",
            },
            {
                "id": "mcp",
                "available": True,
                "boundary": "typed transport send/receive and Core backend result before truncation",
                "limit": "wrapper send does not prove remote receipt; typed MCP boundaries cannot recover already-discarded unknown JSON members",
            },
            {
                "id": "harness",
                "available": True,
                "boundary": "source-local categorical observations at native owners",
                "limit": "acceptance, input drain, model admission, and consumption are distinct",
            },
        ],
        "evidence": {
            "capture": None,
            "exercises": [],
            "status": "declared_not_exercised",
        },
        "limits": [
            "Writer sequence is append order, not a universal causal clock.",
            "Observed API messages depend on negotiated capabilities and subscriptions.",
            "A clean sequence is not proof of complete collection.",
            "Capture hashes are integrity fingerprints, not proof of authenticity.",
            "Provider-exposed reasoning is not access to hosted private reasoning.",
        ],
    }


def observed_capture(bundle):
    """Count only evidence actually present; do not infer unsupported APIs."""
    source = bundle / "trace.jsonl" if bundle.is_dir() else bundle
    try:
        from observatory.trace_viewer import expand_oversized_event
    except ImportError:
        from trace_viewer import expand_oversized_event
    events = Counter()
    methods = Counter()
    api_messages = Counter()
    malformed = []
    for number, line in enumerate(source.read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except ValueError:
            malformed.append(number)
            continue
        event = expand_oversized_event(event, source)
        payload = event.get("payload", {})
        event_type = payload.get("type", event.get("type", "unknown"))
        events[event_type] += 1
        if event_type in {"app_server_frame_observed", "mcp_frame_observed"}:
            method = payload.get("method")
            if method:
                methods[f"{event_type}:{method}"] += 1
                if event_type == "app_server_frame_observed":
                    kind = payload.get("frame_kind")
                    client = payload.get("direction") == "client_to_server"
                    if kind in {"response", "error"}:
                        client = not client
                        kind = "request"
                    family = ("Client" if client else "Server") + (
                        "Request" if kind == "request" else "Notification"
                    )
                    if kind in {"request", "notification"}:
                        api_messages[f"{family}:{method}"] += 1
    return {
        "event_counts": dict(sorted(events.items())),
        "method_counts": dict(sorted(methods.items())),
        "api_message_counts": dict(sorted(api_messages.items())),
        "malformed_lines": malformed,
        "status": "observed_not_completeness_certified",
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--schema-dir", type=Path, required=True)
    parser.add_argument("--stable-schema-dir", type=Path, required=True)
    parser.add_argument("--upstream-source", type=Path, required=True)
    parser.add_argument("--instrumented-source", type=Path, required=True)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = build_inventory(
        args.schema_dir,
        args.stable_schema_dir,
        args.upstream_source,
        args.instrumented_source,
        json.loads(args.release.read_text()),
    )
    if args.capture:
        result["evidence"]["capture"] = observed_capture(args.capture)
        result["evidence"]["status"] = "capture_observed"
        counts = result["evidence"]["capture"]["api_message_counts"]
        result["evidence"]["api_methods"] = {
            family: [
                {
                    "method": method,
                    "observation": "observed_in_run"
                    if counts.get(f"{family}:{method}")
                    else "unexercised_in_run",
                    "message_count": counts.get(f"{family}:{method}", 0),
                }
                for method in group["methods"]
            ]
            for family, group in result["api"]["groups"].items()
        }
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
