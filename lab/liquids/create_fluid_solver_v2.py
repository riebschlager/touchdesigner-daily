"""Build Fluid Solver V2: a GPU dye solver with a shaded 2.5D liquid surface.

Paste into a Text DAT and Run Script. Creates a new fluid_solver_v2 Base COMP.
No pip dependencies; shaders and runtime are embedded. See README.md for inputs,
units, controls, outputs, numerical limitations, and validation instructions.
"""

MAX_SOURCES = 64
# V1 base SHA256: bfb255a141324e8be2147fa57756672620ea38f7a1ef9c628d948363fee954ab

COMMON = r'''
uniform vec4 uSim;     // dt, boundary (0 closed / 1 periodic), source count, age
uniform vec4 uFluid;   // velocity decay, viscosity, confinement, buoyancy
uniform vec4 uForce;   // wind x/y, maximum speed, motion strength
uniform vec4 uDye;     // dye decay, dye rate, MacCormack enabled, density cap
uniform vec4 uLook;    // exposure, opacity, view, transparent
uniform vec4 uBg;
uniform vec4 uSurface;    // height scale, density sensitivity, smoothing sigma, surface mode
uniform vec4 uMaterial;   // roughness, specular strength, edge Fresnel, reflection strength
uniform vec4 uLight;      // azimuth radians, elevation radians, intensity, ambient
uniform vec4 uLightcolor; // light RGB, diffuse strength
uniform vec4 uResidue;    // opacity, sensitivity, fade/sec, color follow/sec
uniform vec4 uExtra;      // residue enabled, Matcap assigned, Matcap strength, rotation
layout(location=0) out vec4 fragColor;
ivec2 size(){ return ivec2(uTDOutputInfo.res.zw); }
float h(){ return 1.0/float(size().y); }
bool outside(ivec2 p){ return any(lessThan(p,ivec2(0))) || any(greaterThanEqual(p,size())); }
ivec2 indexOf(ivec2 p){
    ivec2 n=size();
    return uSim.y>0.5 ? (p%n+n)%n : clamp(p,ivec2(0),n-1);
}
vec4 cell(sampler2D t, ivec2 p){ return texelFetch(t,indexOf(p),0); }
// Explicit interpolation avoids dependence on a TOP's hardware sampler settings.
vec4 linearAt(sampler2D t, vec2 p){
    ivec2 i=ivec2(floor(p)); vec2 f=fract(p);
    return mix(mix(cell(t,i),cell(t,i+ivec2(1,0)),f.x),
               mix(cell(t,i+ivec2(0,1)),cell(t,i+ivec2(1,1)),f.x),f.y);
}
// Texel (i,j) stores u at (i+1,j+.5), v at (i+.5,j+1).
float face(sampler2D t, ivec2 p, int axis){
    if(uSim.y<.5 && ((axis==0 && (p.x<0 || p.x>=size().x-1)) ||
                    (axis==1 && (p.y<0 || p.y>=size().y-1)))) return 0.;
    return cell(t,p)[axis];
}
float faceLinear(sampler2D t, vec2 p, int axis){
    ivec2 i=ivec2(floor(p)); vec2 f=fract(p);
    return mix(mix(face(t,i,axis),face(t,i+ivec2(1,0),axis),f.x),
               mix(face(t,i+ivec2(0,1),axis),face(t,i+ivec2(1,1),axis),f.x),f.y);
}
vec2 faceCell(sampler2D t, ivec2 p){return vec2(face(t,p,0),face(t,p,1));}
// Coordinates are in cell-center index space; interpolate staggered components.
vec2 velocityAt(sampler2D t, vec2 p){
    return vec2(faceLinear(t,p-vec2(.5,0),0),faceLinear(t,p-vec2(0,.5),1));
}
vec2 trace(sampler2D t, vec2 p, float dt){
    vec2 mid=p-.5*dt*velocityAt(t,p)/h();
    return p-dt*velocityAt(t,mid)/h();
}
vec2 wall(vec2 v, ivec2 p){
    if(uSim.y<.5){
        if(p.x==size().x-1) v.x=0.;
        if(p.y==size().y-1) v.y=0.;
    }
    return v;
}
float divergence(sampler2D t, ivec2 p){
    return (face(t,p,0)-face(t,p-ivec2(1,0),0)+
            face(t,p,1)-face(t,p-ivec2(0,1),1))/h();
}
void emit(vec4 v){ fragColor=TDOutputSwizzle(v); }
'''

