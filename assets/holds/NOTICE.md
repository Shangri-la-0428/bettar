# External climbing-hold geometry

The SetRsoft meshes in this directory originate from the [SetRsoft Climbing Holds 3D dataset](https://huggingface.co/datasets/setrsoft/climbing-holds). Attribution: SetRsoft dataset contributors; individual scanner names were not supplied in the selected records. The original files, source URLs and SHA-256 hashes are retained alongside the normalized library.

The dataset declares [Creative Commons Attribution-ShareAlike 4.0 International](https://creativecommons.org/licenses/by-sa/4.0/). Modified mesh geometry is distributed under that same license. The unmodified upstream README is included as `SETRSOFT-UPSTREAM-README.md`. That README separately reserves manufacturers' shape rights and describes educational/gym-management use; this copy is not permission to manufacture branded holds for sale. No endorsement is implied.

Changes made for this local prototype: applied GLB scene/node transforms; changed to a right-handed wall-local frame; centered the footprint and placed its rear minimum at z=0; welded coincident texture-seam vertices before mesh reduction; reduced triangle count where recorded; omitted the original texture; added draft contact and installation annotations. Welding adds no surface and does not fill real holes. Three selected scans become closed meshes after welding and remain closed after reduction; the pinch retains open boundaries from its source. Original dimensions were not measured or independently calibrated. `asset_scale` is a uniform demonstration scaling, never a recovered manufacturer's dimension.

`library.json` records per-asset sources, original and normalized geometry hashes, transformations, classification evidence, exact triangle anchors and contact-region triangle IDs. Contact regions, effective pull directions and backplate annotations are AI-assisted first drafts for routesetter review. Friction and load capacity are not measured from the mesh. The application still uses conservative bounding boxes for collision checks and synthetic grasp envelopes for static diagnostics.

Asset preparation is reproducible with `requirements-assets.txt`, `scripts/prepare_hold_assets.py`, `scripts/annotate_hold_assets.py` and the explicit `work/external-holds/selection.json` configuration. The application runtime does not download or execute third-party content.

The jug, crimp and sloper now have a separate `standing` annotation on their
exterior upper surface. Their representative points and normals are bound to
mesh triangles 1490, 2560 and 1993 respectively; record hashes include these
annotations. The jug's inner grip and the pinch's side grips remain hand-only.
The pinch has no declared standing surface because its current annotations do
not establish an exterior upper foothold. These are conservative AI-assisted
contact proposals, not measured friction, shoe fit or human forerun evidence.
An explicit state `contact_id` selects one of these surfaces; the legacy
`main` alias still selects the placement's default surface.
