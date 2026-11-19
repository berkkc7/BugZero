
import os
import sys
import time
import uuid
import tempfile
import subprocess
import traceback

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

app = FastAPI(
    title="BugZero API",
    description="A Python code execution and debugging prototype",
    version="0.1.0"
)


class ExecuteRequest(BaseModel):
    request_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    language: str = "python"
    code: str = Field(min_length=1, max_length=10000)
    stdin: str = ""
    timeout_ms: int = Field(default=5000, ge=100, le=5000)


class ErrorInfo(BaseModel):
    type: str
    message: str
    line: int | None = None


class ExecuteResponse(BaseModel):
    request_id: str
    status: str
    stdout: str
    stderr: str
    exit_code: int | None
    duration_ms: int
    error: ErrorInfo | None = None


@app.get("/")
def home():
    return {
        "name": "BugZero",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/api/v1/execute", response_model=ExecuteResponse)
def execute_code(request: ExecuteRequest):

    if request.language != "python":
        raise HTTPException(
            status_code=400,
            detail="Only Python is currently supported."
        )

    start_time = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="bugzero_") as temp_dir:
        file_path = os.path.join(temp_dir, "program.py")

        with open(file_path, "w", encoding="utf-8") as file:
            file.write(request.code)

        try:
            result = subprocess.run(
                [sys.executable, "-I", file_path],
                input=request.stdin,
                capture_output=True,
                text=True,
                timeout=request.timeout_ms / 1000,
                cwd=temp_dir,
                env={
                    "PATH": os.environ.get("PATH", ""),
                    "PYTHONIOENCODING": "utf-8"
                }
            )

            duration = int(
                (time.perf_counter() - start_time) * 1000
            )

            error = None

            if result.returncode != 0:
                error_type = "RuntimeError"
                error_message = "Execution failed."
                error_line = None

                try:
                    lines = result.stderr.strip().splitlines()

                    if lines:
                        error_message = lines[-1]

                    for line in lines:
                        if "Error:" in line:
                            error_type = line.split(":")[0].strip()
                            break

                    import re
                    matches = re.findall(
                        r'line (\d+)',
                        result.stderr
                    )

                    if matches:
                        error_line = int(matches[-1])

                except Exception:
                    pass

                error = ErrorInfo(
                    type=error_type,
                    message=error_message,
                    line=error_line
                )

            return ExecuteResponse(
                request_id=request.request_id,
                status="success" if result.returncode == 0 else "error",
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                duration_ms=duration,
                error=error
            )

        except subprocess.TimeoutExpired:
            duration = int(
                (time.perf_counter() - start_time) * 1000
            )

            return ExecuteResponse(
                request_id=request.request_id,
                status="timeout",
                stdout="",
                stderr="Execution timed out.",
                exit_code=None,
                duration_ms=duration,
                error=ErrorInfo(
                    type="TimeoutError",
                    message="Execution exceeded the time limit."
                )
            )

        except Exception as exc:
            return ExecuteResponse(
                request_id=request.request_id,
                status="error",
                stdout="",
                stderr="Internal execution error.",
                exit_code=None,
                duration_ms=int(
                    (time.perf_counter() - start_time) * 1000
                ),
                error=ErrorInfo(
                    type=type(exc).__name__,
                    message="An internal error occurred."
                )
            )
