#!/usr/bin/env python3
"""
Monitor running Ollama instances and their GPU information.
Returns JSON output with port mappings and GPU details.
"""

import json
import subprocess
import re
import sys
import http.client
from urllib import request, error
from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path


def get_running_ollama_instances() -> List[Dict[str, Any]]:
    """
    Try to get Ollama instances from:
    1. ollama_launcher GPU mapping file (/tmp/ollama_gpu_mapping.json)
    2. Legacy systemd unit files (/etc/systemd/system/ollama-gpu-*.service)
    3. Port discovery fallback
    """
    from glob import glob

    # Try mapping file first (new launcher)
    mapping_file = Path("/tmp/ollama_gpu_mapping.json")
    if mapping_file.exists():
        try:
            with open(mapping_file) as f:
                mapping = json.load(f)
            instances = []
            for port_str, config in mapping.items():
                port = int(port_str)
                gpu_index = config.get("gpu_index")
                instances.append({
                    'pid': None,
                    'port': port,
                    'gpu_uuid': None,
                    'gpu_index': gpu_index,
                })
            return sorted(instances, key=lambda x: x['port'])
        except (json.JSONDecodeError, ValueError, KeyError):
            pass  # Fallback to systemd

    # Try legacy systemd unit files
    unit_files = sorted(glob('/etc/systemd/system/ollama-gpu-*.service'))
    if unit_files:
        return _instances_from_unit_files(unit_files)

    # Fallback: discover ports via ss + HTTP probe (no GPU mapping)
    pid_to_port = get_ports_from_ss_with_pids()
    ports = discover_ollama_ports(pid_to_port)
    return [{'pid': None, 'port': p, 'gpu_uuid': None, 'gpu_index': None} for p in ports]


def _instances_from_unit_files(unit_files: List[str]) -> List[Dict[str, Any]]:
    """Build instance list from systemd unit files."""
    instances = []
    for path in unit_files:
        port = None
        gpu_uuid = None
        gpu_index = None
        service_name = Path(path).stem   # e.g. ollama-gpu-68f663ec
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    m = re.match(r'^Environment=OLLAMA_HOST=\S+:(\d+)', line)
                    if m:
                        port = int(m.group(1))
                    m = re.match(r'^Environment=CUDA_VISIBLE_DEVICES=(.+)$', line)
                    if m:
                        gpu_uuid, gpu_index = parse_cuda_visible_devices(m.group(1))
        except IOError:
            continue
        if port is None:
            continue
        pid = _get_pid_for_service(service_name)
        instances.append({
            'pid': pid,
            'port': port,
            'gpu_uuid': gpu_uuid,
            'gpu_index': gpu_index,
        })

    return sorted(instances, key=lambda x: x['port'])


def parse_cuda_visible_devices(raw_value: str) -> Tuple[Optional[str], Optional[int]]:
    """Parse CUDA_VISIBLE_DEVICES into either a GPU UUID or a GPU index."""
    value = raw_value.strip().strip('"').strip("'")
    if not value:
        return None, None

    # Keep the first token if a list is configured (e.g. "0,1").
    first_token = value.split(',')[0].strip()
    if first_token.startswith('GPU-'):
        return first_token, None
    if first_token.isdigit():
        return None, int(first_token)
    return None, None


def _get_pid_for_service(service_name: str) -> int:
    """Find the main PID of a systemd service by scanning /proc/*/cgroup."""
    from glob import glob
    unit_filename = service_name + '.service'
    for cgroup_path in glob('/proc/*/cgroup'):
        try:
            with open(cgroup_path) as f:
                if unit_filename in f.read():
                    return int(cgroup_path.split('/')[2])
        except (IOError, ValueError):
            pass
    return None


def extract_port_from_cmdline(pid: int) -> int:
    """
    Extract port number from ollama process command line.
    
    First checks for --port flag, then checks listening ports via netstat.
    
    Args:
        pid: Process ID
        
    Returns:
        Port number or None if not found
    """
    # Try reading /proc/cmdline
    try:
        cmdline_path = Path(f"/proc/{pid}/cmdline")
        if cmdline_path.exists():
            with open(cmdline_path) as f:
                cmdline = f.read().replace('\x00', ' ')
                # Look for --port XXXX pattern
                match = re.search(r'--port\s+(\d+)', cmdline)
                if match:
                    return int(match.group(1))
    except (IOError, ValueError):
        pass
    
    # Fallback: check ss mapping for ports opened by this PID
    pid_to_port = get_ports_from_ss_with_pids()
    if pid in pid_to_port:
        return pid_to_port[pid]
    
    # Default ollama port
    return 11434


