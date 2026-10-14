# BetaZero inference source

The optional offline hold-set generator adapts the MIT-licensed BetaZero
production inference code by Evan McCormick. Its upstream repository is
https://github.com/EvanMcCormick37/ml-homewall-climb-generator, pinned to commit
`6f0acb414a5f1ab070aa62d02ac98f2602011821`.

Source files: `climb-backend/app/services/utils/ddpm_model.py` and
`climb-backend/app/services/utils/generation_utils.py`. The architecture,
cosine/composite schedule, classifier-free guidance and manifold projection are
retained. The database/pool/service, training and evolutionary generator are
omitted. Inference is explicitly CPU, deterministic, 100 steps and x_offset=0.
The original MIT notice is retained in `BETAZERO-LICENSE.txt`.

The upstream repository includes production weights and scaler under its root
license, but supplies no separate model/data license statement. We link to and
download the exact upstream artifacts into ignored local storage; neither
weights nor upstream training data are redistributed in this repository.

`scripts/prepare_learned_model.py` pins file byte length, Git blob SHA-1 and
SHA-256. The scaler is never loaded with pickle or joblib: ten known float64
array slices are extracted only from the exact digest-verified 1841-byte
artifact, then validated and saved as primitive JSON. Checkpoints are loaded
with `torch.load(..., weights_only=True)` and strict state-dict matching.

The learned proposal is a selected set of installed holds with roles, not an
ordered beta. Model slots, discrete selections and upstream role repairs are
retained. Bettar's fixed anchors, permission checks and independent movement
search are separate stages. Target grades are model conditioning inputs only.

Runtime setup (from the repository root):

```sh
.venv/bin/python -m venv .runtime/venv-ml
.runtime/venv-ml/bin/python -m pip install --no-cache-dir -r requirements-ml.txt
.runtime/venv-ml/bin/python scripts/prepare_learned_model.py --generate-proposals fixtures/learned-wall-request.json
```

Only the optional worker environment needs PyTorch. Normal application startup,
saved experiment viewing and route validation work without this environment.
Model artifacts are approximately 87 MB; install size depends on the platform.
