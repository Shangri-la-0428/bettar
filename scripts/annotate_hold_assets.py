"""Build the reviewed contact library from normalized meshes and explicit targets.
Targets/pull directions are draft setter annotations, not measured grip capacities.
All stored representative contacts are exact triangle barycentric points.
"""
from pathlib import Path
import json,sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from boulderlab.hold_assets import asset_hash,validate_asset
from prepare_hold_assets import render

TARGETS={
 'jug':[
  dict(id='working',label='凹唇内沿 · 向下抓握',target=[0,-.060,.044],normal=[0,1,.15],radii=[.070,.022],pull=[0,-1,0]),
  dict(id='alternate',label='左侧凹唇 · 侧向抓握',target=[-.070,-.025,.040],normal=[1,.3,.4],radii=[.030,.018],pull=[-.8,-.6,0]),
  dict(id='standing',label='洞外上沿 · 鞋尖踩面（草稿）',target=[-.015258463333,.101536646667,.015261546667],normal=[-.329535,.802176,.497917],radii=[.018,.006],pull=[0,-1,0],limbs=['LF','RF'])],
 'crimp':[
  dict(id='working',label='上缘浅扣边',target=[-.015,.026,.011],normal=[0,1,.4],radii=[.025,.006],pull=[0,-1,0]),
  dict(id='alternate',label='右段浅扣边',target=[.035,.023,.009],normal=[0,1,.5],radii=[.018,.005],pull=[0,-1,0]),
  dict(id='standing',label='上缘浅台 · 鞋尖踩面（草稿）',target=[.00120264,.02778645,.010688386667],normal=[.131332,.990889,.029839],radii=[.018,.004],pull=[0,-1,0],limbs=['LF','RF'])],
 'pinch':[
  dict(id='working',label='左侧捏握面（与右面配对）',target=[-.075,0,.050],normal=[-1,0,.1],radii=[.060,.018],pull=[0,-1,0],axis=[0,1,0]),
  dict(id='alternate',label='右侧捏握面（与左面配对）',target=[.075,0,.050],normal=[1,0,.1],radii=[.060,.018],pull=[0,-1,0],axis=[0,1,0])],
 'sloper':[
  dict(id='working',label='上部圆坡摩擦面',target=[.060,.085,.135],normal=[0,.65,.76],radii=[.085,.050],pull=[0,-1,0]),
  dict(id='alternate',label='左上圆坡摩擦面',target=[-.100,.050,.110],normal=[-.3,.65,.70],radii=[.060,.040],pull=[.3,-.954,0]),
  dict(id='standing',label='外部上坡 · 摩擦踩面（草稿）',target=[.00030235,.102507566667,.087170153333],normal=[-.220560,.782398,.582414],radii=[.050,.025],pull=[0,-1,0],limbs=['LF','RF'])]
}
LABELS={'jug':'SetRsoft 12 · 凹唇 Jug','crimp':'SetRsoft 25 · 浅边 Crimp','pinch':'SetRsoft 17 · 长块 Pinch','sloper':'SetRsoft 11 · 圆坡 Sloper'}

def surfaces(g,specs):
 v=np.array(g['positions']);f=np.array(g['triangles']);tri=v[f];centers=tri.mean(1)
 cross=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);normals=cross/np.linalg.norm(cross,axis=1)[:,None]
 out=[]
 for spec in specs:
  target=np.array(spec['target']);wish=np.array(spec['normal']);wish/=np.linalg.norm(wish)
  score=np.linalg.norm(centers-target,axis=1)+.015*(1-normals@wish)
  # Exclude back surfaces and strongly opposing sides before selecting a mesh face.
  score[(normals@wish<.45)|(centers[:,2]<.003)]=np.inf
  i=int(np.argmin(score));pos=centers[i];n=normals[i]
  seed=np.array(spec.get('axis',[1,0,0]),float);u=seed-n*(seed@n);u/=np.linalg.norm(u);vv=np.cross(n,u)
  delta=centers-pos;r=spec['radii']
  ids=np.flatnonzero(((delta@u/r[0])**2+(delta@vv/r[1])**2<1.1)&(np.abs(delta@n)<max(r)*.50)&(normals@n>.15)).tolist()
  if i not in ids:ids.append(i)
  s=dict(id=spec['id'],label=spec['label'],position=pos.tolist(),normal=n.tolist(),u_axis=u.tolist(),v_axis=vv.tolist(),radii=r,limbs=spec.get('limbs',['LH','RH']),pull_direction=spec['pull'],mesh_anchor={'triangle_index':i,'barycentric':[1/3,1/3,1/3]},annotations={'triangle_indices':sorted(ids)})
  out.append(s)
 return out

def main():
 rows=json.loads((ROOT/'work/external-holds/selection.json').read_text())['assets'];assets=[]
 for row in rows:
  family=row['family']
  if family not in TARGETS:continue
  data=json.loads((ROOT/'work/external-holds/normalized'/(row['id']+'.json')).read_text());g=data['geometry'];dims=np.ptp(np.array(g['positions']),axis=0)
  asset=dict(id=row['id'],family=family,label=LABELS[family],geometry=g,geometry_sha256=asset_hash(g),width=float(dims[0]),height=float(dims[1]),depth=float(dims[2]),
   source={'url':f"https://huggingface.co/datasets/setrsoft/climbing-holds/tree/main/{row['upstream_id']}",'author':'SetRsoft dataset contributors; individual scanner not specified','license':'CC BY-SA 4.0','license_url':'https://creativecommons.org/licenses/by-sa/4.0/','original_sha256':data['provenance']['original_sha256'],'upstream_id':row['upstream_id'],'rights_note':'Dataset permits educational/gym-management use; branded shape rights remain with manufacturers. No commercial manufacturing authorization.'},
   scale={'basis':'GLB 名义米制，原始扫描没有实测校准；线路按演示宽度同比缩放，数值不代表厂家尺寸。','verified':False},
   installation={'kind':'backplate','origin':[0,0,0],'normal':[0,0,-1],'basis':'依据扫描平背面，把局部 XY 作为安装面、Z 向外；保留真实外轮廓，未验证螺栓规格、背板平整度与安装强度。','verified':False},
   classification={'basis':'AI multi-view geometric inspection; original metadata type unknown','confidence':'provisional','observation':{'jug':'Broad positive recessed lip; bolt recess excluded.','crimp':'Low-profile narrow upper edge, rather than a universal difficulty grade.','pinch':'Two opposing elongated side faces; paired physical squeeze is approximated by the grasp envelope.','sloper':'Broad convex friction-dependent surface; no positive lip inferred.'}[family]},
   annotation_basis='AI-reviewed draft geometry annotations; not a human routesetter or forerun certification. Surface roughness/friction and load capacity unmeasured.',
   grip_surfaces=surfaces(g,TARGETS[family]),preparation=data['provenance'])
  if family=='pinch':asset['contact_pair']={'surface_ids':['working','alternate'],'mechanics':'single representative synthetic grasp envelope; not two solved fingers'}
  asset['asset_record_sha256']=asset_hash(asset);validate_asset(asset);assets.append(asset)
  render(row,g,asset['grip_surfaces'])
  print(row['id'],[(s['id'],s['mesh_anchor']['triangle_index'],np.round(s['position'],4).tolist(),np.round(s['normal'],3).tolist(),len(s['annotations']['triangle_indices'])) for s in asset['grip_surfaces']],flush=True)
 library={'schema_version':'hold-assets/1','assets':assets}
 (ROOT/'assets/holds/library.json').write_text(json.dumps(library,ensure_ascii=False,separators=(',',':'))+'\n')
if __name__=='__main__':main()
