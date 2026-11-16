#!/usr/bin/env python3
"""Reversible runtime patch for the tested native Linux Dead Cells build."""

import argparse
import hashlib
import math
import os
from pathlib import Path
import struct
import subprocess
import sys
import time

EXPECTED_HASH = "59350cad475a2375b9e39d7cd13fdb6e4ed9a027fd827ae5140f913c1c07ce7e"
STOCK_WIDTH = 683
HEIGHT = 400
MAX_WIDTH = 8192
CHUNK_SIZE = 1024 * 1024


def find_game():
    matches = []
    for path in Path("/proc").iterdir():
        if not path.name.isdigit():
            continue
        try:
            if (path / "comm").read_text().strip() != "deadcells":
                continue
            executable = (path / "exe").resolve(strict=True)
            if executable.name == "deadcells":
                matches.append((int(path.name), executable.parent))
        except FileNotFoundError:
            continue
    if len(matches) != 1:
        raise RuntimeError(f"Expected exactly one installed Dead Cells process, found {len(matches)}")
    return matches[0]


def check_build(game_dir):
    with (game_dir / "hlboot.dat").open("rb") as bytecode:
        digest = hashlib.file_digest(bytecode, "sha256").hexdigest()
    if digest != EXPECTED_HASH:
        raise RuntimeError("Game bytecode differs from the tested build; refusing to patch")


def read_exact(fd, address, size):
    data = os.pread(fd, size, address)
    if len(data) != size:
        raise RuntimeError(f"Short memory read at {address:#x}")
    return data


def read_u64(fd, address):
    return struct.unpack("<Q", read_exact(fd, address, 8))[0]


def is_viewport(fd, address):
    try:
        type_address = read_u64(fd, address - 48)
        if struct.unpack("<I", read_exact(fd, type_address, 4))[0] != 11:
            return False
        obj_address = read_u64(fd, type_address + 8)
        name_address = read_u64(fd, obj_address + 16)
        name = read_exact(fd, name_address, 20)
        return name == "$Viewport\0".encode("utf-16-le")
    except (OSError, OverflowError, RuntimeError, struct.error):
        return False


def find_viewport(fd, maps):
    needle = struct.pack("<i", HEIGHT)
    matches = set()
    for line in maps:
        fields = line.split(maxsplit=5)
        if len(fields) < 5 or fields[1][:2] != "rw" or fields[1][3] != "p":
            continue
        start, end = (int(value, 16) for value in fields[0].split("-"))
        tail = b""
        for pos in range(start, end, CHUNK_SIZE):
            data = read_exact(fd, pos, min(CHUNK_SIZE, end - pos))
            chunk = tail + data
            index = chunk.find(needle)
            while index >= 0:
                address = pos - len(tail) + index - 4
                if address >= start and address % 4 == 0:
                    width = struct.unpack("<i", read_exact(fd, address, 4))[0]
                    if 1 <= width <= MAX_WIDTH and is_viewport(fd, address):
                        matches.add(address)
                index = chunk.find(needle, index + 1)
            tail = chunk[-7:]
    if len(matches) != 1:
        raise RuntimeError(f"Expected one verified $Viewport, found {len(matches)}")
    return matches.pop()


def run_command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def fullscreen_window(pid):
    matches = []
    for line in run_command("wmctrl", "-lpG").splitlines():
        parts = line.split(maxsplit=8)
        if len(parts) >= 7 and parts[2] == str(pid):
            matches.append(parts)
    if len(matches) != 1:
        raise RuntimeError(f"Expected one X11 game window, found {len(matches)}")
    window, _, _, _, _, width, height = matches[0][:7]
    state = run_command("xprop", "-id", window, "_NET_WM_STATE")
    if "_NET_WM_STATE_FULLSCREEN" not in state:
        raise RuntimeError("Game must be in X11 fullscreen before applying the patch")
    return window, (int(width), int(height))


