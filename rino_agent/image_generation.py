"""Single-GPU image generation job runner.

All machine-specific values are intentionally supplied through environment
variables.  This module never accepts a command line, workflow path, or file
path from an HTTP caller.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import subprocess
import time
import secrets
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4
from urllib.request import urlopen


@dataclass(frozen=True)
class ImageGenerationConfig:
    workflow: Path
    prompt_node: str
    prompt_input: str
    comfy_url: str
    kobold_url: str
    comfy_output: Path
    public_output: Path
    public_url_prefix: str
    kobold_process: str
    kobold_start: tuple[str, ...]
    comfy_start: tuple[str, ...]

    @classmethod
    def from_environment(cls) -> "ImageGenerationConfig":
        def required(name: str) -> str:
            value = os.environ.get(name, "").strip()
            if not value:
                raise RuntimeError(f"{name} must be configured before image generation is enabled.")
            return value

        def command(name: str) -> tuple[str, ...]:
            value = json.loads(required(name))
            if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
                raise RuntimeError(f"{name} must be a non-empty JSON string array.")
            return tuple(value)

        return cls(
            workflow=Path(required("RINO_IMAGE_WORKFLOW")).resolve(),
            prompt_node=required("RINO_IMAGE_PROMPT_NODE"),
            prompt_input=required("RINO_IMAGE_PROMPT_INPUT"),
            comfy_url=required("RINO_IMAGE_COMFYUI_URL").rstrip("/"),
            kobold_url=required("RINO_IMAGE_KOBOLD_URL").rstrip("/"),
            comfy_output=Path(required("RINO_IMAGE_COMFYUI_OUTPUT_DIR")).resolve(),
            public_output=Path(required("RINO_IMAGE_PUBLIC_OUTPUT_DIR")).resolve(),
            public_url_prefix=required("RINO_IMAGE_PUBLIC_URL_PREFIX").rstrip("/"),
            kobold_process=required("RINO_IMAGE_KOBOLD_PROCESS"),
            kobold_start=command("RINO_IMAGE_KOBOLD_START"),
            comfy_start=command("RINO_IMAGE_COMFYUI_START"),
        )


class ImageGenerationService:
    """Serializes GPU ownership: KoboldCpp -> ComfyUI -> KoboldCpp."""

    def __init__(self, config: ImageGenerationConfig, event_hub, audit) -> None:
        self.config = config
        self.event_hub = event_hub
        self.audit = audit
        self.jobs: dict[str, dict] = {}
        self._lock = asyncio.Lock()
        self._comfy_process: subprocess.Popen | None = None

    def submit(self, prompt: str) -> dict:
        job_id = uuid4().hex
        self.jobs[job_id] = {"job_id": job_id, "status": "queued", "prompt": prompt, "images": []}
        asyncio.create_task(self._run(job_id))
        return {"job_id": job_id, "status": "queued"}

    async def _run(self, job_id: str) -> None:
        job = self.jobs[job_id]
        async with self._lock:
            try:
                job["status"] = "switching_to_comfyui"
                await asyncio.to_thread(self._stop_by_image_name, self.config.kobold_process)
                await asyncio.to_thread(self._start_and_wait, self.config.comfy_start)
                job["status"] = "generating"
                prompt_id = await asyncio.to_thread(self._queue_prompt, job["prompt"])
                images = await asyncio.to_thread(self._wait_for_images, prompt_id, job_id)
                job.update(status="succeeded", prompt_id=prompt_id, images=images)
                self.audit.write("image.generation.succeeded", job_id=job_id, prompt_id=prompt_id, image_count=len(images))
                await self.event_hub.publish({"type": "image.generation_completed", "job_id": job_id, "images": images})
            except Exception as error:
                job.update(status="failed", error=str(error)[:500])
                self.audit.write("image.generation.failed", job_id=job_id, error=str(error))
                await self.event_hub.publish({"type": "image.generation_failed", "job_id": job_id})
            finally:
                job["status"] = "restoring_rino" if job["status"] != "succeeded" else job["status"]
                try:
                    await asyncio.to_thread(self._stop_process_tree, self._comfy_process)
                    await asyncio.to_thread(self._start_and_wait, self.config.kobold_start, self.config.kobold_url, "v1/models")
                except Exception as error:
                    job.update(status="restore_failed", error=str(error)[:500])
                    self.audit.write("image.generation.restore_failed", job_id=job_id, error=str(error))
                else:
                    if job["status"] == "restoring_rino":
                        job["status"] = "failed"

    def _stop_by_image_name(self, image_name: str) -> None:
        # No shell is used; the configured image name is the sole stop target.
        subprocess.run(["taskkill", "/IM", image_name, "/T", "/F"], capture_output=True, check=False, text=True)

    def _start_and_wait(self, command: tuple[str, ...], base_url: str | None = None, ready_path: str = "system_stats") -> None:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if base_url is None:
            self._comfy_process = process
        base_url = (base_url or self.config.comfy_url).rstrip("/")
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                with urlopen(f"{base_url}/{ready_path}", timeout=2) as response:
                    if response.status < 500:
                        return
            except Exception:
                time.sleep(1)
        raise RuntimeError(f"Timed out waiting for {base_url}/{ready_path}.")

    def _stop_process_tree(self, process: subprocess.Popen | None) -> None:
        if process is None or process.poll() is not None:
            return
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, check=False, text=True)
        self._comfy_process = None

    def _queue_prompt(self, user_prompt: str) -> str:
        workflow = json.loads(self.config.workflow.read_text(encoding="utf-8"))
        try:
            workflow[self.config.prompt_node]["inputs"][self.config.prompt_input] = user_prompt
        except (KeyError, TypeError) as error:
            raise RuntimeError("Configured workflow prompt node/input was not found.") from error
        # Workflows commonly link every KSampler to one SeedNode.  Refreshing
        # those source nodes preserves the workflow graph while ensuring a
        # fresh result on every chat request.
        for node in workflow.values():
            if isinstance(node, dict) and node.get("class_type") == "SeedNode":
                node.setdefault("inputs", {})["seed"] = secrets.randbelow(2**63)
        from urllib.request import Request
        request = Request(f"{self.config.comfy_url}/prompt", data=json.dumps({"prompt": workflow, "client_id": "rino-image"}).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            result = json.loads(response.read())
        prompt_id = result.get("prompt_id")
        if not isinstance(prompt_id, str) or not prompt_id:
            raise RuntimeError("ComfyUI did not accept the image job.")
        return prompt_id

    def _wait_for_images(self, prompt_id: str, job_id: str) -> list[str]:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            with urlopen(f"{self.config.comfy_url}/history/{prompt_id}", timeout=10) as response:
                history = json.loads(response.read())
            entry = history.get(prompt_id)
            if entry:
                # PreviewImage and custom preview nodes return temporary files
                # alongside SaveImage output.  Only output files are publishable
                # after ComfyUI is shut down.
                images = [
                    image
                    for output in entry.get("outputs", {}).values()
                    for image in output.get("images", [])
                    if image.get("type", "output") == "output"
                ]
                if images:
                    return self._publish_images(images, job_id)
            time.sleep(1)
        raise RuntimeError("Timed out waiting for ComfyUI image output.")

    def _publish_images(self, images: list[dict], job_id: str) -> list[str]:
        self.config.public_output.mkdir(parents=True, exist_ok=True)
        urls: list[str] = []
        for index, image in enumerate(images, start=1):
            filename = str(image.get("filename", ""))
            subfolder = str(image.get("subfolder", ""))
            # ComfyUI versions/custom SaveImage nodes differ: some put the
            # relative directory in ``subfolder``, while others include it in
            # ``filename``.  Accept only existing files contained by the
            # configured output root; callers still cannot choose a path.
            root = self.config.comfy_output.resolve()
            candidates = (
                (root / subfolder / filename).resolve(),
                (root / filename).resolve(),
                (root / subfolder / Path(filename).name).resolve(),
            )
            source = next((path for path in candidates if root in path.parents and path.is_file()), None)
            if source is None:
                raise RuntimeError("ComfyUI returned an invalid output path.")
            target_name = f"{job_id}-{index}{source.suffix.lower()}"
            shutil.copy2(source, self.config.public_output / target_name)
            urls.append(f"{self.config.public_url_prefix}/{target_name}")
        return urls
