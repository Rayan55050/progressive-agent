"""
System monitoring tool — CPU, RAM, disk, processes, network.

Uses psutil for cross-platform system monitoring.
Falls back to subprocess if psutil is not installed.
"""

from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any

from src.core.tools import ToolDefinition, ToolParameter, ToolResult

logger = logging.getLogger(__name__)

try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not installed — system tool limited. Install: pip install psutil")


class SystemTool:
    """System monitoring: CPU, RAM, disk, processes, network."""

    @property
    def definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="system",
            description=(
                "Monitor system health: CPU, RAM, disk, processes, network. "
                "Actions: 'overview' — full system status; "
                "'processes' — top processes by CPU or memory; "
                "'disk' — disk usage per drive; "
                "'network' — network stats and connections. "
                "Runs locally, no API needed."
            ),
            parameters=[
                ToolParameter(
                    name="action",
                    type="string",
                    description="Action: 'overview', 'processes', 'disk', 'network'",
                    required=False,
                    enum=["overview", "processes", "disk", "network"],
                ),
                ToolParameter(
                    name="sort_by",
                    type="string",
                    description="Sort processes by: 'cpu' or 'memory' (for 'processes' action)",
                    required=False,
                    enum=["cpu", "memory"],
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Number of top processes to show (default: 10)",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        if not PSUTIL_AVAILABLE:
            return ToolResult(
                success=False,
                error="psutil not installed. Run: pip install psutil",
            )

        action = kwargs.get("action", "overview").strip().lower()

        try:
            if action == "overview":
                return await asyncio.to_thread(self._overview)
            elif action == "processes":
                sort_by = kwargs.get("sort_by", "memory").strip().lower()
                limit = int(kwargs.get("limit", 10))
                return await asyncio.to_thread(self._processes, sort_by, limit)
            elif action == "disk":
                return await asyncio.to_thread(self._disk)
            elif action == "network":
                return await asyncio.to_thread(self._network)
            else:
                return ToolResult(success=False, error=f"Unknown action: {action}")
        except Exception as e:
            logger.error("System tool error: %s", e)
            return ToolResult(success=False, error=f"System error: {e}")

    def _overview(self) -> ToolResult:
        """Full system overview."""
        cpu_pct = psutil.cpu_percent(interval=1)
        cpu_count = psutil.cpu_count()
        cpu_freq = psutil.cpu_freq()

        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()

        boot = psutil.boot_time()
        import datetime
        uptime = datetime.datetime.now() - datetime.datetime.fromtimestamp(boot)
        uptime_str = str(uptime).split(".")[0]  # Remove microseconds

        lines = [
            "🖥 **System Overview**\n",
            f"**OS:** {platform.system()} {platform.release()} ({platform.machine()})",
            f"**Uptime:** {uptime_str}",
            "",
            f"**CPU:** {cpu_pct}% ({cpu_count} cores)",
        ]
        if cpu_freq:
            lines.append(f"  Frequency: {cpu_freq.current:.0f} MHz")

        lines.extend([
            "",
            f"**RAM:** {mem.percent}% used ({self._fmt_bytes(mem.used)} / {self._fmt_bytes(mem.total)})",
            f"  Available: {self._fmt_bytes(mem.available)}",
        ])
        if swap.total > 0:
            lines.append(f"**Swap:** {swap.percent}% ({self._fmt_bytes(swap.used)} / {self._fmt_bytes(swap.total)})")

        # Disks summary
        lines.append("\n**Disks:**")
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                warn = " ⚠️" if usage.percent > 90 else ""
                lines.append(
                    f"  {part.device} ({part.mountpoint}): "
                    f"{usage.percent}% used ({self._fmt_bytes(usage.used)} / {self._fmt_bytes(usage.total)}){warn}"
                )
            except PermissionError:
                continue

        # Battery (if laptop)
        battery = psutil.sensors_battery()
        if battery:
            plug = "🔌" if battery.power_plugged else "🔋"
            lines.append(f"\n{plug} **Battery:** {battery.percent}%")

        return ToolResult(success=True, data="\n".join(lines))

    def _processes(self, sort_by: str, limit: int) -> ToolResult:
        """Top processes by CPU or memory."""
        limit = max(1, min(30, limit))
        sort_key = "memory_percent" if sort_by == "memory" else "cpu_percent"

        procs = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent", "memory_info"]):
            try:
                info = p.info
                if info["name"] and info[sort_key] is not None:
                    procs.append(info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        procs.sort(key=lambda x: x[sort_key] or 0, reverse=True)
        top = procs[:limit]

        sort_label = "Memory" if sort_by == "memory" else "CPU"
        lines = [f"**Top {limit} processes by {sort_label}:**\n"]
        for p in top:
            mem_mb = (p.get("memory_info") or type("", (), {"rss": 0})).rss / (1024 * 1024)
            lines.append(
                f"  {p['name'][:25]:<25} "
                f"CPU: {p['cpu_percent']:5.1f}% | "
                f"RAM: {p['memory_percent']:5.1f}% ({mem_mb:.0f} MB) | "
                f"PID: {p['pid']}"
            )

        return ToolResult(success=True, data="\n".join(lines))

    def _disk(self) -> ToolResult:
        """Detailed disk usage."""
        lines = ["💿 **Disk Usage:**\n"]
        for part in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(part.mountpoint)
                free_gb = usage.free / (1024 ** 3)
                total_gb = usage.total / (1024 ** 3)
                warn = " ⚠️ LOW SPACE!" if usage.percent > 90 else ""
                lines.append(
                    f"  **{part.device}** ({part.mountpoint}) [{part.fstype}]\n"
                    f"    Used: {self._fmt_bytes(usage.used)} / {self._fmt_bytes(usage.total)} "
                    f"({usage.percent}%){warn}\n"
                    f"    Free: {free_gb:.1f} GB"
                )
            except PermissionError:
                lines.append(f"  {part.device}: access denied")
        return ToolResult(success=True, data="\n".join(lines))

    def _network(self) -> ToolResult:
        """Network stats."""
        counters = psutil.net_io_counters()
        lines = [
            "🌐 **Network Stats:**\n",
            f"Sent: {self._fmt_bytes(counters.bytes_sent)}",
            f"Received: {self._fmt_bytes(counters.bytes_recv)}",
            f"Packets sent: {counters.packets_sent:,}",
            f"Packets received: {counters.packets_recv:,}",
        ]

        # Active interfaces
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        lines.append("\n**Interfaces:**")
        for iface, addr_list in addrs.items():
            is_up = stats.get(iface, type("", (), {"isup": False})).isup
            status = "UP" if is_up else "DOWN"
            ipv4 = next((a.address for a in addr_list if a.family.name == "AF_INET"), None)
            if ipv4:
                lines.append(f"  {iface}: {ipv4} [{status}]")

        return ToolResult(success=True, data="\n".join(lines))

    @staticmethod
    def _fmt_bytes(b: int) -> str:
        """Format bytes to human-readable string."""
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if b < 1024:
                return f"{b:.1f} {unit}"
            b /= 1024
        return f"{b:.1f} PB"
