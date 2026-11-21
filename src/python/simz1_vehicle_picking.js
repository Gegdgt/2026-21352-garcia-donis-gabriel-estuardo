/* Screen-space selection only. It never changes marker size, native data or motion. */
class SimZ1VehiclePicking {
  static radius(pointerType='mouse') {
    return pointerType==='touch' ? 18 : 8;
  }
  static key(marker) {
    const vehicle=marker?.vehicle;
    if(typeof vehicle!=='string' && !(typeof vehicle==='number' && Number.isFinite(vehicle)))return null;
    if(String(vehicle).length===0)return null;
    return JSON.stringify([String(vehicle),
      String(marker.Replay_Journey_Key ?? marker.Trip?.Trip_ID ?? marker.Agent_ID ?? marker.Trip?.Person_ID ?? ''),
      String(marker.Agent_ID ?? marker.Trip?.Person_ID ?? '')]);
  }
  /** Closed footprint of the displayed rigid PathLayer body; never a route path. */
  static bodyOutline(marker) {
    const path=marker?.Visual_Body_Path,width=marker?.Visual_Body_Width_Meters;
    if(marker?.Visual_Body_Representable===false || !Array.isArray(path) || path.length!==2 ||
       !path.every(point=>Array.isArray(point) && point.length>=2 && point.slice(0,2).every(Number.isFinite)) ||
       !Number.isFinite(width) || width<=0)return null;
    // The body path already includes its final lane/queue/turn pose. Convert only
    // its perpendicular half width into local geographic coordinates.
    const metresPerDegree=6371008.8*Math.PI/180;
    const xScale=metresPerDegree*Math.cos((path[0][1]+path[1][1])*Math.PI/360);
    if(!Number.isFinite(xScale) || xScale<=1e-8)return null;
    const dx=(path[1][0]-path[0][0])*xScale,dy=(path[1][1]-path[0][1])*metresPerDegree;
    const length=Math.hypot(dx,dy);
    if(!(length>0))return null;
    const ox=-dy/length*width/2/xScale,oy=dx/length*width/2/metresPerDegree;
    const a=path[0],b=path[1];
    const corners=[[a[0]+ox,a[1]+oy],[b[0]+ox,b[1]+oy],[b[0]-ox,b[1]-oy],[a[0]-ox,a[1]-oy]];
    return [...corners,[...corners[0]]];
  }
  static outlineDistance(outline,x,y) {
    let inside=false,distance=Infinity;
    for(let i=0;i<outline.length-1;i++) {
      const a=outline[i],b=outline[i+1],dx=b[0]-a[0],dy=b[1]-a[1],lengthSquared=dx*dx+dy*dy;
      const t=lengthSquared ? Math.max(0,Math.min(1,((x-a[0])*dx+(y-a[1])*dy)/lengthSquared)) : 0;
      distance=Math.min(distance,Math.hypot(x-a[0]-t*dx,y-a[1]-t*dy));
      if((a[1]>y)!==(b[1]>y) && x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0])inside=!inside;
    }
    return inside || distance<1e-8 ? 0 : distance;
  }
  /**
   * x/y, projected positions and width/height use the same CSS-pixel canvas frame.
   * project(position, marker) is supplied by the current Deck viewport. Call with
   * current visible markers on pointer events; no cache survives a seek or zoom.
   */
  static pick(markers,{x,y,project,width,height,pointerType='mouse',radiusPixels}={}) {
    const radius=radiusPixels ?? this.radius(pointerType);
    if(!Array.isArray(markers) || typeof project!=='function' ||
       !Number.isFinite(x) || !Number.isFinite(y) || !Number.isFinite(radius) || radius<0)return null;
    if(width!==undefined && (!Number.isFinite(width) || width<=0) ||
       height!==undefined && (!Number.isFinite(height) || height<=0))return null;
    const right=width ?? Infinity,bottom=height ?? Infinity;
    if(x<0 || y<0 || x>right || y>bottom)return null;
    let nearest=null,nearestDistance=Infinity,nearestCenter=Infinity,nearestKey=null,nearestInside=false;
    for(const marker of markers) {
      if(marker?.opacity===0 || marker?.Visual_Queue_Opacity===0 || marker?.Visual_Body_Opacity===0 ||
         marker?.Visual_Queue_Representable===false || marker?.Visual_Body_Representable===false)continue;
      const key=this.key(marker),position=marker?.position;
      if(key===null || !Array.isArray(position) || position.length<2 ||
         !Number.isFinite(position[0]) || !Number.isFinite(position[1]))continue;
      let screen;
      try {screen=project(position,marker);} catch {continue;}
      if(!screen || !Number.isFinite(screen[0]) || !Number.isFinite(screen[1]))continue;
      const centerDistance=Math.hypot(screen[0]-x,screen[1]-y),outline=this.bodyOutline(marker);
      let distance=centerDistance,insideBody=false;
      if(outline) {
        let projected;
        try {projected=outline.map(point=>project(point,marker));} catch {continue;}
        if(projected.some(point=>!point || !Number.isFinite(point[0]) || !Number.isFinite(point[1])))continue;
        // A body whose centre has left the viewport may still be visibly clickable.
        if(projected.every(p=>p[0]<0) || projected.every(p=>p[0]>right) ||
           projected.every(p=>p[1]<0) || projected.every(p=>p[1]>bottom))continue;
        distance=this.outlineDistance(projected,x,y);insideBody=distance===0;
      } else if(marker.Visual_Body_Representable===true || Object.hasOwn(marker,'Visual_Body_Path') ||
                Object.hasOwn(marker,'Visual_Body_Width_Meters') || Object.hasOwn(marker,'Visual_Body_Length_Meters')) {
        // A declared but invalid rigid footprint is not a visible legacy point.
        // Falling back to its centre would manufacture an unrelated 8/18px hit.
        continue;
      } else if(screen[0]<0 || screen[1]<0 || screen[0]>right || screen[1]>bottom)continue;
      if(distance>radius+1e-8)continue;
      // Interior hits beat nearby bodies. For overlapping bodies use the nearest
      // centre, then real identity. Geometry makes duplicate-identity ties stable.
      const stableKey=JSON.stringify([key,position,marker.Link_ID ?? '',marker.timestamps ?? [],marker.Visual_Body_Path ?? []]);
      const equalDistance=Math.abs(distance-nearestDistance)<=1e-8,equalCenter=Math.abs(centerDistance-nearestCenter)<=1e-8;
      if(distance<nearestDistance-1e-8 || equalDistance && (centerDistance<nearestCenter-1e-8 ||
         equalCenter && (nearestKey===null || stableKey<nearestKey))) {
        nearest=marker;nearestDistance=distance;nearestCenter=centerDistance;nearestKey=stableKey;nearestInside=insideBody;
      }
    }
    return nearest===null ? null : {object:nearest,distancePixels:nearestDistance,centerDistancePixels:nearestCenter,
      insideBody:nearestInside,radiusPixels:radius};
  }
}
if(typeof module!=='undefined' && module.exports)module.exports=SimZ1VehiclePicking;
