from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path

from modelscope import snapshot_download
from modelscope.hub.api import HubApi


PROXY_ENV_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def remove_proxy_env() -> None:
    for key in PROXY_ENV_KEYS:
        os.environ.pop(key, None)


def expected_files(model_id: str) -> list[dict]:
    api = HubApi()
    return [
        item
        for item in api.get_model_files(model_id=model_id, recursive=True)
        if item.get("Type") == "blob"
    ]


def validate_snapshot(model_dir: Path, files: list[dict], *, sha256: bool) -> None:
    errors: list[str] = []
    for item in files:
        rel_path = Path(str(item["Path"]))
        path = model_dir / rel_path
        expected_size = int(item.get("Size") or 0)
        if not path.exists():
            errors.append(f"missing {rel_path}")
            continue
        actual_size = path.stat().st_size
        if actual_size != expected_size:
            errors.append(f"size mismatch {rel_path}: expected {expected_size}, got {actual_size}")
            continue
        expected_sha = str(item.get("Sha256") or "")
        if sha256 and expected_sha:
            actual_sha = sha256_file(path)
            if actual_sha.lower() != expected_sha.lower():
                errors.append(f"sha256 mismatch {rel_path}: expected {expected_sha}, got {actual_sha}")

    if errors:
        raise RuntimeError("snapshot validation failed:\n" + "\n".join(errors))


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def clean_model_cache(model_id: str, cache_root: Path) -> None:
    namespace, name = model_id.split("/", 1)
    targets = [
        cache_root / "models" / namespace / name,
        cache_root / "models" / "._____temp" / namespace / name,
        cache_root / ".lock" / f"{namespace}___{name}",
    ]
    resolved_root = cache_root.resolve()
    for target in targets:
        if not target.exists():
            continue
        resolved = target.resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise RuntimeError(f"refusing to remove outside cache root: {resolved}") from exc
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        print(f"removed {resolved}", flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and validate a ModelScope model snapshot.")
    parser.add_argument("model_id", help="ModelScope model id, for example iic/SenseVoiceSmall")
    parser.add_argument("--clean", action="store_true", help="Remove existing cache for this model before downloading.")
    parser.add_argument("--no-proxy", action="store_true", help="Remove proxy env vars for this process.")
    parser.add_argument("--sha256", action="store_true", help="Verify sha256 for every listed file after download.")
    parser.add_argument(
        "--cache-root",
        type=Path,
        default=Path.home() / ".cache" / "modelscope" / "hub",
        help="ModelScope hub cache root.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.no_proxy:
        remove_proxy_env()
    if args.clean:
        clean_model_cache(args.model_id, args.cache_root)

    files = expected_files(args.model_id)
    total_size = sum(int(item.get("Size") or 0) for item in files)
    print(f"expected_files={len(files)} expected_bytes={total_size}", flush=True)

    model_dir = Path(snapshot_download(args.model_id))
    print(f"snapshot_dir={model_dir}", flush=True)
    validate_snapshot(model_dir, files, sha256=args.sha256)
    print(f"validation_ok model_id={args.model_id}", flush=True)


if __name__ == "__main__":
    main()
