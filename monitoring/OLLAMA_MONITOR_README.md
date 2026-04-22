# Ollama Monitor Tool

A Python script to discover running Ollama instances on a Ubuntu server and retrieve their GPU information.

## Features

- **Discovers running Ollama instances**: Finds all active Ollama processes and their ports
- **GPU Information**: Retrieves detailed GPU specs including:
  - Model/Name (e.g., RTX 3090, A100)
  - Total VRAM
  - Current VRAM usage
  - CUDA compute capability
  - CUDA core count (estimated or known values)
- **JSON Output**: Easy to integrate with monitoring systems and automation tools

## Requirements

- Python 3.6+
- NVIDIA GPU with nvidia-smi installed
- `netstat` utility (usually available on Ubuntu)
- CUDA-capable system

## Installation

The script is already executable. No additional dependencies beyond what's listed above.

## Usage

### Basic Usage

```bash
./ollama_monitor.py
```

Or with Python:

```bash
python3 ollama_monitor.py
```

### Output Format

The script outputs JSON with the following structure:

```json
{
  "timestamp": "2026-04-09T14:30:00+00:00",
  "ollama_instances": [
    {
      "pid": 12345,
      "port": 11434
    },
    {
      "pid": 12346,
      "port": 11435
    }
  ],
  "gpus": [
    {
      "index": 0,
      "name": "NVIDIA RTX 3090",
      "memory": {
        "total": "24 GB",
        "used": "8512 MiB"
      },
      "compute_capability": "8.6",
      "cuda_cores": 10496
    }
  ],
  "summary": {
    "total_ollama_instances": 2,
    "total_gpus": 1,
    "ollama_instances_with_gpu": true
  }
}
```

## Integration Examples

### Save Output to File

```bash
./ollama_monitor.py > ollama_status.json
```

### Parse with jq

```bash
# Get all Ollama ports
./ollama_monitor.py | jq '.ollama_instances[].port'

# Get GPU names
./ollama_monitor.py | jq '.gpus[].name'

# Get total VRAM across all GPUs
./ollama_monitor.py | jq '[.gpus[].memory.total] | join(", ")'
```

### Continuous Monitoring with Watch

```bash
watch -n 5 './ollama_monitor.py | jq .'
```

### Cron Job Example

Add to crontab to log status every 5 minutes:

```bash
*/5 * * * * /home/malo/monitoring/ollama_monitor.py >> /var/log/ollama_monitor.json
```

### Integration with Prometheus

You can wrap this script in a Prometheus exporter if needed. Example:

```python
# Create a wrapper that exposes metrics
from prometheus_client import start_http_server, Gauge
import json
import subprocess

# Create Prometheus metrics
ollama_instances = Gauge('ollama_instances_count', 'Number of running Ollama instances')
gpu_vram_total = Gauge('gpu_vram_total_mb', 'GPU total VRAM in MB', ['gpu_name'])
gpu_vram_used = Gauge('gpu_vram_used_mb', 'GPU used VRAM in MB', ['gpu_name'])

def update_metrics():
    result = subprocess.run(['./ollama_monitor.py'], capture_output=True, text=True)
    data = json.loads(result.stdout)
    ollama_instances.set(data['summary']['total_ollama_instances'])
    # ... update other metrics
```

## Troubleshooting

### Script returns empty ollama_instances

1. **Ollama not running**: Make sure Ollama is actually running
   ```bash
   ps aux | grep ollama
   ```

2. **Permission issues**: The script needs to read `/proc/{pid}/cmdline`. Run with appropriate permissions or use `sudo`

3. **Default port assumption**: If port detection fails, the script defaults to port 11434. Check actual ports with:
   ```bash
   netstat -tulnp | grep -i ollama
   ```

### nvidia-smi errors

1. **NVIDIA drivers not installed**: Install NVIDIA drivers
   ```bash
   ubuntu-drivers autoinstall
   ```

2. **CUDA not installed**: This script only requires nvidia-smi, not full CUDA toolkit

### Inaccurate CUDA core count

- The script uses a known model database for accurate counts
- Falls back to estimation based on compute capability
- You can manually update the `cuda_core_map` dictionary in the script for custom estimates

## Performance Notes

- The script is lightweight and should execute in <1 second
- Safe to run frequently (e.g., every 5-10 seconds)
- Minimal system impact

## Future Enhancements

Potential improvements:
- Memory allocation tracking per Ollama instance
- Real-time monitoring daemon
- Temperature and power consumption tracking
- Prometheus exporter wrapper
- Web dashboard integration