def get_ports_from_ss_with_pids() -> Dict[int, int]:
    """Return a PID->port map from ss output when process info is available."""
    pid_to_port: Dict[int, int] = {}
    try:
        ss_output = subprocess.run(
            ["ss", "-ltnp"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return pid_to_port

    for line in ss_output.stdout.splitlines():
        if 'ollama' not in line:
            continue
        port_match = re.search(r':(\d+)\s', line)
        pid_match = re.search(r'pid=(\d+)', line)
        if not port_match or not pid_match:
            continue
        pid_to_port[int(pid_match.group(1))] = int(port_match.group(1))
    return pid_to_port


def discover_ollama_ports(pid_to_port: Dict[int, int]) -> List[int]:
    """Discover listening Ollama ports even without sudo by probing localhost listeners."""
    ports = set(pid_to_port.values())

    try:
        ss_output = subprocess.run(
            ["ss", "-ltn"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return sorted(ports)

    candidate_ports = set()
    for line in ss_output.stdout.splitlines():
        if '127.0.0.1:' not in line and '[::1]:' not in line:
            continue
        match = re.search(r':(\d+)\s', line)
        if not match:
            continue
        candidate_ports.add(int(match.group(1)))

    for port in sorted(candidate_ports):
        if is_ollama_http_port(port):
            ports.add(port)

    return sorted(ports)


def is_ollama_http_port(port: int) -> bool:
    """Return True if localhost:port responds like an Ollama API endpoint."""
    try:
        with request.urlopen(f"http://127.0.0.1:{port}/api/tags", timeout=0.35) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8"))
            return isinstance(payload, dict) and "models" in payload
    except (error.URLError, TimeoutError, ValueError, json.JSONDecodeError, http.client.HTTPException):
        return False


def get_gpu_info() -> List[Dict[str, Any]]:
    """
    Get GPU information using nvidia-smi.
    
    Returns:
        List of dicts with GPU details
    """
    try:
        # Check if nvidia-smi is available
        subprocess.run(
            ["which", "nvidia-smi"],
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError:
        return []
    
    gpus = []
    
    try:
        # Get GPU list and properties
        gpu_output = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,uuid,name,memory.total,compute_cap",
                "--format=csv,noheader"
            ],
            capture_output=True,
            text=True,
            check=True
        )
    except subprocess.CalledProcessError as e:
        print(f"Error running nvidia-smi: {e}", file=sys.stderr)
        return []
    
    for line in gpu_output.stdout.strip().split('\n'):
        if not line.strip():
            continue
        
        try:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 5:
                gpu_index = int(parts[0])
                gpu_uuid  = parts[1]
                gpu_name  = parts[2]
                memory_total = parts[3]
                compute_cap  = parts[4]

                memory_used = get_gpu_memory_used(gpu_index)
                cuda_cores  = calculate_cuda_cores(gpu_name, compute_cap)

                gpus.append({
                    'index': gpu_index,
                    'uuid':  gpu_uuid,
                    'name':  gpu_name,
                    'memory': {
                        'total': memory_total,
                        'used':  memory_used
                    },
                    'compute_capability': compute_cap,
                    'cuda_cores': cuda_cores
                })
        except (ValueError, IndexError) as e:
            continue
    
    return gpus


def get_gpu_memory_used(gpu_index: int) -> str:
    """
    Get GPU memory currently used.
    
    Args:
        gpu_index: GPU index
        
    Returns:
        Memory string (e.g., "5000 MiB")
    """
    try:
        mem_output = subprocess.run(
            [
                "nvidia-smi",
                f"--id={gpu_index}",
                "--query-gpu=memory.used",
                "--format=csv,noheader"
            ],
            capture_output=True,
            text=True,
            check=True
        )
        return mem_output.stdout.strip()
    except subprocess.CalledProcessError:
        return "Unknown"


def calculate_cuda_cores(gpu_name: str, compute_cap: str) -> int:
    """
    Calculate approximate CUDA cores based on GPU model and compute capability.
    
    Args:
        gpu_name: GPU model name
        compute_cap: Compute capability (e.g., "8.6")
        
    Returns:
        Estimated CUDA core count
    """
    # Known CUDA core counts for common GPUs
    cuda_core_map = {
        "RTX 3090": 10496,
        "RTX 3080": 8704,
        "RTX 3070": 5888,
        "RTX 3060": 3584,
        "RTX 4090": 16384,
        "RTX 4080": 9728,
        "RTX 4070": 5888,
        "A100": 6912,
        "H100": 14080,
        "V100": 5120,
        "T4": 2560,
        "GTX 1080": 2560,
    }
    
    # Try direct match first
    for model, cores in cuda_core_map.items():
        if model in gpu_name:
            return cores
    
    # Fallback: estimate based on compute capability
    # Rough formula: multiply compute units by ~128 cores per unit
    try:
        major, minor = compute_cap.split('.')
        major = int(major)
        minor = int(minor)
        
        # Architecture-specific multipliers
        if major == 9:  # Ada (RTX 40xx)
            return 12800  # rough estimate
        elif major == 8:  # Ampere (RTX 30xx, A100)
            return 7500   # rough estimate
        elif major == 7:  # Volta/Turing
            return 5000   # rough estimate
    except (ValueError, AttributeError):
        pass
    
    return None


def main():
    """Main function to gather and output monitoring data."""

    instances = get_running_ollama_instances()
    gpus = get_gpu_info()

    # Build UUID → GPU info map (nvidia-smi returns uuid in query-gpu)
    uuid_map: Dict[str, Any] = {}
    for g in gpus:
        if g.get('uuid'):
            uuid_map[g['uuid']] = g

    output = []
    for inst in instances:
        gpu_uuid = inst.get('gpu_uuid')
        gpu_index = inst.get('gpu_index')
        gpu = uuid_map.get(gpu_uuid) if gpu_uuid else None
        if gpu is None and isinstance(gpu_index, int):
            gpu = next((g for g in gpus if g.get('index') == gpu_index), None)
        # Fallback: if UUID not resolved, try matching by short UUID prefix in the key
        if gpu is None and gpu_uuid:
            for uid, g in uuid_map.items():
                if gpu_uuid.startswith(uid[:20]) or uid.startswith(gpu_uuid[:20]):
                    gpu = g
                    break
        
        # Final fallback: if no GPU info found, use gpu_index as label
        if gpu is None and isinstance(gpu_index, int):
            gpu = {
                'index': gpu_index,
                'name': f'GPU {gpu_index}',
                'uuid': None,
            }
        
        output.append({
            'pid':  inst.get('pid'),
            'port': inst['port'],
            'gpu':  gpu,
        })

    print(json.dumps(output, indent=2))
    return 0 if output else 1


if __name__ == '__main__':
    sys.exit(main())