SHADERS = {
'zero': 'void main(){emit(vec4(0));}',
'advect_velocity': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy); vec2 p=vec2(i);
    vec2 pu=trace(sTD2DInputs[0],p+vec2(.5,0),uSim.x);
    vec2 pv=trace(sTD2DInputs[0],p+vec2(0,.5),uSim.x);
    vec2 v=vec2(faceLinear(sTD2DInputs[0],pu-vec2(.5,0),0),
                faceLinear(sTD2DInputs[0],pv-vec2(0,.5),1));
    emit(vec4(wall(v*exp(-uFluid.x*uSim.x),i),0,0));
}''',
'curl': r'''
float omega(ivec2 p){
    return (velocityAt(sTD2DInputs[0],vec2(p+ivec2(1,0))).y-
            velocityAt(sTD2DInputs[0],vec2(p-ivec2(1,0))).y-
            velocityAt(sTD2DInputs[0],vec2(p+ivec2(0,1))).x+
            velocityAt(sTD2DInputs[0],vec2(p-ivec2(0,1))).x)/(2.*h());
}
void main(){emit(vec4(omega(ivec2(gl_FragCoord.xy)),0,0,0));}
''',
'forces': r'''
vec2 centerForce(ivec2 p){
    float w=cell(sTD2DInputs[2],p).x;
    vec2 g=vec2(abs(cell(sTD2DInputs[2],p+ivec2(1,0)).x)-abs(cell(sTD2DInputs[2],p-ivec2(1,0)).x),
                abs(cell(sTD2DInputs[2],p+ivec2(0,1)).x)-abs(cell(sTD2DInputs[2],p-ivec2(0,1)).x));
    g/=max(length(g),1e-6);
    return uForce.xy + uFluid.z*h()*w*vec2(g.y,-g.x) +
           vec2(0,uFluid.w*cell(sTD2DInputs[1],p).a);
}
float weight(vec2 p, vec2 a, vec2 b, float radius){
    vec2 d=p-b; vec2 ab=a-b;
    if(uSim.y>.5){
        vec2 domain=vec2(float(size().x)/float(size().y),1);
        d-=round(d/domain)*domain; ab-=round(ab/domain)*domain;
    }
    d-=ab*clamp(dot(d,ab)/max(dot(ab,ab),1e-12),0.,1.);
    float q=length(d)/max(radius,h()*.5);
    return exp(-4.*q*q)*(1.-smoothstep(.9,1.,q));
}
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy); vec2 p=vec2(i);
    vec2 f=vec2(.5*(centerForce(i).x+centerForce(i+ivec2(1,0)).x),
                 .5*(centerForce(i).y+centerForce(i+ivec2(0,1)).y));
    vec2 aspect=vec2(float(size().x)/float(size().y),1);
    for(int s=0;s<64;++s){
        if(s>=int(uSim.z)) break;
        vec4 pos=texelFetch(sTD2DInputs[3],ivec2(s,0),0);
        vec4 col=texelFetch(sTD2DInputs[3],ivec2(s,1),0);
        vec4 force=texelFetch(sTD2DInputs[3],ivec2(s,2),0);
        vec2 prev=texelFetch(sTD2DInputs[3],ivec2(s,3),0).xy;
        vec2 a=pos.xy*aspect, b=prev*aspect;
        vec2 weights=vec2(weight((p+vec2(1,.5))*h(),a,b,pos.z),
                          weight((p+vec2(.5,1))*h(),a,b,pos.z));
        f+=force.xy*weights*col.a;
    }
    vec2 v=cell(sTD2DInputs[0],i).xy+uSim.x*f;
    v*=min(1.,uForce.z/max(length(v),1e-8));
    emit(vec4(wall(v,i),0,0));
}''',
'diffuse': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy);
    float a=uFluid.y*uSim.x/(h()*h());
    vec2 neighbors=faceCell(sTD2DInputs[0],i+ivec2(1,0))+faceCell(sTD2DInputs[0],i-ivec2(1,0))+
                   faceCell(sTD2DInputs[0],i+ivec2(0,1))+faceCell(sTD2DInputs[0],i-ivec2(0,1));
    vec2 v=(cell(sTD2DInputs[1],i).xy+a*neighbors)/(1.+4.*a);
    emit(vec4(wall(v,i),0,0));
}''',
'divergence': r'''
void main(){emit(vec4(divergence(sTD2DInputs[0],ivec2(gl_FragCoord.xy)),0,0,0));}
''',
'pressure': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy);
    ivec2 dirs[4]=ivec2[4](ivec2(1,0),ivec2(-1,0),ivec2(0,1),ivec2(0,-1));
    float sum=0., count=0.;
    for(int k=0;k<4;++k){
        ivec2 j=i+dirs[k];
        if(uSim.y>.5 || !outside(j)){sum+=cell(sTD2DInputs[0],j).x; count+=1.;}
    }
    float old=cell(sTD2DInputs[0],i).x;
    float next=(sum-h()*h()*cell(sTD2DInputs[1],i).x)/max(count,1.);
    // Weighted Jacobi damps the alternating mode of a periodic even grid.
    emit(vec4(mix(old,next,2./3.),0,0,0));
}''',
'project': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy); float p=cell(sTD2DInputs[1],i).x;
    vec2 grad=vec2(cell(sTD2DInputs[1],i+ivec2(1,0)).x-p,
                   cell(sTD2DInputs[1],i+ivec2(0,1)).x-p)/h();
    emit(vec4(wall(cell(sTD2DInputs[0],i).xy-grad,i),0,0));
}''',
'dye_forward': r'''
void main(){
    vec2 p=gl_FragCoord.xy-.5;
    emit(linearAt(sTD2DInputs[0],trace(sTD2DInputs[1],p,uSim.x)));
}''',
'dye_reverse': r'''
void main(){
    vec2 p=gl_FragCoord.xy-.5;
    emit(linearAt(sTD2DInputs[0],trace(sTD2DInputs[1],p,-uSim.x)));
}''',
'dye_correct': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy);
    vec4 f=cell(sTD2DInputs[1],i);
    if(uDye.z>.5){
        vec2 back=trace(sTD2DInputs[3],vec2(i),uSim.x);
        ivec2 b=ivec2(floor(back));
        vec4 a=cell(sTD2DInputs[0],b), c=cell(sTD2DInputs[0],b+ivec2(1,0));
        vec4 d=cell(sTD2DInputs[0],b+ivec2(0,1)), e=cell(sTD2DInputs[0],b+ivec2(1,1));
        vec4 corrected=f+.5*(cell(sTD2DInputs[0],i)-cell(sTD2DInputs[2],i));
        f=clamp(corrected,min(min(a,c),min(d,e)),max(max(a,c),max(d,e)));
    }
    emit(max(f,vec4(0))*exp(-uDye.x*uSim.x));
}''',
'dye_inject': r'''
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy); vec4 dye=cell(sTD2DInputs[0],i);
    vec2 aspect=vec2(float(size().x)/float(size().y),1);
    vec2 p=gl_FragCoord.xy*h();
    for(int s=0;s<64;++s){
        if(s>=int(uSim.z)) break;
        vec4 pos=texelFetch(sTD2DInputs[1],ivec2(s,0),0);
        vec4 col=texelFetch(sTD2DInputs[1],ivec2(s,1),0);
        vec2 a=pos.xy*aspect;
        vec2 b=texelFetch(sTD2DInputs[1],ivec2(s,3),0).xy*aspect;
        vec2 d=p-b, ab=a-b;
        if(uSim.y>.5){d-=round(d/aspect)*aspect; ab-=round(ab/aspect)*aspect;}
        d-=ab*clamp(dot(d,ab)/max(dot(ab,ab),1e-12),0.,1.);
        float q=length(d)/max(pos.z,h()*.5);
        float w=exp(-4.*q*q)*(1.-smoothstep(.9,1.,q));
        dye+=vec4(col.rgb,1)*w*pos.w*col.a*uDye.y*uSim.x;
    }
    // Preserve hue when capping accumulated density.
    dye*=min(1.,uDye.w/max(dye.a,1e-8));
    emit(max(dye,vec4(0)));
}''',
'display': r'''
const float PI=3.141592653589793;
vec3 lampDirection(){
    float az=uLight.x, el=uLight.y;
    return vec3(cos(el)*cos(az),cos(el)*sin(az),sin(el));
}
vec3 fresnelSchlick(float cosine,vec3 f0){
    return f0+(1.-f0)*pow(1.-clamp(cosine,0.,1.),5.);
}
vec3 surfaceColor(vec3 base,vec3 n){
    vec3 v=vec3(0,0,1), l=lampDirection(), halfway=normalize(l+v);
    float nl=max(dot(n,l),0.), nv=max(n.z,.001), nh=max(dot(n,halfway),0.);
    float vh=max(dot(v,halfway),0.);
    float rough=clamp(uMaterial.x,.08,1.);
    float a=rough*rough, a2=a*a;
    float denominator=nh*nh*(a2-1.)+1.;
    float distribution=a2/(PI*denominator*denominator+1e-7);
    float k=(rough+1.)*(rough+1.)/8.;
    float geometry=(nl/(nl*(1.-k)+k))*(nv/(nv*(1.-k)+k));
    vec3 f0=vec3(.04);
    vec3 fresnel=fresnelSchlick(vh,f0);
    vec3 specular=distribution*geometry*fresnel/max(4.*nl*nv,.001);
    vec3 lit=base*(uLight.w+uLightcolor.w*nl*uLight.z*uLightcolor.rgb);
    lit+=specular*uMaterial.y*nl*uLight.z*uLightcolor.rgb;

    // Analytic studio environment: two softboxes plus a cool ambient reflection.
    // This keeps the default self-contained; an external Matcap is optional.
    vec3 reflected=reflect(-v,n);
    float width=.08+.5*rough, height=.35+.4*rough;
    float box=exp(-pow((reflected.x+.32)/width,4.)-pow((reflected.y-.48)/height,4.));
    float fill=exp(-pow((reflected.x-.55)/(.15+.4*rough),4.)-pow((reflected.y+.25)/(.3+.4*rough),4.));
    vec3 environment=vec3(.12,.18,.28)+vec3(3.)*box+vec3(.6,.8,1.2)*fill;
    vec3 edgeF=fresnelSchlick(nv,f0);
    lit+=environment*(f0+uMaterial.z*(edgeF-f0))*uMaterial.w;
    if(uExtra.y>.5 && uExtra.z>0.){
        float angle=uExtra.w;
        vec2 matuv=mat2(cos(angle),-sin(angle),sin(angle),cos(angle))*n.xy*.5+.5;
        vec3 matcap=texture(sTD2DInputs[4],matuv).rgb;
        lit+=matcap*uExtra.z;
    }
    return max(lit,vec3(0));
}
void main(){
    ivec2 i=ivec2(gl_FragCoord.xy);
    vec4 d=cell(sTD2DInputs[0],i);
    vec4 normalHeight=cell(sTD2DInputs[2],i);
    vec3 n=normalize(normalHeight.rgb*2.-1.);
    vec4 stain=cell(sTD2DInputs[3],i);
    vec2 v=velocityAt(sTD2DInputs[1],vec2(i));
    float alpha=1.-exp(-max(d.a,0.)*uLook.y);
    vec3 color=d.rgb/max(d.a,1e-8);
    if(uLook.z<.5){
        vec3 wet=uSurface.w>.5 ? surfaceColor(color,n) : color;
        float film=clamp(stain.a*uResidue.x*uExtra.x,0.,1.);
        vec3 dry=stain.rgb*(uSurface.w>.5 ? uLight.w+uLightcolor.w*max(lampDirection().z,0.)*uLight.z*uLightcolor.rgb : vec3(1));
        vec3 premult=(wet*alpha+dry*film*(1.-alpha))*uLook.x;
        float total=alpha+film*(1.-alpha);
        if(uLook.w>.5) emit(vec4(premult,total));
        else emit(vec4(premult+uBg.rgb*(1.-total),1));
    } else if(uLook.z<1.5) emit(vec4(vec3(1.-exp(-d.a*uLook.x)),1));
    else if(uLook.z<2.5) emit(vec4(.5+.5*v/uForce.z,0,1));
    else if(uLook.z<3.5){float div=divergence(sTD2DInputs[1],i);emit(vec4(max(div,0),0,max(-div,0),1));}
    else if(uLook.z<4.5) emit(vec4(vec3(normalHeight.a/max(uSurface.x,1e-8)),1));
    else if(uLook.z<5.5) emit(vec4(normalHeight.rgb,1));
    else {
        float coverage=stain.a*uExtra.x;
        emit(vec4(stain.rgb*coverage+uBg.rgb*(1.-coverage),1));
    }
}''',
'height_source': r'''
void main(){
    float density=max(cell(sTD2DInputs[0],ivec2(gl_FragCoord.xy)).a,0.);
    float height=uSurface.x*(1.-exp(-density*uSurface.y));
    emit(vec4(height,0,0,1));
}''',
'height_blur_x': r'''
void main(){
    ivec2 p=ivec2(gl_FragCoord.xy);
    float sigma=uSurface.z;
    if(sigma<.01){emit(cell(sTD2DInputs[0],p));return;}
    float sum=0., weight=0.;
    for(int k=-12;k<=12;++k){
        float w=exp(-.5*float(k*k)/(sigma*sigma));
        sum+=w*cell(sTD2DInputs[0],p+ivec2(k,0)).r; weight+=w;
    }
    emit(vec4(sum/weight,0,0,1));
}''',
'height_field': r'''
void main(){
    ivec2 p=ivec2(gl_FragCoord.xy);
    float sigma=uSurface.z;
    if(sigma<.01){emit(cell(sTD2DInputs[0],p));return;}
    float sum=0., weight=0.;
    for(int k=-12;k<=12;++k){
        float w=exp(-.5*float(k*k)/(sigma*sigma));
        sum+=w*cell(sTD2DInputs[0],p+ivec2(0,k)).r; weight+=w;
    }
    emit(vec4(sum/weight,0,0,1));
}''',
'surface_normals': r'''
void main(){
    ivec2 p=ivec2(gl_FragCoord.xy);
    float dx=cell(sTD2DInputs[0],p+ivec2(1,0)).r-cell(sTD2DInputs[0],p-ivec2(1,0)).r;
    float dy=cell(sTD2DInputs[0],p+ivec2(0,1)).r-cell(sTD2DInputs[0],p-ivec2(0,1)).r;
    vec3 n=normalize(vec3(-dx/(2.*h()),-dy/(2.*h()),1));
    emit(vec4(n*.5+.5,cell(sTD2DInputs[0],p).r));
}''',
'residue_update': r'''
void main(){
    ivec2 p=ivec2(gl_FragCoord.xy);
    vec4 old=cell(sTD2DInputs[0],p), dye=cell(sTD2DInputs[1],p);
    float current=1.-exp(-max(dye.a,0.)*uResidue.y);
    float remaining=old.a*exp(-uResidue.z*uSim.x);
    float coverage=max(remaining,current);
    vec3 color=dye.rgb/max(dye.a,1e-8);
    float recolor=(1.-exp(-uResidue.w*uSim.x))*current;
    // Newly covered areas take the incoming color immediately. Existing film
    // gradually recolors, keeping a stationary stain when the flow moves away.
    float newCoverage=max(0.,current-remaining)/max(coverage,1e-8);
    vec3 pigment=mix(old.rgb,color,max(newCoverage,recolor));
    if(coverage<1e-7) pigment=vec3(0);
    emit(vec4(max(pigment,vec3(0)),clamp(coverage,0.,1.)));
}''',
'velocity_output': r'''
void main(){
    vec2 v=velocityAt(sTD2DInputs[0],gl_FragCoord.xy-.5);
    // RG is signed UV / simulation second, directly usable for displacement.
    emit(vec4(v/vec2(float(size().x)/float(size().y),1),0,1));
}'''
}

RUNTIME = r'''
import math
import re
import time
import numpy as np