def parse_resolution(value):
    try:
        width, height = value.lower().split("x")
        width, height = int(width), int(height)
        if not (1 <= width <= 32768 and 1 <= height <= 32768):
            raise ValueError
        return width, height
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Resolution must be WIDTHxHEIGHT, each from 1 to 32768") from exc


def parse_width(value):
    try:
        width = int(value)
        if not 1 <= width <= MAX_WIDTH:
            raise ValueError
        return width
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"Viewport width must be an integer from 1 to {MAX_WIDTH}") from exc


def fit_width(resolution):
    width, height = resolution
    scale = math.floor(max(1, 3 * min(width / 1920, height / 1080)) * 4) / 4
    target = max(STOCK_WIDTH, math.ceil(width / scale))
    if target > MAX_WIDTH:
        raise RuntimeError(f"Required viewport width {target} exceeds maximum {MAX_WIDTH}")
    return target


def refresh_window(window):
    try:
        run_command("wmctrl", "-i", "-r", window, "-b", "remove,fullscreen")
        time.sleep(1)
    finally:
        run_command("wmctrl", "-i", "-r", window, "-b", "add,fullscreen")
    time.sleep(1)
    state = run_command("xprop", "-id", window, "_NET_WM_STATE")
    if "_NET_WM_STATE_FULLSCREEN" not in state:
        raise RuntimeError("Could not restore fullscreen; restore it in the game manually")


def main():
    parser = argparse.ArgumentParser(description="Dead Cells native Linux ultrawide runtime patch")
    parser.add_argument("--restore", action="store_true", help="restore stock viewport width")
    parser.add_argument("--status", action="store_true", help="inspect only; do not change the game")
    parser.add_argument("--resolution", type=parse_resolution, metavar="WIDTHxHEIGHT",
                        help="monitor resolution; must match fullscreen game window (default: detect window)")
    parser.add_argument("--width", type=parse_width, metavar="WIDTH",
                        help="logical viewport width instead of automatically fitting the screen")
    args = parser.parse_args()
    if (args.restore and args.status) or ((args.restore or args.status) and
                                           (args.resolution is not None or args.width is not None)):
        parser.error("--restore and --status cannot be combined with other options")
    pid, game_dir = find_game()
    check_build(game_dir)
    with open(f"/proc/{pid}/maps", encoding="utf-8") as maps:
        with open(f"/proc/{pid}/mem", "rb" if args.status else "r+b", buffering=0) as mem:
            address = find_viewport(mem.fileno(), maps)
            current, height = struct.unpack("<ii", read_exact(mem.fileno(), address, 8))
            print(f"PID {pid}: verified $Viewport, width={current}, height={height}", flush=True)
            if args.status:
                return
            window, dimensions = fullscreen_window(pid)
            if args.resolution is not None and args.resolution != dimensions:
                raise RuntimeError(f"Requested resolution {args.resolution[0]}x{args.resolution[1]} "
                                   f"does not match fullscreen game window {dimensions[0]}x{dimensions[1]}")
            target = STOCK_WIDTH if args.restore else (
                args.width if args.width is not None else fit_width(args.resolution or dimensions)
            )
            print(f"Fullscreen {dimensions[0]}x{dimensions[1]}; target width={target}", flush=True)
            if current == target:
                print("Already set; no changes made.")
                return
            if read_exact(mem.fileno(), address, 8) != struct.pack("<ii", current, HEIGHT):
                raise RuntimeError("Viewport changed during validation; refusing to write")
            if not is_viewport(mem.fileno(), address):
                raise RuntimeError("Viewport type changed during validation; refusing to write")
            if os.pwrite(mem.fileno(), struct.pack("<i", target), address) != 4:
                raise RuntimeError("Short memory write; restart the game to restore")
            if read_exact(mem.fileno(), address, 8) != struct.pack("<ii", target, HEIGHT):
                raise RuntimeError("Memory verification failed; restart the game to restore")
            print(f"Changed width {current} -> {target}; refreshing fullscreen.", flush=True)
            refresh_window(window)
            print("Done. The change lasts until the game exits.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
