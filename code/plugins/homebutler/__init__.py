import docker
import logging
import threading
import time
from datetime import datetime

logger = logging.getLogger(__name__)

# --- Globals ---
# In a real plugin, you'd want a more robust way to manage state
# and the background thread, but this is a simple example.
_event_thread = None
_stop_event = threading.Event()
_event_history = []
_history_lock = threading.Lock()

# --- Main Plugin Logic ---

def monitor_docker_events():
    """Connects to the Docker event stream and handles events."""
    client = docker.from_env()
    logger.info("HomeButler: Starting Docker event monitoring.")

    # Check for running containers on startup
    try:
        containers = client.containers.list()
        logger.info(f"HomeButler: Found {len(containers)} running containers on startup.")
    except Exception as e:
        logger.error(f"HomeButler: Could not connect to Docker daemon on startup: {e}")
        return

    for event in client.events(decode=True):
        if _stop_event.is_set():
            break

        event_type = event.get('Type')
        if event_type != 'container':
            continue

        status = event.get('status')
        actor = event.get('Actor', {})
        attributes = actor.get('Attributes', {})
        name = attributes.get('name')

        if not name:
            continue

        log_event(f"Container '{name}' status: {status}")

        if status in ['die', 'oom']:
            handle_container_failure(name)

def handle_container_failure(container_name):
    """Handles logic for restarting a failed container."""
    now = datetime.now()
    # Quiet hours: 1 AM to 2 AM
    if 1 <= now.hour < 2:
        log_event(f"Quiet hours: Skipping restart for '{container_name}'.")
        return

    try:
        client = docker.from_env()
        log_event(f"Attempting to restart container '{container_name}'...")
        container = client.containers.get(container_name)
        container.restart()
        log_event(f"Successfully restarted container '{container_name}'.")
    except docker.errors.NotFound:
        log_event(f"Container '{container_name}' not found. Cannot restart.")
    except Exception as e:
        log_event(f"Failed to restart container '{container_name}': {e}")


def log_event(message):
    """Logs an event to the console and internal history."""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] {message}"
    logger.info(f"HomeButler: {message}")
    with _history_lock:
        _event_history.append(log_message)
        # Keep history to a reasonable size
        if len(_event_history) > 200:
            _event_history.pop(0)

    # Also log to shared memory
    try:
        with open("/home/rohit/shared_agent_memory/homebutler.log", "a") as f:
            f.write(log_message + "\n")
    except Exception as e:
        logger.error(f"HomeButler: Could not write to shared log file: {e}")


# --- Tool Implementations ---

def docker_health_summary(args=None):
    """Provides a summary of running Docker containers."""
    try:
        client = docker.from_env()
        containers = client.containers.list()
        summary = f"Found {len(containers)} running containers:\n"
        for c in containers:
            summary += f"- {c.name} ({c.short_id}): {c.status}\n"
        return summary
    except Exception as e:
        return f"Error getting Docker health summary: {e}"

def docker_restart_service(service_name: str):
    """Manually restarts a specific Docker container."""
    if not service_name:
        return "Please provide a service name to restart."

    log_event(f"Manual restart requested for '{service_name}'.")
    try:
        client = docker.from_env()
        container = client.containers.get(service_name)
        container.restart()
        return f"Successfully restarted '{service_name}'."
    except docker.errors.NotFound:
        return f"Container '{service_name}' not found."
    except Exception as e:
        return f"Error restarting '{service_name}': {e}"


def docker_event_history(lines: int = 20):
    """Returns the last N lines of the event history."""
    with _history_lock:
        return "\n".join(_event_history[-lines:])

# --- Plugin Registration ---

def register(ctx):
    """Registers the HomeButler plugin."""
    global _event_thread

    # Register tools
    ctx.register_tool(
        name="docker_health_summary",
        toolset="homebutler",
        schema={
            "name": "docker_health_summary",
            "description": "Get a summary of running Docker containers.",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=docker_health_summary,
        description="Get a summary of running Docker containers."
    )
    ctx.register_tool(
        name="docker_restart_service",
        toolset="homebutler",
        schema={
            "name": "docker_restart_service",
            "description": "Restart a specific Docker container by name.",
            "parameters": {"type": "object", "properties": {"service_name": {"type": "string"}}, "required": ["service_name"]},
        },
        handler=docker_restart_service,
        description="Restart a specific Docker container by name."
    )
    ctx.register_tool(
        name="docker_event_history",
        toolset="homebutler",
        schema={
            "name": "docker_event_history",
            "description": "Get the recent event history from HomeButler.",
            "parameters": {"type": "object", "properties": {"lines": {"type": "integer", "default": 20}}},
        },
        handler=docker_event_history,
        description="Get the recent event history from HomeButler."
    )

    # Start the background monitoring thread
    def start_monitoring():
        global _event_thread
        if _event_thread is None or not _event_thread.is_alive():
            _stop_event.clear()
            _event_thread = threading.Thread(target=monitor_docker_events, daemon=True)
            _event_thread.start()

    # Register a hook to start monitoring when a session starts
    ctx.register_hook("on_session_start", start_monitoring)

    logger.info("HomeButler plugin registered.")