MAX_SOURCES = 64

def value(c, name):
    return getattr(c.par, name).eval()

def state(c):
    s=c.fetch('Fluidstate', None)
    if s is None:
        reset(c)
        s=c.fetch('Fluidstate')
    return s

def capture(c, dest, source):
    target=c.op(dest) if isinstance(dest,str) else dest
    source=c.op(source) if isinstance(source,str) else source
    source.cook(force=True)
    target.inputConnectors[0].connect(source)
    if (target.width,target.height)!=(source.width,source.height):
        target.par.resetpulse.pulse()
    target.par.replace=True
    try:
        target.cook(force=True)
    finally:
        target.par.replace=False
        # Inactive cache retains its texture. Remove graph cycles between ticks.
        target.inputConnectors[0].connect(c.op('zero'))

def bind(c, reader, source):
    c.op(reader).par.top=source
    c.op(reader).cook(force=True)

def reset(c):
    c.store('Fluidstate', {'v':0,'d':0,'p':0,'s':0,'age':0.,'debt':0.,
                         'last':time.monotonic(),'frame':None,'previous':{},
                         'signature':None,'size':(int(value(c,'Width')),int(value(c,'Height')),
                                                value(c,'Boundary'))})
    c.store('Dt',0.)
    c.store('Sourcecount',0)
    c.store('Sourcearray',np.zeros((4,64,4),np.float32))
    for name in ('v_a','v_b','d_a','d_b','p_a','p_b','rhs','div_buffer','forward_buffer','reverse_buffer','curl_buffer','s_a','s_b'):
        capture(c,name,'zero')
    for name,source in [('velocity_read','v_a'),('dye_read','d_a'),('pressure_read','p_a'),('residue_read','s_a')]:
        bind(c,name,source)
    c.par.Simtime=0
    c.par.Simlag=0
    c.par.Sources=0
    c.par.Status='Ready'

