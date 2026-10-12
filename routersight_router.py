"""Router data source for RouterSight (iStoreOS / OpenWrt) - self-contained.

Replaces the Netdata HTTP dependency: opens one SSH session to the router, runs a
read-only POSIX script through `sh -s` (nothing is written on the router), and
derives live metrics from kernel counters.

Why this fixes the "LAN transfer shows 2x speed" bug
----------------------------------------------------
Netdata's `system.net` is the SUM over every interface.  A single flow is counted
once as ingress on one port and again as egress on another (and a third time on
the bridge master), so the old widget displayed a multiple of the real rate.
Here per-interface counters are kept and ONE interface is reported, with download
and upload kept apart - neither is ever added to the other.

Metric shape returned by to_netdata_metrics() is the same dict RouterSight already
consumed from Netdata, plus a 'router' key with per-interface detail.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

try:
    import paramiko
except Exception:  # pragma: no cover - surfaced through test_connection()
    paramiko = None  # type: ignore

# Read-only probe.  Runs as `sh -s` over SSH: no file is created on the router.
AGENT_SCRIPT = """#!/bin/sh
# RouterSight router agent (POSIX / busybox-safe, read-only kernel counters).
echo '[cpu]'
head -n 1 /proc/stat

echo '[mem]'
grep -E '^(MemTotal|MemFree|MemAvailable|Buffers|Cached|SReclaimable|Shmem|SwapTotal|SwapFree):' /proc/meminfo

echo '[net]'
cat /proc/net/dev

echo '[route]'
cat /proc/net/route

echo '[block]'
for d in /sys/block/*; do
  n=${d##*/}
  case "$n" in
    loop*|ram*|zram*) ;;
    *) echo "$n" ;;
  esac
done

echo '[disk]'
cat /proc/diskstats

echo '[sock]'
printf 'tcp %s\\n'  "$(cat /proc/net/tcp  2>/dev/null | wc -l)"
printf 'tcp6 %s\\n' "$(cat /proc/net/tcp6 2>/dev/null | wc -l)"
printf 'udp %s\\n'  "$(cat /proc/net/udp  2>/dev/null | wc -l)"
printf 'udp6 %s\\n' "$(cat /proc/net/udp6 2>/dev/null | wc -l)"
printf 'tcp_estab %s\\n'  "$(cat /proc/net/tcp  2>/dev/null | grep -c ' 01 ' || true)"
printf 'tcp6_estab %s\\n' "$(cat /proc/net/tcp6 2>/dev/null | grep -c ' 01 ' || true)"

