"""Trusted local inspection: render upstream GLB geometry, no source execution.

PCA axes are display axes only, never installation or calibrated dimensions.
"""
from pathlib import Path
import json, struct, math
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'inspection'; OUT.mkdir(exist_ok=True)
FONT=ImageFont.load_default()

def quaternion(q):
    x,y,z,w=q
    return np.array([[1-2*y*y-2*z*z,2*x*y-2*z*w,2*x*z+2*y*w],
                     [2*x*y+2*z*w,1-2*x*x-2*z*z,2*y*z-2*x*w],
                     [2*x*z-2*y*w,2*y*z+2*x*w,1-2*x*x-2*y*y]])

def load(path):
    raw=path.read_bytes(); at=12; chunks={}
    while at<len(raw):
        length,kind=struct.unpack_from('<II',raw,at);chunks[kind]=raw[at+8:at+8+length];at+=8+length
    j=json.loads(chunks[0x4e4f534a]); binary=chunks[0x004e4942]
    def accessor(i):
        a=j['accessors'][i]; bv=j['bufferViews'][a['bufferView']]
        dtype={5126:'<f4',5125:'<u4',5123:'<u2',5121:'u1'}[a['componentType']]
        dim={'SCALAR':1,'VEC2':2,'VEC3':3,'VEC4':4}[a['type']]; n=a['count']
        offset=bv.get('byteOffset',0)+a.get('byteOffset',0); stride=bv.get('byteStride',np.dtype(dtype).itemsize*dim)
        return np.ndarray((n,dim),dtype=dtype,buffer=binary,offset=offset,strides=(stride,np.dtype(dtype).itemsize)).copy()
    vertices=[]; faces=[]
    def visit(i,parent):
        node=j['nodes'][i]; m=np.eye(4)
        if 'matrix' in node:m=np.asarray(node['matrix']).reshape(4,4).T
        else:
            m[:3,:3]=quaternion(node.get('rotation',[0,0,0,1])) @ np.diag(node.get('scale',[1,1,1]));m[:3,3]=node.get('translation',[0,0,0])
        m=parent@m
        if 'mesh' in node:
            for primitive in j['meshes'][node['mesh']]['primitives']:
                if primitive.get('mode',4)!=4:raise ValueError('nontriangle primitive')
                v=accessor(primitive['attributes']['POSITION']); v=v@m[:3,:3].T+m[:3,3]
                f=accessor(primitive['indices']).reshape(-1,3) if 'indices' in primitive else np.arange(len(v)).reshape(-1,3)
                start=sum(len(x) for x in vertices); vertices.append(v);faces.append(f+start)
        for child in node.get('children',[]):visit(child,m)
    for i in j['scenes'][j.get('scene',0)]['nodes']:visit(i,np.eye(4))
    v=np.concatenate(vertices);f=np.concatenate(faces)
    center=v.mean(0);cov=(v-center).T@(v-center);values,axes=np.linalg.eigh(cov);axes=axes[:,np.argsort(values)[::-1]]
    if np.linalg.det(axes)<0:axes[:,-1]*=-1
    p=(v-center)@axes; extent=np.ptp(p,axis=0);p/=.5*max(extent)
    info={'vertices':len(v),'triangles':len(f),'scene_extent_gltf_units':np.ptp(v,axis=0).tolist(),'pca_extent_gltf_units':extent.tolist(),'display_center_world':center.tolist(),'display_axes_columns':axes.tolist(),'asset':j.get('asset'), 'scale_calibration':'unknown; glTF nominal metre convention does not verify scan dimensions'}
    return p,f,info

def render(points,faces,view,sz=220):
    # Orthographic, physically original triangles; no shape edits or smoothing.
    az,el=np.radians(view);forward=np.array([math.sin(az)*math.cos(el),math.sin(el),math.cos(az)*math.cos(el)])
    right=np.cross([0,1,0],forward);right/=np.linalg.norm(right);up=np.cross(forward,right)
    basis=np.array([right,up,forward]);p=points@basis.T
    xy=p[:,:2]*(sz*.37);xy[:,0]+=sz/2;xy[:,1]=sz/2-xy[:,1]
    tri=p[faces];normals=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]);nlen=np.linalg.norm(normals,axis=1);normals/=np.maximum(nlen[:,None],1e-10)
    light=np.array([-.4,.7,1.]);light/=np.linalg.norm(light);intensity=.28+.72*np.abs(normals@light)
    image=Image.new('RGB',(sz,sz),(239,242,244));d=ImageDraw.Draw(image)
    for i in np.argsort(tri[:,:,2].mean(axis=1)):
        if nlen[i]<1e-12:continue
        color=tuple(int(c*intensity[i]) for c in (105,173,205));d.polygon([tuple(x) for x in xy[faces[i]]], fill=color)
    return image

records=[]; paths=sorted((ROOT/'setrsoft').glob('*/hold.glb'))
for path in paths:
    pid=path.parent.name;p,f,info=load(path)
    panel=Image.new('RGB',(660,480),'white');d=ImageDraw.Draw(panel)
    for i,view in enumerate([(20,15),(160,15),(80,15),(0,65),(180,65),(0,-65)]):
        panel.paste(render(p,f,view),(i%3*220,i//3*240));d.text((i%3*220+5,i//3*240+222),f'{view[0]}az {view[1]}el',font=FONT,fill='black')
    panel.save(OUT/f'{pid}-views.png');info['id']=pid;records.append(info)
    print(pid,info['triangles'],flush=True)
sheet=Image.new('RGB',(5*440,math.ceil(len(paths)/5)*250),'white');draw=ImageDraw.Draw(sheet)
for i,path in enumerate(paths):
    pid=path.parent.name;p,f,_=load(path);x=i%5*440;y=i//5*250
    sheet.paste(render(p,f,(20,15)),(x,y));sheet.paste(render(p,f,(160,15)),(x+220,y));draw.text((x+6,y+224),f'{pid} front/back PCA display only',font=FONT,fill='black')
sheet.save(OUT/'all-holds-front-back.png');(OUT/'geometry-inspection.json').write_text(json.dumps(records,indent=2))