def read_sources(c, elapsed):
    """Accept sampled x/y channels or numbered x0/y0 channel pairs; strict lengths."""
    explicit=value(c,'Sourcechop')
    wired=c.op('sources_input')
    wired.cook(force=True)
    source=explicit if explicit is not None else (wired if wired.numChans else None)
    s=state(c)
    signature=(source.path if source else None, value(c,'Colorschop').path if value(c,'Colorschop') else None,
               value(c,'Coordinates'))
    if signature!=s['signature']:
        s['previous']={}
        s['signature']=signature
    color=value(c,'Colorschop')
    if color is not None: color.cook(force=True)
    rows=[]
    def chan(chop,name):
        return chop[name] if chop is not None else None
    def sample(chop,name,index,n,default):
        ch=chan(chop,name)
        if ch is None: return default
        if len(ch) not in (1,n): raise ValueError(name+' needs 1 or '+str(n)+' samples')
        result=float(ch[0 if len(ch)==1 else index])
        if not math.isfinite(result): raise ValueError(name+' must be finite')
        return result
    groups=[('',1)]
    if source is not None:
        source.cook(force=True)
        if chan(source,'x') is not None and chan(source,'y') is not None:
            n=max(len(source['x']),len(source['y']))
            groups=[('',n)]
        else:
            suffixes=sorted({ch.name[1:] for ch in source.chans() if re.fullmatch(r'x\d+',ch.name)},key=int)
            if not suffixes: raise ValueError('Source CHOP needs x/y or x0/y0, x1/y1...')
            groups=[]
            for suffix in suffixes:
                if chan(source,'y'+suffix) is None: raise ValueError('Missing y'+suffix)
                groups.append((suffix,max(len(source['x'+suffix]),len(source['y'+suffix]))))
    if sum(n for _,n in groups)>MAX_SOURCES: raise ValueError('Maximum 64 sources; reduce input sample count')
    current={}
    for suffix,n in groups:
        for i in range(n):
            def get(name,default,other=None):
                ch=other if other is not None else source
                specific=name+suffix
                # Unsuffixed fields broadcast to numbered droppers.
                field=specific if chan(ch,specific) is not None else name
                return sample(ch,field,i,n,default)
            x=get('x',value(c,'X')); y=get('y',value(c,'Y'))
            if not math.isfinite(x) or not math.isfinite(y): raise ValueError('Position must be finite')
            if value(c,'Coordinates')=='pixels':
                x/=max(1,int(value(c,'Width'))-1); y/=max(1,int(value(c,'Height'))-1)
            if value(c,'Boundary')=='wrap': x%=1.; y%=1.
            else: x=min(1.,max(0.,x)); y=min(1.,max(0.,y))
            enabled=max(0.,min(1.,get('active',1.)))*float(value(c,'Emit'))
            key=(suffix,i)
            prev=s['previous'].get(key,(x,y,enabled))
            if not enabled or not prev[2]: prev=(x,y,enabled)
            dx=x-prev[0]; dy=y-prev[1]
            if value(c,'Boundary')=='wrap': dx-=round(dx); dy-=round(dy)
            aspect=value(c,'Width')/value(c,'Height')
            jump=math.hypot(dx*aspect,dy)
            if jump>value(c,'Teleport'): prev=(x,y,enabled); dx=dy=0.
            rate=max(elapsed,1e-6)
            fx=get('vx',value(c,'Jetx'))+dx*aspect/rate*value(c,'Motionforce')
            fy=get('vy',value(c,'Jety'))+dy/rate*value(c,'Motionforce')
            limit=value(c,'Maxforce'); length=math.hypot(fx,fy)
            if length>limit: fx*=limit/length; fy*=limit/length
            rgb=[get(k,value(c,k.upper()),color) for k in ('r','g','b')]
            radius=max(.0001,get('radius',value(c,'Radius')))
            amount=max(0.,get('amount',1.))
            rgb=[max(0.,v) if math.isfinite(v) else v for v in rgb]
            flat=[x,y,radius,amount]+rgb+[enabled,fx,fy,0.,0.,prev[0],prev[1],0.,0.]
            if not all(math.isfinite(v) for v in flat): raise ValueError('Source values must be finite')
            rows.append(flat)
            current[key]=(x,y,enabled)
    array=np.zeros((4,64,4),np.float32)
    with np.errstate(over='raise',invalid='raise'):
        for j,row in enumerate(rows): array[:,j,:]=np.asarray(row,np.float32).reshape(4,4)
    s['previous']=current
    c.store('Sourcearray',array)
    c.store('Sourcecount',len(rows))
    c.par.Sources=len(rows)
    c.op('source_upload').cook(force=True)
    return array