echo '[end]'
"""

SECTOR_BYTES = 512


class RouterStatsError(Exception):
    pass


# --------------------------------------------------------------------------- #
# report parsing
# --------------------------------------------------------------------------- #
def parse_report(text: str) -> Dict[str, List[str]]:
    """Split the agent's sectioned output into {section: [lines]}."""
    sections: Dict[str, List[str]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.rstrip('\r')
        stripped = line.strip()
        if len(stripped) > 2 and stripped[0] == '[' and stripped[-1] == ']':
            name = stripped[1:-1]
            if name == 'end':
                break
            current = name
            sections.setdefault(current, [])
            continue
        if current is not None and stripped:
            sections[current].append(line)
    return sections


def parse_cpu(line: str) -> Tuple[int, int]:
    """'cpu  u n s idle iowait irq softirq steal ...' -> (total_jiffies, idle_jiffies)."""
    parts = line.split()
    if not parts or parts[0] != 'cpu':
        raise RouterStatsError('unexpected /proc/stat line: %r' % line[:60])
    vals = [int(x) for x in parts[1:11]]
    while len(vals) < 10:
        vals.append(0)
    user, nice, system, idle, iowait, irq, softirq, steal, guest, guest_nice = vals
    idle_all = idle + iowait
    total = user + nice + system + irq + softirq + steal + idle_all
    return total, idle_all


def parse_meminfo(lines: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for line in lines:
        if ':' not in line:
            continue
        key, _, rest = line.partition(':')
        num = rest.strip().split()
        if num:
            try:
                out[key.strip()] = int(num[0])
            except ValueError:
                pass
    return out


def parse_netdev(lines: List[str]) -> Dict[str, Tuple[int, int]]:
    """{iface: (rx_bytes, tx_bytes)} from /proc/net/dev (skips the 2 header lines)."""
    out: Dict[str, Tuple[int, int]] = {}
    for line in lines:
        if ':' not in line:
            continue
        name, _, rest = line.partition(':')
        name = name.strip()
        if not name or name.startswith('Inter-') or name.startswith('face'):
            continue
        f = rest.split()
        if len(f) < 9:
            continue
        try:
            out[name] = (int(f[0]), int(f[8]))
        except ValueError:
            continue
    return out


def parse_default_iface(lines: List[str]) -> Optional[str]:
    """First default route (Destination 00000000) from /proc/net/route."""
    for line in lines[1:]:
        f = line.split()
        if len(f) >= 2 and f[1] == '00000000':
            return f[0]
    return None


def parse_whole_disks(lines: List[str]) -> List[str]:
    return [l.strip() for l in lines if l.strip()]


def parse_diskstats(lines: List[str], whole_disks: List[str]) -> Tuple[int, int]:
    """Sum (sectors_read, sectors_written) over whole disks only."""
    keep = set(whole_disks)
    rd = wr = 0
    for line in lines:
        f = line.split()
        if len(f) < 10:
            continue
        name = f[2]
        if keep and name not in keep:
            continue
        if not keep and (name[-1].isdigit() and not name.startswith(('nvme', 'mmcblk'))):
            continue
        try:
            rd += int(f[5])
            wr += int(f[9])
        except ValueError:
            continue
    return rd, wr


def parse_sock(lines: List[str]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for line in lines:
        f = line.split()
        if len(f) == 2:
            try:
                out[f[0]] = int(f[1])
            except ValueError:
                pass
    return out


# --------------------------------------------------------------------------- #
# client
# --------------------------------------------------------------------------- #
class RouterStats:
    """Persistent SSH session against the router; thread-safe sampling."""

    def __init__(self, host: str, port: int = 22, username: str = 'root',
                 password: str = '', key_filename: str = '', timeout: float = 6.0,
                 interface: str = 'auto', agent_path: str = '',
                 auto_reconnect: bool = True) -> None:
        self.host = host
        self.port = int(port or 22)
        self.username = username or 'root'
        self.password = password or ''
        self.key_filename = key_filename or ''
        self.timeout = float(timeout or 6.0)
        self.interface = interface or 'auto'
        self.agent_path = agent_path or ''
        self.auto_reconnect = auto_reconnect

        self._client = None  # type: Optional['paramiko.SSHClient']
        self._agent = self._load_agent(self.agent_path)
        self._lock = threading.RLock()
        self._prev: Optional[Dict[str, Any]] = None
        self._last_error = ''
        self.last_interfaces: List[str] = []

    # -- agent script ------------------------------------------------------ #
    @staticmethod
    def _load_agent(path: str) -> str:
        """Bundled script by default; an external file only for development."""
        if path:
            try:
                with open(path, 'r', encoding='utf-8') as fh:
                    return fh.read()
            except OSError:
                pass
        return AGENT_SCRIPT

    # -- connection -------------------------------------------------------- #
    def _connect(self):
        if paramiko is None:
            raise RouterStatsError('paramiko 不可用（打包时未包含）')
        host = (self.host or '').strip()
        if not host:
            raise RouterStatsError('未配置路由器地址')
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        kwargs = dict(
            hostname=host,
            port=self.port,
            username=self.username,
            timeout=self.timeout,
            banner_timeout=self.timeout,
            auth_timeout=self.timeout,
            allow_agent=False,
            look_for_keys=bool(self.key_filename),
        )
        if self.password:
            kwargs['password'] = self.password
        if self.key_filename:
            kwargs['key_filename'] = self.key_filename
        try:
            client.connect(**kwargs)
        except Exception as exc:
            raise RouterStatsError(_friendly_auth_error(exc)) from exc
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(15)
        self._client = client
        return client

    def _ensure_client(self):
        if self._client is not None:
            transport = self._client.get_transport()
            if transport is not None and transport.is_active():
                return self._client
            self.close()
        return self._connect()

    def close(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            try:
                client.close()
            except Exception:
                pass

    # -- one sample -------------------------------------------------------- #
    def _run_agent(self) -> str:
        client = self._ensure_client()
        try:
            stdin, stdout, stderr = client.exec_command('sh -s', timeout=self.timeout)
            stdin.write(self._agent)
            stdin.flush()
            stdin.channel.shutdown_write()
            out = stdout.read().decode('utf-8', 'replace')
            err = stderr.read().decode('utf-8', 'replace')
            try:
                stdout.channel.recv_exit_status()
            except Exception:
                pass
        except RouterStatsError:
            raise
        except Exception as exc:
            self.close()
            raise RouterStatsError('读取路由器失败: %s' % exc) from exc
        if not out.strip():
            raise RouterStatsError('路由器没有返回数据%s' % (': ' + err.strip()[:200] if err.strip() else ''))
        return out

    def sample(self) -> Dict[str, Any]:
        """One measurement. Rates need two samples, so the first call reports 0."""
        with self._lock:
            text = self._run_agent()
            return self._compute(parse_report(text))

    def _compute(self, sections: Dict[str, List[str]]) -> Dict[str, Any]:
        now = time.monotonic()
        cpu_lines = sections.get('cpu', [])
        if not cpu_lines:
            raise RouterStatsError('缺少 [cpu] 数据')
        cpu_total, cpu_idle = parse_cpu(cpu_lines[0])

        mem = parse_meminfo(sections.get('mem', []))
        net = parse_netdev(sections.get('net', []))
        default_iface = parse_default_iface(sections.get('route', []))
        disks = parse_whole_disks(sections.get('block', []))
        disk_rd, disk_wr = parse_diskstats(sections.get('disk', []), disks)
        sock = parse_sock(sections.get('sock', []))

        mem_total = mem.get('MemTotal', 0)
        mem_avail = mem.get('MemAvailable', mem.get('MemFree', 0))
        mem_used = max(0, mem_total - mem_avail)

        result: Dict[str, Any] = {
            'ts': now,
            'cpu_percent': 0.0,
            'mem_total_kb': mem_total,
            'mem_used_kb': mem_used,
            'mem_avail_kb': mem_avail,
            'mem_free_kb': mem.get('MemFree', 0),
            'mem_cached_kb': mem.get('Cached', 0) + mem.get('SReclaimable', 0),
            'mem_buffers_kb': mem.get('Buffers', 0),
            'mem_percent': (mem_used / mem_total * 100.0) if mem_total else 0.0,
            'net_raw': net,
            'net': {},
            'net_default_iface': default_iface,
            'disk_read_kib': 0.0,
            'disk_write_kib': 0.0,
            'tcp_estab': sock.get('tcp_estab', 0) + sock.get('tcp6_estab', 0),
            'udp_inuse': max(0, sock.get('udp', 0) - 1) + max(0, sock.get('udp6', 0) - 1),
        }

        prev = self._prev
        if prev is not None:
            dt = now - prev['ts']
            if 0.05 < dt < 120:
                d_total = cpu_total - prev['cpu_total']
                d_idle = cpu_idle - prev['cpu_idle']
                if d_total > 0:
                    result['cpu_percent'] = max(0.0, min(100.0, (1.0 - d_idle / d_total) * 100.0))
                for name, (rx, tx) in net.items():
                    prx, ptx = prev['net_raw'].get(name, (rx, tx))
                    # bytes/s -> kilobits/s (the unit RouterSight's network card expects)
                    result['net'][name] = {
                        'rx_kbps': max(0.0, (rx - prx) * 8.0 / 1000.0 / dt),
                        'tx_kbps': max(0.0, (tx - ptx) * 8.0 / 1000.0 / dt),
                        'rx_bps': max(0.0, (rx - prx) / dt),
                        'tx_bps': max(0.0, (tx - ptx) / dt),
                        'rx_bytes': rx,
                        'tx_bytes': tx,
                    }
                # sectors -> KiB/s
                result['disk_read_kib'] = max(0.0, (disk_rd - prev['disk_rd']) * SECTOR_BYTES / 1024.0 / dt)
                result['disk_write_kib'] = max(0.0, (disk_wr - prev['disk_wr']) * SECTOR_BYTES / 1024.0 / dt)

        self._prev = {
            'ts': now,
            'cpu_total': cpu_total,
            'cpu_idle': cpu_idle,
            'net_raw': net,
            'disk_rd': disk_rd,
            'disk_wr': disk_wr,
        }
        self.last_interfaces = sorted(net.keys())
        return result

    # -- interface choice -------------------------------------------------- #
    def pick_interface(self, sample: Dict[str, Any], prefer: Optional[str] = None) -> Optional[str]:
        """Resolve 'auto' to one concrete interface, so nothing is double counted."""
        want = (prefer if prefer is not None else self.interface) or 'auto'
        net = sample.get('net') or {}
        if want and want != 'auto':
            if want in net:
                return want
            if want in (sample.get('net_raw') or {}):
                return want
        if not net:
            return sample.get('net_default_iface')
        default_iface = sample.get('net_default_iface')
        if default_iface in net and (net[default_iface]['rx_kbps'] + net[default_iface]['tx_kbps']) > 0:
            return default_iface
        def load(item):
            return item[1]['rx_kbps'] + item[1]['tx_kbps']
        best = max(net.items(), key=load)
        if load(best) > 0:
            return best[0]
        for candidate in ('eth1', 'eth0', default_iface):
            if candidate in net:
                return candidate
        return sorted(net)[0] if net else None

    # -- Netdata-compatible view ------------------------------------------- #
    def to_netdata_metrics(self, sample: Dict[str, Any], interface: Optional[str] = None) -> Dict[str, Any]:
        """Same dict shape RouterSight already consumed from Netdata allmetrics.

        Extra keys under 'router' carry one-interface download/upload detail.
        """
        iface = interface or self.pick_interface(sample)
        net = (sample.get('net') or {}).get(iface or '', {})
        rx = net.get('rx_kbps', 0.0)
        tx = net.get('tx_kbps', 0.0)
        used = sample.get('mem_used_kb', 0)
        avail = sample.get('mem_avail_kb', 0)
        free = sample.get('mem_free_kb', 0)
        total = used + avail
        # RouterSight turns these four dimensions into used/(used+free+cached+buffers).
        # Split the *available* memory so they still add up to MemTotal, which makes
        # the card read (MemTotal - MemAvailable) / MemTotal - the usual "in use".
        cached = max(0, min(sample.get('mem_cached_kb', 0), avail - free))
        buffers = max(0, avail - free - cached)
        plain_used = max(0, used)
        return {
            'system.cpu': {'dimensions': {'user': {'value': sample.get('cpu_percent', 0.0)},
                                          'system': {'value': 0}}},
            'system.ram': {'dimensions': {'used': {'value': plain_used},
                                          'free': {'value': free},
                                          'cached': {'value': cached},
                                          'buffers': {'value': buffers}}},
            'system.io': {'dimensions': {'in': {'value': sample.get('disk_read_kib', 0.0)},
                                         'out': {'value': sample.get('disk_write_kib', 0.0)}}},
            'system.net': {'dimensions': {'InOctets': {'value': rx},
                                          'OutOctets': {'value': tx}}},
            'ipv4.tcpsock': {'dimensions': {'CurrEstab': {'value': sample.get('tcp_estab', 0)}}},
            'ipv4.sockstat_udp_sockets': {'dimensions': {'inuse': {'value': sample.get('udp_inuse', 0)}}},
            'router': {
                'interface': iface,
                'interfaces': sorted((sample.get('net') or {}).keys()),
                'rx_kbps': rx,
                'tx_kbps': tx,
                'mem_total_kb': total,
                'cpu_percent': sample.get('cpu_percent', 0.0),
                'source': 'router-ssh',
            },
        }

    # -- health ------------------------------------------------------------ #
    def test_connection(self) -> Tuple[bool, str]:
        """Non-fatal check used by the settings dialog."""
        try:
            with self._lock:
                text = self._run_agent()
            sections = parse_report(text)
            iface = parse_default_iface(sections.get('route', [])) or '?'
            n_if = len(parse_netdev(sections.get('net', [])))
            return True, 'OK（%d 个网卡，默认 %s）' % (n_if, iface)
        except Exception as exc:
            return False, str(exc)


# --------------------------------------------------------------------------- #
def _friendly_auth_error(exc: Exception) -> str:
    name = type(exc).__name__
    text = str(exc)
    if 'Authentication' in name or 'authentication' in text.lower():
        return '认证失败：用户名或密码不对'
    if 'NoValidConnections' in name or 'timed out' in text.lower():
        return '连接超时：检查路由器地址和端口'
    if 'UnableToConnect' in name or 'refused' in text.lower():
        return '无法连接：SSH 端口未开放'
    return '连接失败: %s' % text
