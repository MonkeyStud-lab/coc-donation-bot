"""Test the project's real pinned scrcpy transport on an isolated ADB target."""
import argparse
import asyncio
import json
from pathlib import Path
import time


async def probe(args):
    import av
    from coc_bot.web.live import ScrcpySource
    source = ScrcpySource(args.device, args.server)
    result = {"device": args.device, "packets": 0, "decoded_frames": 0}
    started = time.monotonic()
    try:
        await source.start()
        result["metadata"] = [source.width, source.height]
        decoder = av.CodecContext.create("h264", "r")
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            packet = await asyncio.wait_for(source.packet(), min(5, deadline - time.monotonic()))
            result["packets"] += 1
            for frame in decoder.decode(packet):
                result["decoded_frames"] += 1
                result["decoded_size"] = [frame.width, frame.height]
                if "first_frame_s" not in result:
                    result["first_frame_s"] = time.monotonic() - started
    except Exception as exc:
        result["ended_with"] = type(exc).__name__ + ": " + str(exc)
    finally:
        result["duration_s"] = time.monotonic() - started
        await source.close()
        result["logs"] = source.logs
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--device", required=True)
    p.add_argument("--server", type=Path, required=True)
    p.add_argument("--seconds", type=int, default=10)
    p.add_argument("--output", type=Path, required=True)
    asyncio.run(probe(p.parse_args()))