def swap(c,kind,shader):
    s=state(c); dest=1-s[kind]
    name=kind+'_'+('a','b')[dest]
    capture(c,name,shader)
    s[kind]=dest
    bind(c,{'v':'velocity_read','d':'dye_read','p':'pressure_read','s':'residue_read'}[kind],name)

def substep(c,dt):
    c.store('Dt',dt)
    swap(c,'v','advect_velocity')
    capture(c,'curl_buffer','curl')
    swap(c,'v','forces')
    if value(c,'Viscosity')>0:
        capture(c,'rhs','velocity_read')
        for _ in range(int(value(c,'Viscosityiterations'))): swap(c,'v','diffuse')
    capture(c,'div_buffer','divergence')
    # Cold-start pressure prevents stale gradients after source/boundary edits.
    capture(c,'p_a','zero'); capture(c,'p_b','zero')
    state(c)['p']=0; bind(c,'pressure_read','p_a')
    for _ in range(int(value(c,'Pressureiterations'))): swap(c,'p','pressure')
    swap(c,'v','project')
    capture(c,'forward_buffer','dye_forward')
    if value(c,'Advection')=='maccormack': capture(c,'reverse_buffer','dye_reverse')
    swap(c,'d','dye_correct')
    swap(c,'d','dye_inject')
    if value(c,'Residue'): swap(c,'s','residue_update')
    state(c)['age']+=dt

def tick(c,dt=None):
    dt=float(value(c,'Timestep') if dt is None else dt)
    # Read once per tick. Each substep covers the same swept source path; rates
    # integrate over dt, so changing substeps does not multiply dye/force amount.
    read_sources(c,dt)
    n=int(value(c,'Substeps'))
    for _ in range(n): substep(c,dt/n)
    c.par.Simtime=state(c)['age']

def advance(c,elapsed=None):
    s=state(c)
    size=(int(value(c,'Width')),int(value(c,'Height')),value(c,'Boundary'))
    if size!=s['size']: reset(c); s=state(c)
    now=time.monotonic()
    delta=now-s['last'] if elapsed is None else elapsed
    s['last']=now
    if value(c,'Pause'): s['previous']={}; return
    if value(c,'Clock')=='frame': delta=1./value(c,'Renderfps')
    s['debt']+=max(0.,delta)*value(c,'Speed')
    dt=value(c,'Timestep')
    count=min(int((s['debt']+1e-10)/dt),int(value(c,'Maxticks')))
    for _ in range(count):
        tick(c,dt); s['debt']=max(0.,s['debt']-dt)
    c.par.Simlag=s['debt']
    c.par.Status='Running' if count else 'Ready'

