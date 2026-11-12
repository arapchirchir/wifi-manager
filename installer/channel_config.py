"""Pure hostapd config rendering. Never writes or restarts services."""
import re


class HostapdConfigError(ValueError):
    pass


def render_channel(original, detected_channel):
    """Return a configuration using the detected upstream channel.

    Requires exactly one active channel and one AP interface, and refuses
    unknown values. The installer must obtain explicit approval and verify
    the upstream connection again before writing this rendered text.
    """
    if not isinstance(detected_channel, int) or not 1 <= detected_channel <= 196:
        raise HostapdConfigError("Detected upstream channel is invalid")

    lines = original.splitlines(keepends=True)
    channels = [
        i for i, line in enumerate(lines)
        if re.match(r"^\s*channel\s*=", line)
        and not line.lstrip().startswith("#")
    ]
    interfaces = [
        line.partition("=")[2].strip()
        for line in lines
        if re.match(r"^\s*interface\s*=", line)
        and not line.lstrip().startswith("#")
    ]
    if interfaces != ["ap0"] or len(channels) != 1:
        raise HostapdConfigError(
            "Expected one dedicated ap0 interface and one active channel"
        )
    idx = channels[0]
    newline = "\r\n" if lines[idx].endswith("\r\n") else "\n"
    lines[idx] = f"channel={detected_channel}{newline}"
    return "".join(lines)
