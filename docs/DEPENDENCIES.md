# Dependencies

This project uses both system networking tools and Python packages. Mininet and
Open vSwitch must be installed at the system level because they create Linux
network namespaces, veth pairs, Open vSwitch bridges, and traffic-control queues.

## Verified Environment

- Ubuntu Linux
- Python 3.14.4 in conda environment `network`
- numpy 2.4.6
- Ryu 4.34, installed from a patched local source checkout
- Mininet
- Open vSwitch with OpenFlow 1.3 support
- iperf3
- tshark / Wireshark

## System Packages

Install the required system tools on Ubuntu:

```bash
sudo apt update
sudo apt install -y mininet openvswitch-switch iperf3 tshark wireshark
```

Optional checks:

```bash
mn --version
ovs-vsctl --version
iperf3 --version
tshark --version
```

## Python Environment

Recommended conda setup:

```bash
conda env create -f environment.yml
conda activate network
pip install -r requirements.txt
```

If the conda environment already exists:

```bash
conda activate network
pip install -r requirements.txt
```

## Ryu Source Install

The verified environment uses Ryu from a local source checkout, not directly
from the PyPI wheel/sdist. This avoids an installation issue with newer
Python/setuptools versions where `setuptools.command.easy_install` may no longer
provide the API expected by Ryu's setup hook.

Recreate the verified Ryu install:

```bash
mkdir -p tmp
git clone https://github.com/faucetsdn/ryu tmp/ryu_source
cd tmp/ryu_source
git checkout d6cda4f4
git apply ../../patches/ryu-python314-hooks.patch
pip install .
cd ../..
```

The local checkout is intentionally under `tmp/` and is not committed to this
repository.

Check the Python-side dependencies:

```bash
python3 -c "import numpy; print(numpy.__version__)"
ryu-manager --version
```

Expected versions in the verified environment:

```text
numpy 2.4.6
ryu-manager 4.34
```

## Mininet Cleanup

Before starting a new Mininet experiment, clean old namespaces and interfaces:

```bash
sudo mn -c
```

Do not run `sudo mn -c` while another Mininet topology is still running.

## Notes

- Ryu may print Eventlet deprecation warnings. They do not affect this project.
- Some experiments need `sudo -E python3 ...` so the root process can keep the
  active conda environment.
- `mininet` is not listed in `requirements.txt` because the project uses the
  system Mininet package, not a pip package.