def step(c):
    if value(c,'Pause'): tick(c)

def safe_advance(c):
    try: advance(c)
    except Exception as error:
        c.par.Pause=True
        c.par.Status=str(error)
        raise
'''

SOURCE_CALLBACKS = r'''
import numpy as np
def onCook(scriptOp):
    a=scriptOp.parent().fetch('Sourcearray',None)
    if a is None: a=np.zeros((4,64,4),np.float32)
    scriptOp.copyNumpyArray(a)
'''
CLOCK_CALLBACKS = r'''
def onFrameStart(frame):
    c=me.parent()
    if not c.fetch('Ready',False): return
    r=c.op('runtime').module
    s=r.state(c)
    if s['frame']==absTime.frame: return
    s['frame']=absTime.frame
    r.safe_advance(c)
def onStart():
    c=me.parent()
    if c.fetch('Ready',False): c.op('runtime').module.reset(c)
def onCreate():
    c=me.parent()
    if c.fetch('Ready',False): c.op('runtime').module.reset(c)
def onPlayStateChange(state):
    c=me.parent()
    if c.fetch('Ready',False):
        c.op('runtime').module.state(c)['last']=__import__('time').monotonic()
'''
CONTROL_CALLBACKS = r'''
def onPulse(par):
    c=me.parent(); r=c.op('runtime').module
    if par.name=='Reset': r.reset(c)
    elif par.name=='Step': r.step(c)
    elif par.name=='Cleardye':
        r.capture(c,'d_a','zero'); r.capture(c,'d_b','zero')
    elif par.name=='Clearresidue':
        r.capture(c,'s_a','zero'); r.capture(c,'s_b','zero')
def onValueChange(par,prev):
    c=me.parent()
    if not c.fetch('Ready',False): return
    r=c.op('runtime').module
    if par.name in ('Width','Height','Boundary'): r.reset(c)
    elif par.name in ('Pause','Clock','Speed','Timestep'):
        s=r.state(c); s['last']=__import__('time').monotonic(); s['debt']=0.; s['previous']={}
