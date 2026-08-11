# Offline Python wheelhouse

Place wheels downloaded for `requirements.txt` in this directory before an
air-gapped image build, then build with `--build-arg PIP_OFFLINE=1`.
The README is only a placeholder; no package is downloaded at runtime.
