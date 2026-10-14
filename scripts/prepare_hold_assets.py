"""Reproducible local preparation of selected licensed upstream meshes.

No network, no upstream code execution. GLB scene/node transforms are applied.
The mesh is uniformly scaled only; scan scale is explicitly uncalibrated.
Inspect generated views before supplying contact annotations in the config.
"""
from pathlib import Path
import json, hashlib, argparse
import numpy as np
import trimesh
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/external-holds/normalized'
CONFIG=ROOT/'work/external-holds/selection.json'

def digest(v):
    return 'sha256:'+hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def prepared(row):
    # The selected originals ship with the repository; the full download cache
    # is optional and deliberately excluded from public version control.
    src=ROOT/'assets/holds/originals'/(row['id']+'.glb')
    mesh=trimesh.load_scene(src).to_geometry()
    original_faces=len(mesh.faces)
    # The flat back is near the GLB scene's XZ plane in these selected scans.
    # Right-handed change of basis, followed by a reviewed installation turn.
    vertices=np.column_stack((mesh.vertices[:,0],-mesh.vertices[:,2],mesh.vertices[:,1]))
    a=np.deg2rad(row.get('rotation_deg',0))
    rotation=np.array([[np.cos(a),-np.sin(a),0],[np.sin(a),np.cos(a),0],[0,0,1]])
    vertices=vertices@rotation.T
    center=np.r_[(vertices.min(0)[:2]+vertices.max(0)[:2])/2,vertices.min(0)[2]]
    vertices-=center
    mesh=trimesh.Trimesh(vertices=vertices,faces=mesh.faces,process=False)
    # GLB UV seams duplicate coincident positions. Textures are intentionally
    # omitted, so weld these duplicates before decimation; otherwise the
    # simplifier treats texture seams as open geometric boundaries.
    vertices_before_weld=len(mesh.vertices)
    mesh.merge_vertices(merge_tex=True,merge_norm=True,digits_vertex=8)
    vertices_after_weld=len(mesh.vertices)
    watertight_before_simplification=bool(mesh.is_watertight)
    if len(mesh.faces)>row.get('triangle_budget',3500):
        mesh=mesh.simplify_quadric_decimation(face_count=row.get('triangle_budget',3500),aggression=3)
    # Recenter after decimation. No hole filling, convexification or heightfield conversion.
    offset=np.r_[(mesh.vertices.min(0)[:2]+mesh.vertices.max(0)[:2])/2,mesh.vertices.min(0)[2]]
    mesh.vertices-=offset
    vertices=np.round(mesh.vertices,8)
    geometry={'positions':vertices.tolist(),'triangles':mesh.faces.tolist()}
    return geometry,{'original_triangles':original_faces,'prepared_triangles':len(mesh.faces),'vertices_before_weld':vertices_before_weld,'vertices_after_weld':vertices_after_weld,'watertight_before_simplification':watertight_before_simplification,'watertight_after_simplification':bool(mesh.is_watertight),'scene_to_local_axes':[[1,0,0],[0,0,-1],[0,1,0]],'installation_rotation_deg':row.get('rotation_deg',0),'scene_local_translation':(-center).tolist(),'post_decimation_translation':(-offset).tolist(),'uniform_scale':1,'modifications':['apply GLB scene/node transforms','right-handed scene Y thickness to local Z depth','reviewed in-plane orientation','center XY footprint; back minimum Z=0','weld coincident texture-seam vertices at 1e-8 nominal units; no surface added','quadric mesh simplification when needed; no hole filling','omit original textures and use application material'],'original_sha256':'sha256:'+hashlib.sha256(src.read_bytes()).hexdigest()}

def render(row,g,anchors=None):
    v=np.array(g['positions']);f=np.array(g['triangles']);tri=v[f]
    cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);n=cross/np.maximum(np.linalg.norm(cross,axis=1)[:,None],1e-20)
    fig=plt.figure(figsize=(12,6.6),facecolor='#f4f2ed')
    for i,(el,az,name) in enumerate([(90,-90,'Front: X right / Y up'),(20,-65,'Oblique'),(0,0,'Right side')]):
        ax=fig.add_subplot(1,3,i+1,projection='3d');ax.set_proj_type('ortho')
        shade=.55+.45*np.maximum(0,n@np.array([.25,.50,.83]));color=np.clip(np.array([.65,.38,.25])*shade[:,None],0,1)
        ax.add_collection3d(Poly3DCollection(tri,facecolors=color,edgecolors='none'))
        lo=v.min(0);hi=v.max(0);extent=hi-lo;mid=(hi+lo)/2;radius=max(extent)/2
        ax.set(xlim=(mid[0]-radius,mid[0]+radius),ylim=(mid[1]-radius,mid[1]+radius),zlim=(mid[2]-radius,mid[2]+radius),xlabel='X',ylabel='Y',zlabel='Z')
        ax.set_box_aspect([1,1,1]);ax.view_init(el,az);ax.set_title(name,fontsize=10)
        if anchors:
            for p in anchors:
                xyz=np.array(p['position']);ax.scatter(*xyz,color='#00aaaa',s=30,depthshade=False);ax.text(*xyz,p['id'],fontsize=8)
    fig.suptitle(row['family']+' · SetRsoft '+row['upstream_id']+' · nominal GLB units, not calibrated',fontsize=12)
    fig.tight_layout();fig.savefig(OUT/(row['id']+'-views.png'),dpi=140);plt.close(fig)

def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=json.loads(CONFIG.read_text())['assets']
    for row in rows:
        geometry,provenance=prepared(row)
        path=OUT/(row['id']+'.json');path.write_text(json.dumps({'geometry':geometry,'provenance':provenance},separators=(',',':')))
        render(row,geometry)
        print(row['id'],np.ptp(np.array(geometry['positions']),axis=0).round(5).tolist(),len(geometry['triangles']),flush=True)
if __name__=='__main__':main()