'''


def _set(node,name,value):
    p=getattr(node.par,name,None)
    if p is None: raise RuntimeError('Missing TouchDesigner parameter: '+node.path+'.'+name)
    if isinstance(value,str) and p.menuNames and value not in p.menuNames:
        raise RuntimeError('Unsupported '+node.path+'.'+name+': '+value)
    p.val=value
    return p


def _create(parent,kind,name,x,y):
    # Use TDAPI when installed; native fallback matches the other project builders.
    api=getattr(op,'TDAPI',None)
    if api is not None:
        node=api.CreateOp(parent,kind,name,x=x,y=y)
    else:
        node=parent.create(kind,name)
        node.nodeX,node.nodeY=x,y
        for j,d in enumerate(node.docked): d.nodeX,d.nodeY=x,y-160*(j+1)
    node.viewer=True
    return node


def _number(page,name,label,default,lo,hi,integer=False):
    p=(page.appendInt if integer else page.appendFloat)(name,label=label)[0]
    p.default=p.val=default
    p.min=p.normMin=lo; p.max=p.normMax=hi
    p.clampMin=p.clampMax=True
    return p


def _toggle(page,name,label,default):
    p=page.appendToggle(name,label=label)[0]; p.default=p.val=default
    return p


def _menu(page,name,label,items,default):
    p=page.appendMenu(name,label=label)[0]
    p.menuNames=[a for a,b in items]; p.menuLabels=[b for a,b in items]
    p.default=p.val=default
    return p


def build_fluid_solver_v2(container=None):
    if container is None: container=me.parent()
    api=getattr(op,'TDAPI',None)
    if api is not None:
        # Skill-required discovery; also checked individually in _set.
        for kind in ('glslTOP','cacheTOP','scriptTOP','executeDAT','parameterexecuteDAT'):
            api.GetParameterList(kind)
    name='fluid_solver_v2'; i=2
    while container.op(name): name='fluid_solver_v2_'+str(i); i+=1
    x=max([n.nodeX+250 for n in container.children] or [0])
    c=_create(container,baseCOMP,name,x,0)
    c.store('Ready',False)
    page=c.appendCustomPage('Simulation')
    for args in [('Width','Grid Width',384,32,2048,True),('Height','Grid Height',256,32,2048,True),
                 ('Timestep','Tick (seconds)',1/60,.001,.05,False),('Speed','Speed',1,0,4,False),
                 ('Substeps','Substeps per Tick',2,1,8,True),('Pressureiterations','Pressure Iterations',50,4,200,True),
                 ('Renderfps','Frame Clock FPS',60,1,240,False),('Maxticks','Max Ticks per Frame',2,1,16,True)]:
        _number(page,*args)
    _menu(page,'Clock','Clock',[('frame','Frame Stepped'),('realtime','Real Time')],'frame')
    _menu(page,'Boundary','Boundary',[('closed','Closed / Free Slip'),('wrap','Periodic')],'closed')
    _toggle(page,'Pause','Pause',False)
    for n,l in [('Step','Step One Tick'),('Reset','Reset All'),('Cleardye','Clear Dye')]: page.appendPulse(n,label=l)
    page=c.appendCustomPage('Sources')
    page.appendCHOP('Sourcechop',label='Position / Source CHOP')
    page.appendCHOP('Colorschop',label='Color CHOP (optional override)')
    _menu(page,'Coordinates','Position Coordinates',[('uv','Normalized 0 to 1'),('pixels','Grid Pixels')],'uv')
    _toggle(page,'Emit','Emit Dye and Source Force',True)
    for args in [('X','Dropper X',.5,0,2048),('Y','Dropper Y',.25,0,2048),
                 ('R','Dye Red',.08,0,16),('G','Dye Green',.5,0,16),('B','Dye Blue',1.,0,16),
                 ('Radius','Radius (fraction of height)',.045,.001,.5),('Dyerate','Dye Density / Second',12,0,200),
                 ('Jetx','Jet X (acceleration)',0,-20,20),('Jety','Jet Y (acceleration)',1.,-20,20),
                 ('Motionforce','Motion Force Gain (1/s)',8.,0,100),('Maxforce','Max Source Acceleration',20.,.01,100),
                 ('Teleport','Teleport Distance (height units)',.35,.01,2.)]: _number(page,*args)
    c.par.X.normMax=1; c.par.Y.normMax=1
    page=c.appendCustomPage('Fluid')
    for args in [('Velocitydecay','Velocity Decay (1/s)',.12,0,10),('Viscosity','Kinematic Viscosity',0.,0,.01),
                 ('Viscosityiterations','Viscosity Iterations',20,2,100,True),('Vorticity','Vorticity Confinement',12.,0,80),
                 ('Buoyancy','Density Buoyancy',.2,-10,10),('Windx','Wind X Acceleration',0.,-10,10),
                 ('Windy','Wind Y Acceleration',0.,-10,10),('Maxspeed','Max Speed (height/s)',2.,.01,10),
                 ('Dyedecay','Dye Decay (1/s)',.2,0,10),('Densitycap','Maximum Dye Density',20.,.1,100)]: _number(page,*args)
    _menu(page,'Advection','Dye Advection',[('maccormack','Limited MacCormack'),('semi','Semi-Lagrangian')],'maccormack')
    page=c.appendCustomPage('Appearance')
    _number(page,'Exposure','Exposure',1.,0,10); _number(page,'Opacity','Density to Opacity',1.,0,10)
    _toggle(page,'Transparent','Transparent (premultiplied)',False)
    for name in ('Bgr','Bgg','Bgb'): _number(page,name,'Background '+name[-1].upper(),.012,0,1)
    _menu(page,'View','View',[('dye','Dye'),('density','Density'),('velocity','Velocity'),('divergence','Divergence'),('height','Height'),('normals','Surface Normals'),('residue','Residue')],'dye')
    page=c.appendCustomPage('Surface')
    _menu(page,'Renderstyle','Render Style',[('surface','Shaded Surface'),('flat','Flat Dye')],'surface')
    for args in [('Heightscale','Maximum Height (height units)',.025,0,.15),
                 ('Heightsensitivity','Density to Height',1.5,.01,10),
                 ('Heightsmoothing','Height Smoothing (sigma / cells)',1.25,0,4),
                 ('Roughness','Surface Roughness',.28,.08,1),
                 ('Specular','Specular Strength',1.,0,4),
                 ('Fresnel','Edge Fresnel Strength',1.,0,3),
                 ('Reflection','Studio Reflection Strength',1.,0,4),
                 ('Ambient','Ambient Light',.42,0,2),
                 ('Diffuse','Diffuse Strength',.65,0,2),
                 ('Lightazimuth','Light Azimuth (degrees)',135,-180,180),
                 ('Lightelevation','Light Elevation (degrees)',55,5,89),
                 ('Lightintensity','Light Intensity',1.4,0,6),
                 ('Lightred','Light Red',1.,0,3),('Lightgreen','Light Green',1.,0,3),('Lightblue','Light Blue',1.,0,3),
                 ('Matcapstrength','Matcap Reflection Strength',.35,0,3),
                 ('Matcaprotation','Matcap Rotation (degrees)',0.,-180,180)]:
        _number(page,*args)
    page.appendTOP('Matcaptop',label='Optional Matcap TOP')
    page=c.appendCustomPage('Residue')
    _toggle(page,'Residue','Enable Residue',True)
    for args in [('Residueopacity','Residue Opacity',.35,0,1),
                 ('Residuesensitivity','Density to Residue Coverage',.7,.01,10),
                 ('Residuefade','Residue Fade (1 / second)',.08,0,5),
                 ('Residuecolorfollow','Residue Recolor Rate (1 / second)',4.,0,50)]:
        _number(page,*args)
    page.appendPulse('Clearresidue',label='Clear Residue / Keep Fluid')
    page=c.appendCustomPage('Diagnostics')
    for name,label in [('Simtime','Simulation Seconds'),('Simlag','Time Debt (seconds)'),('Sources','Source Count')]:
        p=page.appendFloat(name,label=label)[0]; p.readOnly=True
    p=page.appendStr('Status',label='Status')[0]; p.readOnly=True
    runtime=_create(c,textDAT,'runtime',-1000,600); runtime.text=RUNTIME
    inp=_create(c,inCHOP,'sources_in',-1000,350)
    null=_create(c,nullCHOP,'sources_input',-800,350); null.inputConnectors[0].connect(inp)
    upload=_create(c,scriptTOP,'source_upload',-600,350)
    upload.par.callbacks.eval().text=SOURCE_CALLBACKS
    _set(upload,'format','rgba32float'); _set(upload,'resmult',False)
    sources=_create(c,nullTOP,'sources',-400,350); sources.inputConnectors[0].connect(upload)

    uniforms=[('uSim',["parent().fetch('Dt',0)","float(parent().par.Boundary.eval()=='wrap')", "parent().fetch('Sourcecount',0)","parent().par.Simtime"]),
              ('uFluid',["parent().par."+p for p in ('Velocitydecay','Viscosity','Vorticity','Buoyancy')]),
              ('uForce',["parent().par."+p for p in ('Windx','Windy','Maxspeed','Motionforce')]),
              ('uDye',["parent().par.Dyedecay","parent().par.Dyerate","float(parent().par.Advection.eval()=='maccormack')","parent().par.Densitycap"]),
              ('uLook',["parent().par.Exposure","parent().par.Opacity","parent().par.View.menuIndex","parent().par.Transparent"]),
              ('uBg',["parent().par.Bgr","parent().par.Bgg","parent().par.Bgb","1"]),
              ('uSurface',["parent().par.Heightscale","parent().par.Heightsensitivity","parent().par.Heightsmoothing","float(parent().par.Renderstyle.eval()=='surface')"]),
              ('uMaterial',["parent().par."+p for p in ('Roughness','Specular','Fresnel','Reflection')]),
              ('uLight',["parent().par.Lightazimuth*math.pi/180","parent().par.Lightelevation*math.pi/180","parent().par.Lightintensity","parent().par.Ambient"]),
              ('uLightcolor',["parent().par."+p for p in ('Lightred','Lightgreen','Lightblue','Diffuse')]),
              ('uResidue',["parent().par."+p for p in ('Residueopacity','Residuesensitivity','Residuefade','Residuecolorfollow')]),
              ('uExtra',["float(parent().par.Residue)","float(parent().par.Matcaptop.eval() is not None)","parent().par.Matcapstrength","parent().par.Matcaprotation*math.pi/180"])]
    for j,(name,body) in enumerate(SHADERS.items()):
        col,row=j%4,j//4
        node=_create(c,glslTOP,name,col*350, -row*650)
        _set(node,'mode','vertexpixel'); _set(node,'glslversion','glsl460')
        _set(node,'compilebehavior','stalluntildone')
        _set(node,'format','rgba32float'); _set(node,'resmult',False)
        _set(node,'outputresolution','custom')
        node.par.resolutionw.expr='parent().par.Width'; node.par.resolutionh.expr='parent().par.Height'
        _set(node,'inputfiltertype','nearest'); _set(node,'inputextenduv','hold')
        node.par.pixeldat.eval().text=COMMON+body
        seq=getattr(node.seq,'vec',None)
        if seq is not None: seq.numBlocks=len(uniforms)
        for k,(uname,expressions) in enumerate(uniforms):
            _set(node,'vec'+str(k)+'name',uname)
            for axis,expr in zip('xyzw',expressions): getattr(node.par,'vec'+str(k)+'value'+axis).expr=expr
    for j,name in enumerate(('v_a','v_b','d_a','d_b','p_a','p_b','rhs','div_buffer','forward_buffer','reverse_buffer','curl_buffer','s_a','s_b')):
        node=_create(c,cacheTOP,name,-1000+(j%3)*300,-100-(j//3)*230)
        node.inputConnectors[0].connect(c.op('zero'))
        for key,val in [('cachesize',1),('active',False),('cacheonce',False),('alwayscook',False),
                        ('replace',False),('replaceindex',0),('outputindex',0),('format','rgba32float'),('resmult',False)]: _set(node,key,val)
    for j,(name,source) in enumerate([('velocity_read','v_a'),('dye_read','d_a'),('pressure_read','p_a'),('residue_read','s_a')]):
        node=_create(c,selectTOP,name,-1000+j*300,-1200); _set(node,'top',source)
    matcap=_create(c,selectTOP,'matcap_source',1500,-700)
    matcap.par.top.expr="parent().par.Matcaptop.eval().path if parent().par.Matcaptop.eval() is not None else 'zero'"
    matcap_null=_create(c,nullTOP,'matcap_input',1750,-700)
    matcap_null.inputConnectors[0].connect(matcap)
    wiring={
        'advect_velocity':['velocity_read'], 'curl':['velocity_read'],
        'forces':['velocity_read','dye_read','curl_buffer','sources'],
        'diffuse':['velocity_read','rhs'], 'divergence':['velocity_read'],
        'pressure':['pressure_read','div_buffer'], 'project':['velocity_read','pressure_read'],
        'dye_forward':['dye_read','velocity_read'], 'dye_reverse':['forward_buffer','velocity_read'],
        'dye_correct':['dye_read','forward_buffer','reverse_buffer','velocity_read'],
        'dye_inject':['dye_read','sources'],
        'height_source':['dye_read'],'height_blur_x':['height_source'],'height_field':['height_blur_x'],
        'surface_normals':['height_field'],'residue_update':['residue_read','dye_read'],
        'display':['dye_read','velocity_read','surface_normals','residue_read','matcap_input'],
        'velocity_output':['velocity_read']}
    for name,inputs in wiring.items():
        for k,source in enumerate(inputs[:3]): c.op(name).inputConnectors[k].connect(c.op(source))
        if len(inputs)>3: _set(c.op(name),'tops',' '.join(inputs[3:]))
    for j,(name,source) in enumerate([('out1','display'),('out2','dye_read'),('out3','velocity_output'),('out4','height_field'),('out5','surface_normals'),('out6','residue_read')]):
        node=_create(c,outTOP,name,1500,200-j*200); node.inputConnectors[0].connect(c.op(source))
    _set(c.op('display'),'inputfiltertype','linear')
    c.par.opviewer='out1'
    clock=_create(c,executeDAT,'clock',-1000,-1600); _set(clock,'active',False); clock.text=CLOCK_CALLBACKS
    for name in ('framestart','start','create','playstatechange'): _set(clock,name,True)
    _set(clock,'frameend',False)
    controls=_create(c,parameterexecuteDAT,'controls',-700,-1600); _set(controls,'active',False)
    controls.text=CONTROL_CALLBACKS
    for key,val in [('op','..'),('pars','Reset Step Cleardye Clearresidue Width Height Boundary Pause Clock Speed Timestep'),
                    ('custom',True),('builtin',False),('onpulse',True),('valuechange',True)]: _set(controls,key,val)
    runtime.module.reset(c)
    # Compile every pass before enabling the clock. Shader failures remain visible.
    for name in SHADERS:
        c.op(name).cook(force=True)
        errors=c.op(name).errors()
        if errors: raise RuntimeError(name+': '+errors)
    c.store('Ready',True)
    _set(controls,'active',True); controls.cook(force=True)
    _set(clock,'active',True)
    c.par.Status='Ready'
    if api is not None: api.CheckErrors(c,recurse=True)
    print('Created '+c.path+' — connect source CHOP or edit Sources; view out1.')
    return c


if 'op' in globals() and 'me' in globals():
    fluid_v2_component=build_fluid_solver_v2()
elif __name__=='__main__':
    print('Run this file inside a TouchDesigner Text DAT. See README_V2.md.')
