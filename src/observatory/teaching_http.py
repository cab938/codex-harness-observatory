"""HTTP adapter for the recording-derived teaching views."""

from http import HTTPStatus


def serve_teaching(handler, query):
    """Read a selected recording prefix; never mutate the source bundle."""
    from observatory.teaching import project_trace
    from observatory.trace_viewer import TraceInputError, safe_stream_error

    trace = handler.viewer_server.resolve_trace_path()
    if trace is None:
        handler.send_json({"error": "trace bundle is not available yet"}, HTTPStatus.NOT_FOUND)
        return
    try:
        until_text = query.get("until", [""])[0]
        until = int(until_text) if until_text else None
        if until is not None and until < 0:
            raise ValueError("until must be a nonnegative sequence")
        result = project_trace(
            trace,
            thread=query.get("thread", [None])[0] or None,
            root=query.get("root", [None])[0] or None,
            descendants=query.get("descendants", ["0"])[0] == "1",
            until=until,
            request=query.get("request", ["live"])[0] or "live",
            item=query.get("item", [None])[0] or None,
            show_content=handler.viewer_server.show_content,
        )
    except ValueError as error:
        handler.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        return
    except TraceInputError as error:
        handler.send_json({"error": safe_stream_error(error, trace)}, HTTPStatus.UNPROCESSABLE_ENTITY)
        return
    handler.send_json(result)
